#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

   All Rights Reserved

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License along
   with this program; if not, write to the Free Software Foundation, Inc.,
   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

   s. FLOSS-EXCEPTION.txt
"""

import functools
import sys
from collections import OrderedDict
from enum import IntEnum
from typing import Optional, Union

import numpy as np
import pya2l.model as model
from objutils import Image, Section, dump, load
from pya2l import DB
from pya2l.api.inspect import AxisPts, Characteristic, CompuMethod, ModCommon, ModPar
from pya2l.functions import fix_axis_par, fix_axis_par_dist
from pyxcp.cpp_ext.cpp_ext import McObject
from pyxcp.daq_stim.optimize import make_continuous_blocks

from asamint.asam import TYPE_SIZES, AsamBaseType, ByteOrder, get_section_reader
from asamint.logger import Logger

# from asamint.calibration import model as cmod
from asamint.model.calibration import klasses
from asamint.utils import SINGLE_BITS, current_timestamp, ffs


ver_info = sys.version_info

if ver_info.major == 3 and ver_info.minor < 10:
    ValueType = (float, int, bool, str)
else:
    ValueType = Union[float, int, bool, str]

BOOLEAN_MAP = {"true": 1, "false": 0}
AXES = ("x", "y", "z", "4", "5")

sys.setrecursionlimit(2000)  # Not required by asamint by itself, but if we run pyinstrument benchmarks...


class ExecutionPolicy(IntEnum):
    EXCEPT = 0
    RETURN_ERROR = 1
    IGNORE = 2


class Status(IntEnum):
    OK = 0
    READ_ONLY_ERROR = 1
    RANGE_ERROR = 2


class RangeError(Exception):
    pass


class ReadOnlyError(Exception):
    pass


def check_limits(characteristic, value: float, extended_limits: bool = False) -> bool:
    """
    Check if the value is within the limits of the characteristic.

    Parameters
    ----------
    value: float
        Value to check

    extended_limits: bool
        Also check extended limits if available

    Returns
    -------
    bool
    """
    if value < characteristic.lowerLimit or value > characteristic.upperLimit:
        return False
    if extended_limits and characteristic.extendedLimits:
        limits = characteristic.extendedLimits
        if value < limits.get("lowerLimit") or value > limits.get("upperLimit"):
            return False
    return True


class Calibration:
    """ """

    def __init__(self, a2l_db: DB, image, loglevel: str = "WARN") -> None:
        self.image = image
        self.a2l_db = a2l_db
        self.session = self.a2l_db.session
        self.logger = Logger(loglevel)
        self.mod_common = ModCommon.get(self.session)
        self.mod_par = ModPar.get(self.session) if ModPar.exists(self.session) else None

    def update(self):
        """To the actual update of parameters (write to HEX file / XCP)."""
        pass

    def load_ascii(self, characteristic_name: str) -> klasses.Ascii:
        characteristic = self.get_characteristic(characteristic_name, "ASCII", False)
        if characteristic.matrixDim:
            length = characteristic.matrixDim["x"]
        else:
            length = characteristic.number
        value = self.image.read_string(characteristic.address, length=length)
        return klasses.Ascii(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category="ASCII",
            value=value,
            displayIdentifier=characteristic.displayIdentifier,
            length=length,
        )

    def save_ascii(
        self,
        characteristic_name: str,
        value: str,
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
    ) -> Status:
        characteristic = self.get_characteristic(characteristic_name, "ASCII", True)
        if characteristic.readOnly:
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(f"Characteristic '{characteristic_name}' is read-only.")
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR
        if characteristic.matrixDim:
            length = characteristic.matrixDim["x"]
        else:
            length = characteristic.number
        self.image.write_string(characteristic.address, length=length, value=value)
        return Status.OK

    def load_value_block(self, characteristic_name: str) -> klasses.ValueBlock:
        characteristic = self.get_characteristic(characteristic_name, "VAL_BLK", False)
        reader = get_section_reader("UBYTE", 0)
        raw_values = self.image.read_ndarray(
            addr=characteristic.address,
            length=characteristic.fnc_allocated_memory,
            dtype=reader,
            shape=characteristic.fnc_np_shape,
            order=characteristic.fnc_np_order,
            bit_mask=characteristic.bitMask,
        )
        converted_values = self.int_to_physical(characteristic, raw_values)
        return klasses.ValueBlock(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category="VAL_BLK",
            raw_values=raw_values,
            converted_values=converted_values,
            displayIdentifier=characteristic.displayIdentifier,
            shape=characteristic.fnc_np_shape,
            unit=characteristic.physUnit,
        )

    def save_value_block(
        self,
        characteristic_name: str,
        values: np.ndarray,
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
    ) -> Status:
        characteristic = self.get_characteristic(characteristic_name, "VAL_BLK", True)
        if characteristic.readOnly:
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(f"Characteristic '{characteristic_name}' is read-only.")
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR
        values = self.physical_to_int(characteristic, values)
        self.image.write_ndarray(addr=characteristic.address, array=values, order=characteristic.fnc_np_order)
        return Status.OK

    def load_value(self, characteristic_name: str) -> klasses.Value:
        characteristic = self.get_characteristic(characteristic_name, "VALUE", False)

        # CALIBRATION_ACCESS
        fnc_asam_dtype = characteristic.fnc_asam_dtype
        reader = get_section_reader(fnc_asam_dtype, self.byte_order(characteristic))
        if characteristic.bitMask:
            raw_value = self.image.read_numeric(characteristic.address, reader, bit_mask=characteristic.bitMask)
            raw_value >>= ffs(characteristic.bitMask)  # Right-shift to get rid of trailing zeros (s. ASAM 2-MC spec).
            is_bool = True if characteristic.bitMask in SINGLE_BITS else False
        else:
            raw_value = self.image.read_numeric(characteristic.address, reader)
            is_bool = False
        if characteristic.physUnit is None and characteristic._conversionRef != "NO_COMPU_METHOD":
            unit = characteristic.compuMethod.unit
        else:
            unit = characteristic.physUnit
        converted_value = self.int_to_physical(characteristic, raw_value)
        if isinstance(converted_value, (int, float)):
            if is_bool:
                category = "BOOLEAN"
                converted_value = "true" if bool(converted_value) else "false"
            else:
                category = "VALUE"
        else:
            category = "TEXT"
        if characteristic.dependentCharacteristic:
            category = "DEPENDENT_VALUE"
        return klasses.Value(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category=category,
            raw_value=raw_value,
            converted_value=converted_value,
            displayIdentifier=characteristic.displayIdentifier,
            unit=unit,
        )

    def save_value(
        self,
        characteristic_name: str,
        value: ValueType,
        extendedLimits: bool = False,
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
        limitsPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
    ) -> Status:
        if not isinstance(value, ValueType):
            raise TypeError("value must be float, int, bool or str")
        characteristic = self.get_characteristic(characteristic_name, "VALUE", True)
        if characteristic.readOnly:
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(f"Characteristic '{characteristic_name}' is read-only.")
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR
        if characteristic.compuMethod.conversionType == "TAB_VERB":
            text_values = characteristic.compuMethod.tab_verb.get("text_values")
            if value not in text_values:
                raise ValueError(f"value must be in {text_values} got {value}.")
        else:
            if isinstance(value, bool):
                value = int(value)
            elif isinstance(value, str):
                pass
                if value in ("true", "false"):
                    value = BOOLEAN_MAP[value]
                else:
                    raise ValueError("value of type str must be 'true' or 'false'")
        dtype = get_section_reader(characteristic.fnc_asam_dtype, self.byte_order(characteristic))

        if isinstance(value, (int, float)) and not check_limits(characteristic, value, extendedLimits):
            self.logger.info(f"Characteristic '{characteristic_name}' is out of range")
            if limitsPolicy == ExecutionPolicy.EXCEPT:
                raise RangeError(f"Characteristic '{characteristic_name}' is out of range")
            elif limitsPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.RANGE_ERROR

        converted_value = self.physical_to_int(characteristic, value)
        if characteristic.bitMask:
            converted_value = int(converted_value)
            converted_value <<= ffs(characteristic.bitMask)
        self.image.write_numeric(characteristic.address, converted_value, dtype)
        return Status.OK

    def load_axis_pts(self, axis_pts_name: str) -> Status:
        axis_pts = self.get_axis_pts(axis_pts_name, False)
        rl_values = self.read_record_layout_values(axis_pts, "x")
        self.record_layout_correct_offsets(axis_pts)
        virtual = False
        axis = axis_pts.record_layout_components.axes("x")
        paired = False
        if "axisRescale" in axis:
            category = "RES_AXIS"
            paired = True
            if "noRescale" in rl_values:
                no_rescale_pairs = rl_values["noRescale"]
            else:
                no_rescale_pairs = axis["maxNumberOfRescalePairs"]
            index_incr = axis["axisRescale"]["indexIncr"]
            count = no_rescale_pairs * 2
            attr = "axisRescale"
        elif "axisPts" in axis:
            category = "COM_AXIS"
            if "noAxisPts" in rl_values:
                no_axis_points = rl_values["noAxisPts"]
            else:
                no_axis_points = axis["maxAxisPoints"]
            index_incr = axis["axisPts"]["indexIncr"]
            count = no_axis_points
            attr = "axisPts"
        elif "offset" in axis:
            category = "FIX_AXIS"
            virtual = True  # Virtual / Calculated axis.
            offset = rl_values.get("offset")
            dist_op = rl_values.get("distOp")
            shift_op = rl_values.get("shiftOp")
            if "noAxisPts" in rl_values:
                no_axis_points = rl_values["noAxisPts"]
            else:
                no_axis_points = axis["maxAxisPoints"]
            if (dist_op or shift_op) is None:
                raise TypeError(f"Malformed AXIS_PTS '{axis_pts}', neither DIST_OP nor SHIFT_OP specified.")
            if dist_op is not None:
                raw_values = fix_axis_par_dist(offset, dist_op, no_axis_points)
            else:
                raw_values = fix_axis_par(offset, shift_op, no_axis_points)
        else:
            raise TypeError(f"Malformed AXIS_PTS '{axis_pts}'.")
        if not virtual:
            raw_values = self.read_nd_array(axis_pts, "x", attr, count)
            if index_incr == "INDEX_DECR":
                raw_values = raw_values[::-1]
                reversed_storage = True
            else:
                reversed_storage = False
        converted_values = self.int_to_physical(axis_pts, raw_values)
        unit = axis_pts.compuMethod.refUnit
        return klasses.AxisPts(
            name=axis_pts.name,
            comment=axis_pts.longIdentifier,
            category=category,
            raw_values=raw_values,
            converted_values=converted_values,
            displayIdentifier=axis_pts.displayIdentifier,
            paired=paired,
            unit=unit,
            reversed_storage=reversed_storage,
        )

    def int_to_physical(self, characteristic, int_values):
        """Convert ECU internal values to physical representation."""
        cm = self.get_compu_method(characteristic)
        return cm.int_to_physical(int_values)

    def physical_to_int(self, characteristic, physical_values):
        """Convert physical values to ECU internal representation."""
        cm = self.get_compu_method(characteristic)
        return cm.physical_to_int(physical_values)

    def get_compu_method(self, characteristic):
        cm_name = "NO_COMPU_METHOD" if characteristic.compuMethod == "NO_COMPU_METHOD" else characteristic.compuMethod.name
        return CompuMethod.get(self.a2l_db.session, cm_name)

    def get_characteristic(self, characteristic_name, type_name: str, save: bool = False):
        characteristic = self._load_characteristic(characteristic_name, type_name)
        direction = "Saving" if save else "Loading"
        self.logger.debug(f"{direction} {type_name} '{characteristic.name}' @0x{characteristic.address:08x}")
        return characteristic

    def _load_characteristic(self, characteristic_name, category):
        try:
            characteristic = Characteristic.get(self.a2l_db.session, characteristic_name)
        except ValueError:
            raise
        if characteristic.type != category:
            raise TypeError(f"'{characteristic_name}' is not of type '{category}'")
        return characteristic

    def _save_characteristic(self, characteristic, value):
        pass

    def get_axis_pts(self, axis_pts_name, save: bool = False):
        axis_pts = self._load_axis_pts(axis_pts_name)
        direction = "Saving" if save else "Loading"
        self.logger.debug(f"{direction} AXIS_PTS '{axis_pts.name}' @0x{axis_pts.address:08x}")
        return axis_pts

    def _load_axis_pts(self, axis_pts_name):
        try:
            axis_pts = AxisPts.get(self.a2l_db.session, axis_pts_name)
        except ValueError:
            raise
        return axis_pts

    def byte_order(self, obj):
        """Get byte-order for A2L element.

        Parameters
        ----------
        obj: (`AxisPts` | `AxisDescr` | `Measurement` | `Characteristic`) instance.

        Returns
        -------
        `ByteOrder`:
            If element has no BYTE_ORDER, lookup MOD_COMMON else ByteOrder.BIG_ENDIAN
        """
        return (
            ByteOrder.BIG_ENDIAN
            if obj.byteOrder or self.mod_common.byteOrder in ("MSB_FIRST", "LITTLE_ENDIAN")
            else ByteOrder.LITTLE_ENDIAN
        )

    def record_layout_correct_offsets(self, obj):
        """ """
        no_axis_pts = {}
        no_rescale = {}
        axis_pts = {}
        axis_rescale = {}
        # fnc_values = None
        for _, component in obj.record_layout_components:
            component_type = component["type"]
            if component_type == "fncValues":
                # fnc_values = component
                pass
            elif len(component_type) == 2:
                name, axis_name = component_type
                if name == "noAxisPts":
                    no_axis_pts[axis_name] = self.read_record_layout_value(obj, axis_name, name)
                elif name == "noRescale":
                    no_rescale[axis_name] = self.read_record_layout_value(obj, axis_name, name)
                elif name == "axisPts":
                    axis_pts[axis_name] = component
                elif name == "axisRescale":
                    axis_rescale[axis_name] = component
            else:
                pass
        biases = {}
        for key, value in no_axis_pts.items():
            axis_pt = axis_pts.get(key)
            if axis_pt:
                max_axis_points = axis_pt["maxAxisPoints"]
                bias = value - max_axis_points
                biases[axis_pt["position"] + 1] = bias
        for key, value in no_rescale.items():
            axis_rescale = axis_rescale.get(key)
            if axis_rescale:
                max_number_of_rescale_pairs = axis_rescale["maxNumberOfRescalePairs"]
                bias = value - max_number_of_rescale_pairs
                biases[axis_rescale["position"] + 1] = bias
        total_bias = 0
        if biases:
            for pos, component in obj.record_layout_components:
                if pos in biases:
                    bias = biases.get(pos)
                    total_bias += bias
                component["offset"] += total_bias

    def read_record_layout_values(self, obj, axis_name):
        DATA_POINTS = (
            "distOp",
            "identification",
            "noAxisPts",
            "noRescale",
            "offset",
            "reserved",
            "ripAddr",
            "srcAddr",
            "shiftOp",
        )
        result = {}
        axis = obj.record_layout_components.axes(axis_name)
        for key in DATA_POINTS:
            if key in axis:
                result[key] = self.read_record_layout_value(obj, axis_name, key)
        return result

    def read_record_layout_value(self, obj, axis_name, component_name):
        """ """
        axis = obj.record_layout_components.axes(axis_name)
        component_map = axis.get(component_name)
        if component_map is None:
            return None
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        reader = get_section_reader(datatype, self.byte_order(obj))
        value = self.image.read_numeric(obj.address + offset, reader)
        return value

    def read_nd_array(self, axis_pts, axis_name, component, no_elements, shape=None, order=None):
        """ """
        axis = axis_pts.record_layout_components.axes(axis_name)
        component_map = axis[component]
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        reader = get_section_reader(datatype, self.byte_order(axis_pts))

        length = no_elements * TYPE_SIZES[datatype]
        np_arr = self.image.read_ndarray(
            addr=axis_pts.address + offset,
            length=length,
            dtype=reader,
            shape=shape,
            order=order,
            # bit_mask = characteristic.bitMask
        )
        return np_arr


class OnlineCalibration(Calibration):
    """ """

    __slots__ = "xcp_master"

    def __init__(self, xcp_master):
        self.xcp_master = xcp_master


class OfflineCalibration(Calibration):
    """ """

    __slots__ = ("hexfile_name", "hexfile_type")

    def __init__(
        self,
        a2l_db: DB,
        image,
        hexfile_name: str = None,
        hexfile_type: str = None,
        loglevel: str = "WARN",
    ):
        super().__init__(a2l_db, image, loglevel)
        self.hexfile_name = hexfile_name
        self.hexfile_type = hexfile_type


class CalibrationData(AsamBaseType):
    """Fetch calibration parameters from HEX file or XCP slave and create an in-memory representation.

    Parameters
    ----------
    project_config

    experiment_config

    Note
    ----
    This is meant as a base-class for CDF, DCM, ...
    Don't use directly.
    """

    def on_init(self, project_config, experiment_config, *args, **kws):
        # self.loadConfig(project_config, experiment_config)
        self.a2l_epk = self.epk_from_a2l()
        if self.a2l_epk is None:
            self.logger.info("A2L doesn't contains an EPK.")
        else:
            self.logger.info(f"EPK from A2L: '{self.a2l_epk[0]}'")
        self._parameters = {
            k: OrderedDict()
            for k in (
                "AXIS_PTS",
                "VALUE",
                "VAL_BLK",
                "ASCII",
                "CURVE",
                "MAP",
                "CUBOID",
                "CUBE_4",
                "CUBE_5",
            )
        }

    def load_hex(self):
        self._load_axis_pts()
        self._load_values()
        self._load_asciis()
        self._load_value_blocks()
        self._load_curves()
        self._load_maps()
        self._load_cubes()

        calibration_log = klasses.dump_characteristics(self._parameters)
        file_name = self.generate_filename(".json")
        file_name = self.sub_dir("logs") / file_name
        self.logger.info(f"Writing calibration log to {str(file_name)!r}")
        with open(file_name, "wb") as of:
            of.write(calibration_log)

    def check_epk_xcp(self, xcp_master):
        """Compare EPK (EPROM Kennung) from A2L with EPK from ECU.

        Returns
        -------
            - True:     EPKs are matching.
            - False:    EPKs are not matching.
            - None:     EPK not configured in MOD_COMMON.
        """
        if self.mod_par is None or self.a2l_epk is None:
            return None
        epk_a2l, epk_addr = self.a2l_epk
        xcp_master.setMta(epk_addr)
        epk_xcp = xcp_master.pull(len(epk_a2l))
        epk_xcp = epk_xcp[: len(epk_a2l)].decode("ascii")
        ok = epk_xcp == epk_a2l
        if not ok:
            self.logger.warn(f"EPK is invalid -- A2L: '{self.mod_par.epk}' XCP: '{epk_xcp}'.")
        else:
            self.logger.info("OK, matching EPKs.")
        return ok

    def epk_from_a2l(self):
        """Read EPK from A2L database.

        Returns
        -------
        tuple: (epk, address)
        """
        if self.mod_par is None:
            return None
        if self.mod_par.addrEpk is None:
            return None
        elif self.mod_par.epk is None:
            return None
        else:
            addr = self.mod_par.addrEpk[0]
            epk = self.mod_par.epk
            return (epk, addr)

    def save_parameters(self, xcp_master=None, hexfile: str = None, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------
        xcp_master:

        hexfile: str
            if None, `MASTER_HEXFILE` and `MASTER_HEXFILE_TYPE` from project_config is used.

        hexfile_type: "ihex" | "srec"
        """
        if xcp_master:
            self.check_epk_xcp(xcp_master)
            image = self.upload_parameters(xcp_master)
            image.file_name = None
            self.logger.info("Using image from XCP slave")
        else:
            if not hexfile:
                hexfile = self.config.general.master_hexfile
                hexfile_type = self.config.general.master_hexfile_type
            with open(f"{hexfile}", "rb") as inf:
                self.logger.info(f"Loading hex-file {hexfile!r}")
                image = load(hexfile_type, inf)
            image.file_name = hexfile
            # self.logger.info(f"Using image from HEX file '{hexfile}'")
        if not image:
            raise ValueError("Empty calibration image.")
        else:
            self._image = image
        self.load_hex()
        # self.save()

    def upload_calram(self, xcp_master, file_type: str = "ihex"):
        """Tansfer RAM segments from ECU to MCS.

        Parameters
        ----------

        Returns
        -------
        :class:`~objutils.Image` or `None`, if there are no suitable segments to read out.

        Note
        ----
        Depending on your calibration concept, CalRAM may or may not cover all of your parameters.
        s. `upload_parameters`
        """

        self.check_epk_xcp(xcp_master)
        if file_type:
            file_type = file_type.lower()
        if file_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        ram_segments = []
        mp = ModPar(self.session, None)
        for segment in mp.memorySegments:
            if segment["memoryType"] == "RAM":
                ram_segments.append(
                    (
                        segment["address"],
                        segment["size"],
                    )
                )
        if not ram_segments:
            return  # ECU program doesn't define any RAM segments.
        sections = []
        xcp_master.setCalPage(0x83, 0, 0)  # TODO: Requires paging information from IF_DATA section.
        page = 0
        for addr, size in ram_segments:
            xcp_master.setMta(addr)
            mem = xcp_master.pull(size)
            sections.append(Section(start_address=addr, data=mem))
        file_name = f'CalRAM{current_timestamp()}_P{page}.{"hex" if file_type == "ihex" else "srec"}'
        file_name = self.sub_dir("hexfiles") / file_name
        img = Image(sections=sections, join=False)
        with open(f"{file_name}", "wb") as outf:
            dump(file_type, outf, img, row_length=32)
        self.logger.info(f"CalRAM written to {file_name}")
        return img

    def download_calram(self, xcp_master, module_name: str = None, data: bytes = None):
        """Tansfer RAM segments from MCS to ECU.

        Parameters
        ----------

        Returns
        -------
        """
        if not data:
            return
        self.check_epk_xcp(xcp_master)
        # ram_segments = []
        mp = ModPar(self.session, module_name or None)
        segment = mp.memorySegments[0]
        if segment["memoryType"] == "RAM":
            xcp_master.setMta(segment["address"])
            # xcp_master.setMta(0x4000)
            xcp_master.push(data)
        # for segment in mp.memorySegments:
        #    if segment['memoryType'] == "RAM":
        #        ram_segments.append((segment['address'], segment['size'], ))
        # if not ram_segments:
        #    return None # ECU program doesn't define RAM segments.
        # sections = []
        # for addr, size in ram_segments:
        #    xcp_master.setMta(addr)
        #    mem = xcp_master.fetch(size)
        #    sections.append(Section(start_address = addr, data = mem))

    def upload_parameters(self, xcp_master, save_to_file: bool = True, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------

        xcp_master:

        save_to_file: bool

        hexfile_type: "ihex" | "srec"


        Returns
        -------
        `Image`

        """
        if hexfile_type:
            hexfile_type = hexfile_type.lower()
        if hexfile_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        result = []
        a2l_epk = self.a2l_epk
        if a2l_epk:
            epk, address = a2l_epk
            result.append(McObject("EPK", address, 0, len(epk), ""))
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(ax.name, ax.address, 0, mem_size, ""))
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))
        blocks = make_continuous_blocks(result)
        total_size = functools.reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching a total of {total_size / 1024:.2f} KBytes from XCP slave")
        sections = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address=block.address, data=mem[: block.length]))
        img = Image(sections=sections, join=True)
        if save_to_file:
            file_name = f'CalParams{current_timestamp()}.{"hex" if hexfile_type == "ihex" else "srec"}'
            file_name = self.sub_dir("hexfiles") / file_name
            with open(f"{file_name}", "wb") as outf:
                dump(hexfile_type, outf, img, row_length=32)
            self.logger.info(f"CalParams written to {file_name}")
        return img

    def _load_asciis(self) -> None:
        self.logger.info("ASCIIs")
        value: Optional[str] = None
        for characteristic in self.characteristics("ASCII"):
            self.logger.debug(f"Processing ASCII '{characteristic.name}' @0x{characteristic.address:08x}")
            if characteristic.matrixDim:
                length = characteristic.matrixDim["x"]
            else:
                length = characteristic.number
            try:
                value = self.image.read_string(characteristic.address, length=length)
            except Exception as e:
                self.logger.error(f"{characteristic.name}: {e!r}")
            self._parameters["ASCII"][characteristic.name] = klasses.Ascii(
                name=characteristic.name,
                comment=characteristic.longIdentifier,
                category="ASCII",
                value=value,
                displayIdentifier=characteristic.displayIdentifier,
                length=length,
            )

    def _load_value_blocks(self) -> None:
        self.logger.info("VAL_BLKs")
        for characteristic in self.characteristics("VAL_BLK"):
            self.logger.debug(f"Processing VAL_BLK '{characteristic.name}' @0x{characteristic.address:08x}")
            reader = get_section_reader(characteristic.fnc_asam_dtype, self.byte_order(characteristic))
            raw_values = self.image.read_ndarray(
                addr=characteristic.address,
                length=characteristic.fnc_allocated_memory,
                dtype=reader,
                shape=characteristic.fnc_np_shape,
                order=characteristic.fnc_np_order,
                bit_mask=characteristic.bitMask,
            )
            converted_values = self.int_to_physical(characteristic, raw_values)
            self._parameters["VAL_BLK"][characteristic.name] = klasses.ValueBlock(
                name=characteristic.name,
                comment=characteristic.longIdentifier,
                category="VAL_BLK",
                raw_values=raw_values,
                converted_values=converted_values,
                displayIdentifier=characteristic.displayIdentifier,
                shape=characteristic.fnc_np_shape,
                unit=characteristic.physUnit,
            )

    def _load_values(self) -> None:
        self.logger.info("VALUEs")
        for characteristic in self.characteristics("VALUE"):
            self.logger.debug(f"Processing VALUE '{characteristic.name}' @0x{characteristic.address:08x}")
            # CALIBRATION_ACCESS
            # READ_ONLY
            raw_value = 0
            fnc_asam_dtype = characteristic.fnc_asam_dtype
            reader = get_section_reader(fnc_asam_dtype, self.byte_order(characteristic))
            if characteristic.bitMask:
                raw_value = self.image.read_numeric(characteristic.address, reader, bit_mask=characteristic.bitMask)
                raw_value >>= ffs(characteristic.bitMask)  # Right-shift to get rid of trailing zeros (s. ASAM 2-MC spec).
                is_bool = True if characteristic.bitMask in SINGLE_BITS else False
            else:
                try:
                    raw_value = self.image.read_numeric(characteristic.address, reader)
                except Exception as e:
                    self.logger.error(f"{characteristic.name}: {e!r}")
                is_bool = False
            if characteristic.physUnit is None and characteristic._conversionRef != "NO_COMPU_METHOD":
                unit = characteristic.compuMethod.unit
            else:
                unit = characteristic.physUnit
            converted_value = self.int_to_physical(characteristic, raw_value)
            if isinstance(converted_value, (int, float)):
                if is_bool:
                    category = "BOOLEAN"
                    converted_value = "true" if bool(converted_value) else "false"
                else:
                    category = "VALUE"
            else:
                category = "TEXT"
            if characteristic.dependentCharacteristic:
                category = "DEPENDENT_VALUE"
            self._parameters["VALUE"][characteristic.name] = klasses.Value(
                name=characteristic.name,
                comment=characteristic.longIdentifier,
                category=category,
                raw_value=raw_value,
                converted_value=converted_value,
                displayIdentifier=characteristic.displayIdentifier,
                unit=unit,
            )

    def _load_axis_pts(self) -> None:
        self.logger.info("AXIS_PTSs")
        for item in self.axis_points():
            ap = AxisPts.get(self.session, item.name)
            self.logger.debug(f"Processing AXIS_PTS '{ap.name}' @0x{ap.address:08x}")
            rl_values = self.read_record_layout_values(ap, "x")
            self.record_layout_correct_offsets(ap)
            virtual = False
            axis = ap.record_layout_components.axes("x")
            paired = False
            if "axisRescale" in axis:
                category = "RES_AXIS"
                paired = True
                if "noRescale" in rl_values:
                    no_rescale_pairs = rl_values["noRescale"]
                else:
                    no_rescale_pairs = axis["maxNumberOfRescalePairs"]
                index_incr = axis["axisRescale"]["indexIncr"]
                count = no_rescale_pairs * 2
                attr = "axisRescale"
            elif "axisPts" in axis:
                category = "COM_AXIS"
                if "noAxisPts" in rl_values:
                    no_axis_points = rl_values["noAxisPts"]
                else:
                    no_axis_points = axis["maxAxisPoints"]
                index_incr = axis["axisPts"]["indexIncr"]
                count = no_axis_points
                attr = "axisPts"
            elif "offset" in axis:
                category = "FIX_AXIS"
                virtual = True  # Virtual / Calculated axis.
                offset = rl_values.get("offset")
                dist_op = rl_values.get("distOp")
                shift_op = rl_values.get("shiftOp")
                if "noAxisPts" in rl_values:
                    no_axis_points = rl_values["noAxisPts"]
                else:
                    no_axis_points = axis["maxAxisPoints"]
                if (dist_op or shift_op) is None:
                    raise TypeError(f"Malformed AXIS_PTS '{ap}', neither DIST_OP nor SHIFT_OP specified.")
                if dist_op is not None:
                    raw_values = fix_axis_par_dist(offset, dist_op, no_axis_points)
                else:
                    raw_values = fix_axis_par(offset, shift_op, no_axis_points)
            else:
                raise TypeError(f"Malformed AXIS_PTS '{ap}'.")
            if not virtual:
                try:
                    raw_values = self.read_nd_array(ap, "x", attr, count)
                except Exception as e:
                    self.logger.error(f"{ap.name}: {e!r}")
                if index_incr == "INDEX_DECR":
                    raw_values = raw_values[::-1]
                    reversed_storage = True
                else:
                    reversed_storage = False
            converted_values = self.int_to_physical(ap, raw_values)
            unit = ap.compuMethod.refUnit

            # pts = klasses.AxisPts()
            # print(pts)

            self._parameters["AXIS_PTS"][ap.name] = klasses.AxisPts(
                name=ap.name,
                comment=ap.longIdentifier,
                category=category,
                raw_values=raw_values,
                converted_values=converted_values,
                displayIdentifier=ap.displayIdentifier,
                paired=paired,
                unit=unit,
                reversed_storage=reversed_storage,
            )

    def _load_curves(self) -> None:
        self.logger.info("CURVEs")
        self._load_curves_and_maps("CURVE", 1)

    def _load_maps(self) -> None:
        self.logger.info("MAPs")
        self._load_curves_and_maps("MAP", 2)

    def _load_cubes(self):
        self.logger.info("CUBOIDs")
        self._load_curves_and_maps("CUBOID", 3)
        self.logger.info("CUBE_4s")
        self._load_curves_and_maps("CUBE_4", 4)
        self.logger.info("CUBE_5s")
        self._load_curves_and_maps("CUBE_5", 5)

    def _order_curves(self, curves):
        """Remove forward references from CURVE list."""
        curves = list(curves)[::1]  # Don't destroy the generator, make a copy.
        curves_by_name = {c.name: (pos, c) for pos, c in enumerate(curves)}
        while True:
            ins_pos = 0
            for curr_pos in range(len(curves)):
                curve = curves[curr_pos]
                axis_descr = curve.axisDescriptions[0]
                if axis_descr.attribute == "CURVE_AXIS":
                    if axis_descr.curveAxisRef.name in curves_by_name:
                        ref_pos, ref_curve = curves_by_name.get(axis_descr.curveAxisRef.name)
                        if ref_pos > curr_pos:
                            # Swap
                            t_curve = curves[ins_pos]
                            curves[ins_pos] = curves[ref_pos]
                            curves[ref_pos] = t_curve
                            curves_by_name[curves[ins_pos].name] = (
                                ins_pos,
                                curves[ins_pos],
                            )
                            curves_by_name[curves[ref_pos].name] = (
                                ref_pos,
                                curves[ref_pos],
                            )
                            ins_pos += 1
            if ins_pos == 0:
                break  # No more swaps, we're done.
        return curves

    def _load_curves_and_maps(self, category: str, num_axes: int):
        characteristics = self.characteristics(category)
        if num_axes == 1:
            # CURVEs may reference other CURVEs, so some ordering is required.
            characteristics = self._order_curves(characteristics)
        for characteristic in characteristics:
            self.logger.debug(f"Processing {category} '{characteristic.name}' @0x{characteristic.address:08x}")

            if characteristic.compuMethod != "NO_COMPU_METHOD":
                characteristic_cm = characteristic.compuMethod.name
            else:
                characteristic_cm = "NO_COMPU_METHOD"
            chr_cm = CompuMethod.get(self.session, characteristic_cm)
            fnc_unit = chr_cm.unit
            fnc_datatype = characteristic.record_layout_components.fncValues["datatype"]
            self.record_layout_correct_offsets(characteristic)
            num_func_values = 1
            shape = []
            axes = []
            for axis_idx in range(num_axes):
                axis_descr = characteristic.axisDescriptions[axis_idx]
                axis_name = AXES[axis_idx]
                maxAxisPoints = axis_descr.maxAxisPoints
                axis_cm_name = "NO_COMPU_METHOD" if axis_descr.compuMethod == "NO_COMPU_METHOD" else axis_descr.compuMethod.name
                axis_cm = CompuMethod.get(self.session, axis_cm_name)
                axis_unit = axis_cm.unit
                axis_attribute = axis_descr.attribute
                axis = characteristic.record_layout_components.axes(axis_name)
                fix_no_axis_pts = characteristic.deposit.fixNoAxisPts.get(axis_name)
                rl_values = self.read_record_layout_values(characteristic, axis_name)
                curve_axis_ref = None
                axis_pts_ref = None
                reversed_storage = False
                flipper = []
                if fix_no_axis_pts:
                    no_axis_points = fix_no_axis_pts
                else:
                    if "noAxisPts" in rl_values:
                        no_axis_points = rl_values["noAxisPts"]
                    elif "noRescale" in rl_values:
                        no_axis_points = rl_values["noRescale"]
                    else:
                        no_axis_points = maxAxisPoints
                if axis_attribute == "FIX_AXIS":
                    if axis_descr.fixAxisParDist:
                        par_dist = axis_descr.fixAxisParDist
                        raw_axis_values = fix_axis_par_dist(
                            par_dist["offset"],
                            par_dist["distance"],
                            par_dist["numberapo"],
                        )
                    elif axis_descr.fixAxisParList:
                        raw_axis_values = axis_descr.fixAxisParList
                    elif axis_descr.fixAxisPar:
                        par = axis_descr.fixAxisPar
                        raw_axis_values = fix_axis_par(par["offset"], par["shift"], par["numberapo"])
                    no_axis_points = len(raw_axis_values)
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                elif axis_attribute == "STD_AXIS":
                    raw_axis_values = self.read_nd_array(characteristic, axis_name, "axisPts", no_axis_points)
                    index_incr = axis["axisPts"]["indexIncr"]
                    if index_incr == "INDEX_DECR":
                        raw_axis_values = raw_axis_values[::-1]
                        reversed_storage = True
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                elif axis_attribute == "RES_AXIS":
                    ref_obj = self._parameters["AXIS_PTS"][axis_descr.axisPtsRef.name]
                    # no_axis_points = min(no_axis_points, len(ref_obj.raw_values) // 2)
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw_values)
                    reversed_storage = ref_obj.reversed_storage
                elif axis_attribute == "CURVE_AXIS":
                    ref_obj = self._parameters["CURVE"][axis_descr.curveAxisRef.name]
                    curve_axis_ref = axis_descr.curveAxisRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw_values)
                    reversed_storage = ref_obj.axes[0].reversed_storage
                elif axis_attribute == "COM_AXIS":
                    ref_obj = self._parameters["AXIS_PTS"][axis_descr.axisPtsRef.name]
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw_values)
                    reversed_storage = ref_obj.reversed_storage
                num_func_values *= no_axis_points
                shape.append(no_axis_points)
                if reversed_storage:
                    flipper.append(axis_idx)
                axes.append(
                    klasses.AxisContainer(
                        category=axis_attribute,
                        unit=axis_unit,
                        reversed_storage=reversed_storage,
                        raw_values=raw_axis_values,
                        converted_values=converted_axis_values,
                        axis_pts_ref=axis_pts_ref,
                        curve_axis_ref=curve_axis_ref,
                    )
                )
            length = num_func_values * TYPE_SIZES[fnc_datatype]
            try:
                raw_values = self.image.read_ndarray(
                    addr=characteristic.address + characteristic.record_layout_components.fncValues["offset"],
                    length=length,
                    dtype=get_section_reader(
                        characteristic.record_layout_components.fncValues["datatype"],
                        self.byte_order(characteristic),
                    ),
                    shape=shape,
                    # order = order,
                    # bit_mask = characteristic.bitMask
                )
            except Exception as e:
                self.logger.error(f"{axis_name}: {e!r}")
            if flipper:
                raw_values = np.flip(raw_values, axis=flipper)
            try:
                converted_values = chr_cm.int_to_physical(raw_values)
            except Exception as e:
                self.logger.error(f"Exception in _load_curves_and_maps(): {e!r}")
                self.logger.error(f"CHARACTERISTIC: {characteristic.name!r}")
                self.logger.error(f"COMPU_METHOD: {chr_cm.name!r} ==> {chr_cm.evaluator!r}")
                self.logger.error(f"RAW_VALUES: {raw_values!r}")

                converted_values = [0.0] * len(raw_values)

            klass = klasses.get_calibration_class(category)
            if klass:
                self._parameters[f"{category}"][characteristic.name] = klass(
                    name=characteristic.name,
                    comment=characteristic.longIdentifier,
                    category=category,
                    displayIdentifier=characteristic.displayIdentifier,
                    raw_values=raw_values,
                    converted_values=converted_values,
                    fnc_unit=fnc_unit,
                    axes=axes,
                )

    def record_layout_correct_offsets(self, obj):
        """ """
        no_axis_pts = {}
        no_rescale = {}
        axis_pts = {}
        axis_rescale = {}
        # fnc_values = None
        for _, component in obj.record_layout_components:
            component_type = component["type"]
            if component_type == "fncValues":
                # fnc_values = component
                pass
            elif len(component_type) == 2:
                name, axis_name = component_type
                if name == "noAxisPts":
                    no_axis_pts[axis_name] = self.read_record_layout_value(obj, axis_name, name)
                elif name == "noRescale":
                    no_rescale[axis_name] = self.read_record_layout_value(obj, axis_name, name)
                elif name == "axisPts":
                    axis_pts[axis_name] = component
                elif name == "axisRescale":
                    axis_rescale[axis_name] = component
            else:
                pass
        biases = {}
        for key, value in no_axis_pts.items():
            axis_pt = axis_pts.get(key)
            if axis_pt:
                max_axis_points = axis_pt["maxAxisPoints"]
                bias = value - max_axis_points
                biases[axis_pt["position"] + 1] = bias
        for key, value in no_rescale.items():
            axis_rescale = axis_rescale.get(key)
            if axis_rescale:
                max_number_of_rescale_pairs = axis_rescale["maxNumberOfRescalePairs"]
                bias = value - max_number_of_rescale_pairs
                biases[axis_rescale["position"] + 1] = bias
        total_bias = 0
        if biases:
            for pos, component in obj.record_layout_components:
                if pos in biases:
                    bias = biases.get(pos)
                    total_bias += bias
                component["offset"] += total_bias

    def read_record_layout_values(self, obj, axis_name):
        DATA_POINTS = (
            "distOp",
            "identification",
            "noAxisPts",
            "noRescale",
            "offset",
            "reserved",
            "ripAddr",
            "srcAddr",
            "shiftOp",
        )
        result = {}
        axis = obj.record_layout_components.axes(axis_name)
        for key in DATA_POINTS:
            if key in axis:
                result[key] = self.read_record_layout_value(obj, axis_name, key)
        return result

    def read_record_layout_value(self, obj, axis_name, component_name):
        """ """
        axis = obj.record_layout_components.axes(axis_name)
        component_map = axis.get(component_name)
        if component_map is None:
            return None
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        reader = get_section_reader(datatype, self.byte_order(obj))
        value = self.image.read_numeric(obj.address + offset, reader)
        return value

    def read_nd_array(self, axis_pts, axis_name, component, no_elements, shape=None, order=None):
        """ """
        axis = axis_pts.record_layout_components.axes(axis_name)
        component_map = axis[component]
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        reader = get_section_reader(datatype, self.byte_order(axis_pts))

        length = no_elements * TYPE_SIZES[datatype]
        np_arr = self.image.read_ndarray(
            addr=axis_pts.address + offset,
            length=length,
            dtype=reader,
            shape=shape,
            order=order,
            # bit_mask = characteristic.bitMask
        )
        return np_arr

    def int_to_physical(self, characteristic, int_values):
        """ """
        if isinstance(characteristic.compuMethod, str) and characteristic.compuMethod == "NO_COMPU_METHOD":
            cm_name = "NO_COMPU_METHOD"
        else:
            cm_name = (
                "NO_COMPU_METHOD"
                if characteristic.compuMethod.conversionType == "NO_COMPU_METHOD"
                else characteristic.compuMethod.name
            )
        cm = CompuMethod.get(self.session, cm_name)
        return cm.int_to_physical(int_values)

    @property
    def image(self):
        return self._image

    @property
    def parameters(self):
        return self._parameters

    def axis_points(self):
        """ """
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            yield AxisPts.get(self.session, a.name)

    def characteristics(self, category):
        """ """
        query = self.query(model.Characteristic.name).filter(model.Characteristic.type == category)
        for characteristic in query.all():
            yield Characteristic.get(self.session, characteristic.name)
