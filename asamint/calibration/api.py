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
from functools import partialmethod
from typing import Optional, Union

import numpy as np
from objutils import Image
from pya2l import DB, model
from pya2l.api.inspect import AxisPts, Characteristic, CompuMethod, asam_type_size
from pya2l.functions import fix_axis_par, fix_axis_par_dist

from asamint.asam import AsamMC, ByteOrder, get_data_type
from asamint.model.calibration import klasses
from asamint.utils import SINGLE_BITS, ffs


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


class DictLike:

    def __init__(self, getter_method) -> None:
        self.getter_method = getter_method
        self.cache = {}

    def __getitem__(self, item: int):
        if item in self.cache:
            return self.cache[item]
        else:
            value = self.getter_method(item)
            self.cache[item] = value
        return value


class ParameterCache:

    # def __init__(self, asam_mc) -> None:
    #    self.asam_mc = asam_mc

    def set_parent(self, parent):
        self.parent = parent
        self.curves = DictLike(partialmethod(parent.load_curve_or_map, category="CURVE", num_axes=1))
        self.axis_pts = DictLike(parent.load_axis_pts)
        self.dicts = {
            "CURVE": self.curves,
            "AXIS_PTS": self.axis_pts,
        }

    def __getitem__(self, item: str) -> DictLike:
        return self.dicts.get(item)


