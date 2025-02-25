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

import sys
from enum import IntEnum
from typing import Union

import numpy as np
from pya2l import DB
from pya2l.api.inspect import AxisPts, Characteristic, CompuMethod, ModCommon, ModPar
from pya2l.functions import fix_axis_par, fix_axis_par_dist

from asamint.asam import ByteOrder, asam_type_size, get_section_reader
from asamint.logger import Logger
from asamint.model.calibration import klasses
from asamint.utils import SINGLE_BITS, ffs


ver_info = sys.version_info

if ver_info.major == 3 and ver_info.minor < 10:
    ValueType = (float, int, bool, str)
else:
    ValueType = Union[float, int, bool, str]

BOOLEAN_MAP = {"true": 1, "false": 0}

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

        length = no_elements * asam_type_size(datatype)
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
