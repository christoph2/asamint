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

import operator
import sys
from dataclasses import dataclass
from enum import IntEnum
from functools import partialmethod, reduce
from typing import Any, Optional, Union

import numpy as np
from black.trans import defaultdict
from objutils import Image
from objutils.exceptions import InvalidAddressError
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


@dataclass
class AxesContainer:
    axes: list[klasses.AxisContainer]
    shape: tuple[int]
    flip_axes: list[int]
    # num_func_values: int


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
    if extended_limits and characteristic.extendedLimits.valid():
        limits = characteristic.extendedLimits
        if value < limits.lowerLimit or value > limits.upperLimit:
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
        result = None
        if chr is None:
            axis_pts = self.session.query(model.AxisPts).filter(model.AxisPts.name == name).first()
            return self.load_axis_pts(name).phys
        else:
            match chr.type:
                case "ASCII":
                    result = self.load_ascii(name)
                case "CUBOID":
                    result = self.load_curve_or_map(name, "CUBOID", 3)
                case "CUBE_4":
                    result = self.load_curve_or_map(name, "CUBE_4", 4)
                case "CUBE_5":
                    result = self.load_curve_or_map(name, "CUBE_5", 5)
                case "CURVE":
                    result = self.load_curve_or_map(name, "CURVE", 1)
                case "MAP":
                    result = self.load_curve_or_map(name, "MAP", 2)
                case "VAL_BLK":
                    result = self.load_value_block(name)
                case "VALUE":
                    result = self.load_value(name)
        return result

    def save(self, name: str, value: Any) -> None:
        chr = self.session.query(model.Characteristic).filter(model.Characteristic.name == name).first()
        if chr is None:
            axis_pts = self.session.query(model.AxisPts).filter(model.AxisPts.name == name).first()
            self.save_axis_pts(name, value)
        else:
            match chr.type:
                case "ASCII":
                    self.save_ascii(name, value)
                case "CUBOID":
                    self.save_curve_or_map(name, "CUBOID", 3, value)
                case "CUBE_4":
                    self.save_curve_or_map(name, "CUBE_4", 4, value)
                case "CUBE_5":
                    self.save_curve_or_map(name, "CUBE_5", 5, value)
                case "CURVE":
                    self.save_curve_or_map(name, "CURVE", 1, value)
                case "MAP":
                    self.save_curve_or_map(name, "MAP", 2, value)
                case "VAL_BLK":
                    self.save_value_block(name, value)
                case "VALUE":
                    self.save_value(name, value)

    # load_with_metadata

    def load_ascii(self, characteristic_name: str) -> klasses.Ascii:
        characteristic = self.get_characteristic(characteristic_name, "ASCII", False)
        value: Optional[str] = None
        if characteristic.matrixDim.valid():
            length = characteristic.matrixDim.x
        else:
            length = characteristic.number
        try:
            value = self.image.read_string(characteristic.address, length=length)
        except Exception as e:
            self.logger.error(f"{characteristic.name!r}: {e}")
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
            phys=value,
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
            length = characteristic.matrixDim.x
        else:
            length = characteristic.number
        # exact string length matters,
        # either cut...
        value = value[:length]
        # or fill.
        value = value.ljust(20, "\x00")
        self.image.write_string(characteristic.address, length=length, value=value)
        return Status.OK

    def load_value_block(self, characteristic_name: str) -> klasses.ValueBlock:
        characteristic = self.get_characteristic(characteristic_name, "VAL_BLK", False)
        raw: np.array = np.array([])
        phys: np.array = np.array([])

        num_func_values = reduce(operator.mul, characteristic.fnc_np_shape, 1)
        length = num_func_values * asam_type_size(characteristic.fnc_asam_dtype)
        try:
            raw = self.image.read_ndarray(
                addr=characteristic.address,
                length=length,
                dtype=get_data_type(characteristic.fnc_asam_dtype, self.asam_mc.byte_order(characteristic)),
                shape=characteristic.fnc_np_shape,
                order=characteristic.fnc_np_order,
                bit_mask=characteristic.bitMask,
            )
        except Exception as e:
            self.logger.error(f"{characteristic.name!r}: {e}")
            # self.log_memory_errors(
            #    e, MemoryType.VAL_BLK, characteristic.name, characteristic.address, characteristic.fnc_allocated_memory
            # )
        else:
            phys = self.int_to_physical(characteristic, raw)
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
            raw=raw,
            phys=phys,
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
        if characteristic.fnc_np_shape != values.shape:
            raise ValueError(
                f"Shape mismatch: characteristic '{characteristic_name}' expects {characteristic.fnc_np_shape}, got {values.shape}"
            )
        phys = self.physical_to_int(characteristic, values)
        self.image.write_ndarray(addr=characteristic.address, array=phys, order=characteristic.fnc_np_order)
        return Status.OK

    def load_value(self, characteristic_name: str) -> klasses.Value:
        characteristic = self.get_characteristic(characteristic_name, "VALUE", False)
        # CALIBRATION_ACCESS
        # READ_ONLY
        raw = 0
        fnc_asam_dtype = characteristic.fnc_asam_dtype
        reader = get_data_type(fnc_asam_dtype, self.asam_mc.byte_order(characteristic))
        if characteristic.bitMask:
            raw = self.image.read_numeric(characteristic.address, reader, bit_mask=characteristic.bitMask)
            raw >>= ffs(characteristic.bitMask)  # Right-shift to get rid of trailing zeros (s. ASAM 2-MC spec).
            is_bool = True if characteristic.bitMask in SINGLE_BITS else False
        else:
            try:
                raw = self.image.read_numeric(characteristic.address, reader)
            except Exception as e:
                self.logger.error(f"{characteristic.name!r}: {e}")
                # self.log_memory_errors(e, MemoryType.VALUE, characteristic.name, characteristic.address,
                #                       allocated_memory)
            is_bool = False
        if characteristic.physUnit is None and characteristic._conversionRef != "NO_COMPU_METHOD":
            unit = characteristic.compuMethod.unit
        else:
            unit = characteristic.physUnit
        phys = self.int_to_physical(characteristic, raw)
        is_numeric = self.is_numeric(characteristic.compuMethod)
        if is_numeric:
            if is_bool:
                category = "BOOLEAN"
                # phys = "true" if bool(phys) else "false"
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
            raw=raw,
            phys=phys,
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

        phys = self.physical_to_int(characteristic, value)
        if characteristic.bitMask:
            phys = int(phys)
            phys <<= ffs(characteristic.bitMask)
        self.image.write_numeric(characteristic.address, phys, dtype)
        return Status.OK

    def load_axis_pts(self, axis_pts_name: str) -> AxisPts:
        ap = self.get_axis_pts(axis_pts_name)
        axis_values = self.read_axes_values(ap, "x")
        axis_arrays = self.read_axes_arrays(ap, "x")
        axes = ap.record_layout_components.get("axes")
        axis_info = axes.get("x")

        if axis_info.category == "COM_AXIS":
            raw = axis_arrays.get("axis_pts")
            # no_axis_pts = axis_values.get("no_axis_pts")
        elif axis_info.category == "FIX_AXIS":
            pass
        elif axis_info.category == "RES_AXIS":
            raw = axis_arrays.get("axis_rescale")
            # no_axis_pts = axis_values.get("no_rescale")
        if axis_info.reversed_storage:
            raw = raw[::-1]
        # raw = axes_values
        phys = self.int_to_physical(ap, raw)
        unit = ap.compuMethod.refUnit
        return klasses.AxisPts(
            name=ap.name,
            comment=ap.longIdentifier,
            category=axis_info.category,
            raw=raw,
            phys=phys,
            displayIdentifier=ap.displayIdentifier,
            paired=False,  # TODO: weg!!!
            unit=unit,
            reversed_storage=False,  # TODO: weg!!!
            is_numeric=self.is_numeric(ap.compuMethod),
        )
        # self.memory_map[ap.address].append(
        #    MemoryObject(memory_type=MemoryType.AXIS_PTS, name=ap.name, address=ap.address,
        #                 length=ap.axis_allocated_memory)
        # )

    def save_axis_pts(self, axis_pts_name: str, values: np.ndarray) -> None:
        ap = self.get_axis_pts(axis_pts_name)

        axis_values = self.read_axes_values(ap, "x")
        axes = ap.record_layout_components.get("axes")
        axis_info = axes.get("x")

        # components = ap.record_layout_components
        if axis_info.category == "FIX_AXIS":
            raise TypeError(f" AXIS_PTS {axis_pts_name!r} is not physically allocated, use A2L to change.")

        ####
        # static_values = components.axes.get("x")
        # dynamic_values = self.read_rl_values(ap, include_arrays=False)
        # if not "axisPts" in axis:
        #    raise TypeError(f" AXIS_PTS {axis_pts_name!r} is not physically allocated, use A2L to change.")
        if values.ndim != 1:
            raise ValueError("`values` must be 1D array")
        if "no_axis_pts" not in axis_info.elements:
            if values.size != ap.maxAxisPoints:
                raise ValueError(f"`values`: expected an array with {ap.maxAxisPoints} elemets.")
        elif values.size > ap.maxAxisPoints:
            raise ValueError("`values` size exceeds maxAxisPoints")
        else:
            no_axis_pts = axis_info.elements.get("no_axis_pts")
            data_type = get_data_type(no_axis_pts.data_type, self.byte_order(ap))
            self.image.write_numeric(addr=no_axis_pts.address, value=values.size, dtype=data_type)
        values = self.physical_to_int(ap, values)
        # axis_pts = static_values.get("axis_pts")
        self.write_nd_array(ap, "x", "axis_pts", values)

    def load_curve_or_map(
        self, characteristic_name: str, category: str, num_axes: int
    ) -> Union[klasses.Cube4, klasses.Cube5, klasses.Cuboid, klasses.Curve, klasses.Map]:
        klass = klasses.get_calibration_class(category)
        characteristic = self.get_characteristic(characteristic_name, category, True)
        raw = np.array([])
        if characteristic.compuMethod != "NO_COMPU_METHOD":
            characteristic_cm = characteristic.compuMethod.name
        else:
            characteristic_cm = "NO_COMPU_METHOD"
        chr_cm = CompuMethod.get(self.session, characteristic_cm)
        fnc_unit = chr_cm.unit
        fnc_datatype = characteristic.record_layout_components.get("elements").get("fnc_values").data_type
        axes_container = self.get_axes(characteristic, num_axes)

        # if category == "CURVE":
        #    memory_type = MemoryType.CURVE
        # elif category == "MAP":
        #    memory_type = MemoryType.MAP
        # else:
        #    memory_type = MemoryType.CUBOID
        num_func_values = reduce(operator.mul, axes_container.shape, 1)
        length = num_func_values * asam_type_size(fnc_datatype)
        fnc_values = characteristic.record_layout_components["elements"].get("fnc_values")
        address = fnc_values.address
        data_type = fnc_values.data_type
        try:
            raw = self.image.read_ndarray(
                addr=address,
                length=length,
                dtype=get_data_type(
                    data_type,
                    self.asam_mc.byte_order(characteristic),
                ),
                shape=axes_container.shape,
                # order = order,
                # bit_mask = characteristic.bitMask
            )
        except Exception as e:
            self.logger.error(f"{characteristic.name!r}:  {e}")
            raw = np.array([])
            phys = np.array([])
            # self.log_memory_errors(
            #    e, memory_type, characteristic.name, characteristic.address, characteristic.total_allocated_memory
            # )
        else:
            if axes_container.flip_axes:
                raw = np.flip(raw, axis=axes_container.flip_axes)
            try:
                phys = chr_cm.int_to_physical(raw)
            except Exception as e:
                self.logger.error(f"Exception in _load_curves_and_maps(): {e}")
                self.logger.error(f"CHARACTERISTIC: {characteristic.name!r}")
                self.logger.error(f"COMPU_METHOD: {chr_cm.name!r} ==> {chr_cm.evaluator!r}")
                self.logger.error(f"raw: {raw!r}")
                phys = np.array([0.0] * len(raw))
        return klass(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category=category,
            displayIdentifier=characteristic.displayIdentifier,
            raw=raw,
            phys=phys,
            fnc_unit=fnc_unit,
            axes=axes_container.axes,
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

    def save_curve_or_map(self, characteristic_name: str, category: str, num_axes: int, values: np.ndarray) -> None:
        characteristic = self.get_characteristic(characteristic_name, category, True)
        axes_container = self.get_axes(characteristic, num_axes)
        if values.shape != axes_container.shape:
            raise ValueError(f"Values shape ({values.shape}) does not match ({axes_container.shape})")
        print(axes_container)
        values = self.physical_to_int(characteristic, values)

        elements = characteristic.record_layout_components.get("elements")
        fnc_values = elements.get("fnc_values")
        address = fnc_values.address
        self.image.write_ndarray(addr=address, array=values, order=characteristic.fnc_np_order)
        """
        raw = self.image.read_ndarray(
                addr=characteristic.address + characteristic.record_layout_components.fncValues["offset"],
                length=length,
                dtype=get_data_type(
                    characteristic.record_layout_components.fncValues["datatype"],
                    self.asam_mc.byte_order(characteristic),
                ),
                shape=axes_container.shape,
                # order = order,
                # bit_mask = characteristic.bitMask
            )
        """

    def get_axes(self, characteristic: Characteristic, num_axes: int) -> AxesContainer:
        num_func_values = 1
        shape = []
        axes = []
        record_layout_components = characteristic.record_layout_components
        axes_values = self.read_axes_values(characteristic)
        # axes_arrays = self.read_axes_arrays(characteristic)
        for idx, axis_descr in enumerate(characteristic.axisDescriptions):
            axis_name = AXES[idx]
            flipper = []
            maxAxisPoints = axis_descr.maxAxisPoints
            axis_cm_name = "NO_COMPU_METHOD" if axis_descr.compuMethod == "NO_COMPU_METHOD" else axis_descr.compuMethod.name
            axis_cm = CompuMethod.get(self.session, axis_cm_name)
            axis_unit = axis_cm.unit
            axis_category = axis_descr.attribute
            reversed_storage = False
            axis_pts_ref = None
            match axis_category:
                case "STD_AXIS":
                    axis_values = axes_values.get(axis_name, {})
                    axis_arrays = self.read_axes_arrays(characteristic, axis_name)
                    if "fix_no_axis_pts" in axis_values:
                        no_axis_points = axis_values.get("fix_no_axis_pts")
                    elif "no_axis_pts" in axis_values:
                        no_axis_points = axis_values.get("no_axis_pts")
                    else:
                        no_axis_points = axis_descr.maxAxisPoints
                    raw_axis_values = axis_arrays.get("axis_pts")
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                case "CURVE_AXIS":
                    print("\tCURVE_AXIS:")
                case "COM_AXIS":
                    ref_obj = self.parameter_cache["AXIS_PTS"][axis_descr.axisPtsRef.name]
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = ref_obj.raw
                    converted_axis_values = ref_obj.phys
                    reversed_storage = ref_obj.reversed_storage
                    no_axis_points = len(ref_obj.raw)
                    # print("\tCOM_AXIS:", ref_obj)
                case "RES_AXIS":
                    print("\tRES_AXIS:")
                    ref_obj = self.parameter_cache["AXIS_PTS"][axis_descr.axisPtsRef.name]
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = ref_obj.raw
                    converted_axis_values = ref_obj.phys
                    reversed_storage = ref_obj.reversed_storage
                    no_axis_points = len(ref_obj.raw)
                    """

                    # no_axis_points = min(no_axis_points, len(ref_obj.raw) // 2)
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw)
                    reversed_storage = ref_obj.reversed_storage
                    """
                case "FIX_AXIS":
                    if axis_descr.fixAxisParDist.valid():
                        par_dist = axis_descr.fixAxisParDist
                        raw_axis_values = fix_axis_par_dist(
                            par_dist.offset,
                            par_dist.distance,
                            par_dist.numberapo,
                        )
                    elif axis_descr.fixAxisPar.valid():
                        par = axis_descr.fixAxisPar
                        raw_axis_values = fix_axis_par(par.offset, par.shift, par.numberapo)
                    elif axis_descr.fixAxisParList:
                        raw_axis_values = axis_descr.fixAxisParList
                    no_axis_points = len(raw_axis_values)
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                    axis_pts_ref = None
                    # print("\tFIX_AXIS:")
            num_func_values *= no_axis_points
            shape.append(no_axis_points)
            if reversed_storage:
                flipper.append(idx)
            axes.append(
                klasses.AxisContainer(
                    name=axis_name,
                    input_quantity=axis_descr.inputQuantity,
                    category=axis_category,
                    unit=axis_unit,
                    reversed_storage=reversed_storage,
                    raw=raw_axis_values,
                    phys=converted_axis_values,
                    axis_pts_ref=axis_pts_ref,
                    is_numeric=self.is_numeric(axis_cm),
                )
            )
        return AxesContainer(axes, shape=tuple(shape), flip_axes=flipper)
        ##
        ##
        ##
        for axis_idx in range(num_axes):
            axis_descr = characteristic.axisDescriptions[axis_idx]
            axis_name = AXES[axis_idx]
            maxAxisPoints = axis_descr.maxAxisPoints
            axis_cm_name = "NO_COMPU_METHOD" if axis_descr.compuMethod == "NO_COMPU_METHOD" else axis_descr.compuMethod.name
            axis_cm = CompuMethod.get(self.session, axis_cm_name)
            axis_unit = axis_cm.unit
            axis_category = axis_descr.attribute
            axis = characteristic.record_layout_components.axes.get(axis_name)
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
            if axis_category == "FIX_AXIS":
                if axis_descr.fixAxisParDist:
                    par_dist = axis_descr.fixAxisParDist
                    raw_axis_values = fix_axis_par_dist(
                        par_dist.offset,
                        par_dist.distance,
                        par_dist.numberapo,
                    )
                elif axis_descr.fixAxisParList:
                    raw_axis_values = axis_descr.fixAxisParList
                elif axis_descr.fixAxisPar:
                    par = axis_descr.fixAxisPar
                    raw_axis_values = fix_axis_par(par.offset, par.shift, par.numberapo)
                no_axis_points = len(raw_axis_values)
                converted_axis_values = axis_cm.int_to_physical(raw_axis_values)

            elif axis_category == "RES_AXIS":
                ref_obj = self.parameter_cache["AXIS_PTS"][axis_descr.axisPtsRef.name]
                # no_axis_points = min(no_axis_points, len(ref_obj.raw) // 2)
                axis_pts_ref = axis_descr.axisPtsRef.name
                raw_axis_values = []
                converted_axis_values = None
                axis_unit = None
                no_axis_points = len(ref_obj.raw)
                reversed_storage = ref_obj.reversed_storage
            elif axis_category == "CURVE_AXIS":
                ref_obj = self.parameter_cache["CURVE"][axis_descr.curveAxisRef.name]
                axis_pts_ref = axis_descr.curveAxisRef.name
                raw_axis_values = []
                converted_axis_values = None
                axis_unit = None
                no_axis_points = len(ref_obj.raw)
                reversed_storage = ref_obj.axes[0].reversed_storage
            elif axis_category == "COM_AXIS":
                ref_obj = self.parameter_cache["AXIS_PTS"][axis_descr.axisPtsRef.name]
                axis_pts_ref = axis_descr.axisPtsRef.name
                raw_axis_values = []
                converted_axis_values = []
                axis_unit = None
                no_axis_points = len(ref_obj.raw)
                reversed_storage = ref_obj.reversed_storage
            num_func_values *= no_axis_points
            shape.append(no_axis_points)
            if reversed_storage:
                flipper.append(axis_idx)
            axes.append(
                klasses.AxisContainer(
                    name=axis_name,
                    input_quantity=axis_descr.inputQuantity,
                    category=axis_category,
                    unit=axis_unit,
                    reversed_storage=reversed_storage,
                    raw=raw_axis_values,
                    phys=converted_axis_values,
                    axis_pts_ref=axis_pts_ref,
                    is_numeric=self.is_numeric(axis_cm),
                )
            )
        return AxesContainer(axes, shape=tuple(shape), flip_axes=flipper)

    def int_to_physical(self, characteristic, int_values):
        """Convert ECU internal values to physical representation."""
        cm = self.get_compu_method(characteristic)
        return cm.int_to_physical(int_values)

    def physical_to_int(self, characteristic, physical_values):
        """Convert physical values to ECU internal representation."""
        cm = self.get_compu_method(characteristic)
        value = cm.physical_to_int(physical_values)
        return value.astype(characteristic.fnc_np_dtype)

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

    def read_axes_values(self, obj: Union[AxisPts | Characteristic], axis_name: Optional[str] = None) -> dict:
        result = defaultdict(dict)
        components = obj.record_layout_components
        axes = components.get("axes")
        for ax_name in axes.keys():
            axis_info = axes.get(ax_name)
            axis_elements = axis_info.elements
            for name, attr in axis_elements.items():
                if name not in ("axis_pts", "axis_rescale"):
                    if name == "fix_no_axis_pts":
                        value = attr.number
                    else:
                        try:
                            value = self.image.read_numeric(attr.address, get_data_type(attr.data_type, self.byte_order(obj)))
                        except InvalidAddressError as e:
                            value = None
                            self.logger.error(f"{obj.name!r} {ax_name}-axis: {e}")
                    result[ax_name][name] = value
        if axis_name is not None and result:
            return result[axis_name]
        else:
            return result

    def read_axes_arrays(self, obj: Union[AxisPts | Characteristic], axis_name: Optional[str] = None) -> dict:
        NO_OF_POINTS = {"axis_pts": "no_axis_pts", "axis_rescale": "no_rescale"}
        result = defaultdict(dict)
        components = obj.record_layout_components
        axes = components.get("axes")
        for ax_name in axes.keys():
            axis_info = axes.get(ax_name)
            number_of_elements = axis_info.maximum_points
            axis_elements = axis_info.elements
            for name, attr in axis_elements.items():
                if name in ("axis_pts", "axis_rescale"):
                    try:
                        values = self.image.read_ndarray(
                            attr.address,
                            length=number_of_elements * asam_type_size(attr.data_type),
                            dtype=get_data_type(attr.data_type, self.byte_order(obj)),
                        )
                    except InvalidAddressError as e:
                        values = np.array([])
                        self.logger.error(f"{obj.name!r} {ax_name}-axis: {e}")
                    result[ax_name][name] = values
        if axis_name is not None and result:
            return result[axis_name]
        else:
            return result

    def read_nd_array(
        self, axis_pts: AxisPts, axis_name: str, component_name: str, no_elements: int, shape: Optional[tuple] = None, order=None
    ) -> np.ndarray:
        axis_info = axis_pts.record_layout_components["axes"].get(axis_name)
        data_type = axis_info.data_type
        component = axis_info.elements.get(component_name)
        address = component.address
        length = no_elements * asam_type_size(data_type)
        np_arr = self.image.read_ndarray(
            addr=address,
            length=length,
            dtype=get_data_type(data_type, self.byte_order(axis_pts)),
            shape=shape,
            order=order,
            # bit_mask = characteristic.bitMask
        )
        return np_arr

    def write_nd_array(self, axis_pts: AxisPts, axis_name: str, component_name: str, np_arr: np.ndarray, order=None) -> None:
        axes = axis_pts.record_layout_components.get("axes")
        axis = axes.get(axis_name)
        component = axis.elements[component_name]
        self.image.write_ndarray(addr=component.address, array=np_arr, order=order)

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