class Calibration:
    """ """

    def __init__(self, asam_mc: AsamMC, image: Image, parameter_cache: Union[dict, ParameterCache], logger) -> None:
        self.image = image
        self.asam_mc = asam_mc
        self.session = asam_mc.session
        self.parameter_cache = parameter_cache
        if isinstance(parameter_cache, ParameterCache):
            self.parameter_cache.set_parent(self)
        self.logger = logger
        self.mod_common = asam_mc.mod_common
        self.mod_par = asam_mc.mod_par

    def update(self):
        """To the actual update of parameters (write to HEX file / XCP)."""
        pass

    def load(self, name: str):
        chr = self.session.query(model.Characteristic).filter(model.Characteristic.name == name).first()
        if chr is None:
            axis_pts = self.session.query(model.AxisPts).filter(model.AxisPts.name == name).first()
            return self.load_axis_pts(name).converted_values
        else:
            match chr.type:
                case "ASCII":
                    return self.load_ascii(name).value
                case "CUBOID":
                    return self.load_curve_or_map(name, "CUBOID", 3).converted_values
                case "CUBE_4":
                    return self.load_curve_or_map(name, "CUBE_4", 4).converted_values
                case "CUBE_5":
                    return self.load_curve_or_map(name, "CUBE_5", 5).converted_values
                case "CURVE":
                    return self.load_curve_or_map(name, "CURVE", 1).converted_values
                case "MAP":
                    return self.load_curve_or_map(name, "MAP", 2).converted_values
                case "VAL_BLK":
                    return self.load_value_block(name).converted_values
                case "VALUE":
                    return self.load_value(name).converted_value

    # load_with_metadata

    def load_ascii(self, characteristic_name: str) -> klasses.Ascii:
        characteristic = self.get_characteristic(characteristic_name, "ASCII", False)
        value: Optional[str] = None
        if characteristic.matrixDim:
            length = characteristic.matrixDim["x"]
        else:
            length = characteristic.number
        try:
            value = self.image.read_string(characteristic.address, length=length)
        except Exception as e:
            self.logger.error(f"{characteristic.name}: {e!r}")
            # self.log_memory_errors(e, MemoryType.ASCII, characteristic.name, characteristic.address, length)
            value = None
        else:
            pass
            # self.memory_map[characteristic.address].append(
            #    MemoryObject(
            #        memory_type=MemoryType.ASCII, name=characteristic.name, address=characteristic.address,
            #        length=length
            #    )
            # )
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
        raw_values: np.array = np.array([])
        converted_values: np.array = np.array([])
        try:
            raw_values = self.image.read_ndarray(
                addr=characteristic.address,
                length=characteristic.fnc_allocated_memory,
                dtype=get_data_type(characteristic.fnc_asam_dtype, self.asam_mc.byte_order(characteristic)),
                shape=characteristic.fnc_np_shape,
                order=characteristic.fnc_np_order,
                bit_mask=characteristic.bitMask,
            )
        except Exception as e:
            self.logger.error(f"{characteristic.name}: {e!r}")
            # self.log_memory_errors(
            #    e, MemoryType.VAL_BLK, characteristic.name, characteristic.address, characteristic.fnc_allocated_memory
            # )
        else:
            converted_values = self.int_to_physical(characteristic, raw_values)
            # self.memory_map[characteristic.address].append(
            #    MemoryObject(
            #        memory_type=MemoryType.VAL_BLK,
            #        name=characteristic.name,
            #        address=characteristic.address,
            #        length=characteristic.fnc_allocated_memory,
            #    )
            # )
        return klasses.ValueBlock(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category="VAL_BLK",
            raw_values=raw_values,
            converted_values=converted_values,
            displayIdentifier=characteristic.displayIdentifier,
            shape=characteristic.fnc_np_shape,
            unit=characteristic.physUnit,
            is_numeric=self.is_numeric(characteristic.compuMethod),
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
        # READ_ONLY
        raw_value = 0
        fnc_asam_dtype = characteristic.fnc_asam_dtype
        allocated_memory = asam_type_size(fnc_asam_dtype)
        reader = get_data_type(fnc_asam_dtype, self.asam_mc.byte_order(characteristic))
        if characteristic.bitMask:
            raw_value = self.image.read_numeric(characteristic.address, reader, bit_mask=characteristic.bitMask)
            raw_value >>= ffs(characteristic.bitMask)  # Right-shift to get rid of trailing zeros (s. ASAM 2-MC spec).
            is_bool = True if characteristic.bitMask in SINGLE_BITS else False
        else:
            try:
                raw_value = self.image.read_numeric(characteristic.address, reader)
            except Exception as e:
                self.logger.error(f"{characteristic.name}: {e!r}")
                # self.log_memory_errors(e, MemoryType.VALUE, characteristic.name, characteristic.address,
                #                       allocated_memory)
                raw_value = 0
            is_bool = False
        if characteristic.physUnit is None and characteristic._conversionRef != "NO_COMPU_METHOD":
            unit = characteristic.compuMethod.unit
        else:
            unit = characteristic.physUnit
        converted_value = self.int_to_physical(characteristic, raw_value)
        is_numeric = self.is_numeric(characteristic.compuMethod)
        if is_numeric:
            if is_bool:
                category = "BOOLEAN"
                # converted_value = "true" if bool(converted_value) else "false"
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
            is_numeric=is_numeric,
        )
        # self.memory_map[characteristic.address].append(
        #    MemoryObject(
        #        memory_type=MemoryType.VALUE, name=characteristic.name, address=characteristic.address,
        #        length=allocated_memory
        #    )
        # )

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
        elif isinstance(value, bool):
            value = int(value)
        elif isinstance(value, str):
            pass
            if value in ("true", "false"):
                value = BOOLEAN_MAP[value]
            else:
                raise ValueError("value of type str must be 'true' or 'false'")
        dtype = get_data_type(characteristic.fnc_asam_dtype, self.byte_order(characteristic))

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
        ap = self.get_axis_pts(axis_pts_name)
        rl_values = self.read_record_layout_values(ap, "x")
        self.record_layout_correct_offsets(ap)
        raw_values = np.array([])
        axis = ap.record_layout_components.axes("x")
        virtual = False
        paired = False
        if "axisRescale" in axis:
            category = "RES_AXIS"
            paired = True
            if "noRescale" in rl_values:
                no_rescale_pairs = rl_values["noRescale"]
            else:
                no_rescale_pairs = axis["maxNumberOfRescalePairs"]
            index_incr = axis["axisRescale"]["indexIncr"]
            count = int(no_rescale_pairs * 2)
            attr = "axisRescale"
        elif "axisPts" in axis:
            category = "COM_AXIS"
            if "noAxisPts" in rl_values:
                no_axis_points = rl_values["noAxisPts"]
            else:
                no_axis_points = axis["maxAxisPoints"]
            index_incr = axis["axisPts"]["indexIncr"]
            count = int(no_axis_points)
            attr = "axisPts"
        elif "offset" in axis:
            category = "FIX_AXIS"
            virtual = True  # Virtual / Calculated axis.
            offset = int(rl_values.get("offset"))
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
                # self.log_memory_errors(e, MemoryType.AXIS_PTS, ap.name, ap.address, ap.axis_allocated_memory)
            if index_incr == "INDEX_DECR":
                raw_values = raw_values[::-1]
                reversed_storage = True
            else:
                reversed_storage = False
        converted_values = self.int_to_physical(ap, raw_values)
        unit = ap.compuMethod.refUnit
        return klasses.AxisPts(
            name=ap.name,
            comment=ap.longIdentifier,
            category=category,
            raw_values=raw_values,
            converted_values=converted_values,
            displayIdentifier=ap.displayIdentifier,
            paired=paired,
            unit=unit,
            reversed_storage=reversed_storage,
            is_numeric=self.is_numeric(ap.compuMethod),
        )
        # self.memory_map[ap.address].append(
        #    MemoryObject(memory_type=MemoryType.AXIS_PTS, name=ap.name, address=ap.address,
        #                 length=ap.axis_allocated_memory)
        # )

    def load_curve_or_map(
        self, characteristic_name: str, category: str, num_axes: int
    ) -> Union[klasses.Cube4, klasses.Cube5, klasses.Cuboid, klasses.Curve, klasses.Map]:
        klass = klasses.get_calibration_class(category)
        characteristic = self.get_characteristic(characteristic_name, category, True)
        raw_values = np.array([])
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
            axis_pts_ref = None
            reversed_storage = False
            flipper = []
            raw_axis_values = []
            if fix_no_axis_pts:
                no_axis_points = fix_no_axis_pts
            elif "noAxisPts" in rl_values:
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
                ref_obj = self.parameter_cache["AXIS_PTS"][axis_descr.axisPtsRef.name]
                # no_axis_points = min(no_axis_points, len(ref_obj.raw_values) // 2)
                axis_pts_ref = axis_descr.axisPtsRef.name
                raw_axis_values = None
                converted_axis_values = None
                axis_unit = None
                no_axis_points = len(ref_obj.raw_values)
                reversed_storage = ref_obj.reversed_storage
            elif axis_attribute == "CURVE_AXIS":
                ref_obj = self.parameter_cache["CURVE"][axis_descr.curveAxisRef.name]
                axis_pts_ref = axis_descr.curveAxisRef.name
                raw_axis_values = None
                converted_axis_values = None
                axis_unit = None
                no_axis_points = len(ref_obj.raw_values)
                reversed_storage = ref_obj.axes[0].reversed_storage
            elif axis_attribute == "COM_AXIS":
                ref_obj = self.parameter_cache["AXIS_PTS"][axis_descr.axisPtsRef.name]
                axis_pts_ref = axis_descr.axisPtsRef.name
                raw_axis_values = []
                converted_axis_values = []
                axis_unit = None
                no_axis_points = len(ref_obj.raw_values)
                reversed_storage = ref_obj.reversed_storage
            num_func_values *= no_axis_points
            shape.append(no_axis_points)
            if reversed_storage:
                flipper.append(axis_idx)
            axes.append(
                klasses.AxisContainer(
                    name=axis_name,
                    input_quantity=axis_descr.inputQuantity,
                    category=axis_attribute,
                    unit=axis_unit,
                    reversed_storage=reversed_storage,
                    raw_values=raw_axis_values,
                    converted_values=converted_axis_values,
                    axis_pts_ref=axis_pts_ref,
                    is_numeric=self.is_numeric(axis_cm),
                )
            )
        # if category == "CURVE":
        #    memory_type = MemoryType.CURVE
        # elif category == "MAP":
        #    memory_type = MemoryType.MAP
        # else:
        #    memory_type = MemoryType.CUBOID
        length = num_func_values * asam_type_size(fnc_datatype)
        try:
            raw_values = self.image.read_ndarray(
                addr=characteristic.address + characteristic.record_layout_components.fncValues["offset"],
                length=length,
                dtype=get_data_type(
                    characteristic.record_layout_components.fncValues["datatype"],
                    self.asam_mc.byte_order(characteristic),
                ),
                shape=shape,
                # order = order,
                # bit_mask = characteristic.bitMask
            )
        except Exception as e:
            self.logger.error(f"{characteristic.name}:  {axis_name}-axis: {e!r}")
            raw_values = np.array([])
            # self.log_memory_errors(
            #    e, memory_type, characteristic.name, characteristic.address, characteristic.total_allocated_memory
            # )
        if flipper:
            raw_values = np.flip(raw_values, axis=flipper)
        try:
            converted_values = chr_cm.int_to_physical(raw_values)
        except Exception as e:
            self.logger.error(f"Exception in _load_curves_and_maps(): {e!r}")
            self.logger.error(f"CHARACTERISTIC: {characteristic.name!r}")
            self.logger.error(f"COMPU_METHOD: {chr_cm.name!r} ==> {chr_cm.evaluator!r}")
            self.logger.error(f"RAW_VALUES: {raw_values!r}")

            converted_values = np.array([0.0] * len(raw_values))
        return klass(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category=category,
            displayIdentifier=characteristic.displayIdentifier,
            raw_values=raw_values,
            converted_values=converted_values,
            fnc_unit=fnc_unit,
            axes=axes,
            is_numeric=self.is_numeric(characteristic.compuMethod),
        )
        ###
        ###
        # self.memory_map[characteristic.address].append(
        #    MemoryObject(
        #        memory_type=memory_type,
        #        name=characteristic.name,
        #        address=characteristic.address,
        #        length=characteristic.total_allocated_memory,
        #    )
        # )

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
        return CompuMethod.get(self.session, cm_name)

    def get_characteristic(self, characteristic_name, type_name: str, save: bool = False):
        characteristic = self._load_characteristic(characteristic_name, type_name)
        direction = "Saving" if save else "Loading"
        self.logger.debug(f"{direction} {type_name} '{characteristic.name}' @0x{characteristic.address:08x}")
        return characteristic

    def _load_characteristic(self, characteristic_name, category):
        try:
            characteristic = Characteristic.get(self.session, characteristic_name)
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
            axis_pts = AxisPts.get(self.session, axis_pts_name)
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
        value = self.image.read_numeric(obj.address + offset, get_data_type(datatype, self.byte_order(obj)))
        return value

    def read_nd_array(
        self, axis_pts: AxisPts, axis_name: str, component: str, no_elements: int, shape=None, order=None
    ) -> np.ndarray:
        """ """
        axis = axis_pts.record_layout_components.axes(axis_name)
        component_map = axis[component]
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        length = no_elements * asam_type_size(datatype)
        np_arr = self.image.read_ndarray(
            addr=axis_pts.address + offset,
            length=length,
            dtype=get_data_type(datatype, self.byte_order(axis_pts)),
            shape=shape,
            order=order,
            # bit_mask = characteristic.bitMask
        )
        return np_arr

    def write_nd_array(self, axis_pts: AxisPts, axis_name: str, component: str, np_arr: np.ndarray, order=None) -> None:
        axis = axis_pts.record_layout_components.axes(axis_name)
        component_map = axis[component]
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        self.image.write_ndarray(addr=axis_pts.address + offset, array=np_arr, order=order)

    def is_numeric(self, compu_method):
        return compu_method == "NO_COMPU_METHOD" or compu_method.conversionType != "TAB_VERB"


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
