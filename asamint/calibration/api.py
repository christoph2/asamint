#!/usr/bin/env python
"""
API for calibration data access and manipulation.
Provides classes and functions for working with ASAM calibration data.
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
from collections import defaultdict
from dataclasses import dataclass
from enum import IntEnum
from functools import partialmethod, reduce
from logging import Logger
from typing import Any, Optional, Union, cast

import numpy as np
from objutils import Image
from objutils.exceptions import InvalidAddressError
from pya2l import DB, model
from pya2l.api.inspect import (AxisPts, Characteristic, CompuMethod,
                               asam_type_size)
from pya2l.functions import Formula, fix_axis_par, fix_axis_par_dist

from asamint.asam import AsamMC, ByteOrder, get_data_type
from asamint.model.calibration import klasses
from asamint.utils import SINGLE_BITS, ffs

# Define type for calibration values
ValueType = Union[float, int, bool, str]

# Constants
BOOLEAN_MAP = {"true": 1, "false": 0}
AXES = ("x", "y", "z", "4", "5")

# Increase recursion limit for complex operations
sys.setrecursionlimit(2000)  # Required for pyinstrument benchmarks


@dataclass
class AxesContainer:
    """Container for axis information in calibration data.

    Attributes:
        axes: List of axis containers with axis data
        shape: Shape of the data array
        flip_axes: List of axes that need to be flipped
    """

    axes: list[klasses.AxisContainer]
    shape: tuple[int, ...]
    flip_axes: list[int]


class ExecutionPolicy(IntEnum):
    """Policy for handling errors during calibration operations.

    Attributes:
        EXCEPT: Raise an exception when an error occurs
        RETURN_ERROR: Return an error status instead of raising an exception
        IGNORE: Ignore errors and continue execution
    """

    EXCEPT = 0
    RETURN_ERROR = 1
    IGNORE = 2


class Status(IntEnum):
    """Status codes for calibration operations.

    Attributes:
        OK: Operation completed successfully
        READ_ONLY_ERROR: Attempted to write to a read-only parameter
        RANGE_ERROR: Value is outside the allowed range
    """

    OK = 0
    READ_ONLY_ERROR = 1
    RANGE_ERROR = 2


class RangeError(Exception):
    """Exception raised when a value is outside the allowed range for a characteristic."""

    pass


class ReadOnlyError(Exception):
    """Exception raised when attempting to write to a read-only characteristic."""

    pass


def check_limits(
    characteristic: Characteristic, value: float, extended_limits: bool = False
) -> bool:
    """Check if the value is within the limits of the characteristic.

    Args:
        characteristic: The characteristic to check limits against
        value: Value to check
        extended_limits: Also check extended limits if available

    Returns:
        True if value is within limits, False otherwise
    """
    # Check standard limits
    if value < characteristic.lowerLimit or value > characteristic.upperLimit:
        return False

    # Check extended limits if requested and available
    if extended_limits and characteristic.extendedLimits.valid():
        limits = characteristic.extendedLimits
        if value < limits.lowerLimit or value > limits.upperLimit:
            return False

    return True


class DictLike:
    """Dictionary-like class that caches values retrieved by a getter method.

    This class provides a dictionary-like interface where values are retrieved
    using a getter method and cached for subsequent access.
    """

    def __init__(self, getter_method: callable) -> None:
        """Initialize the DictLike object.

        Args:
            getter_method: Function to call when retrieving a value not in cache
        """
        self.getter_method = getter_method
        self.cache: dict[str, Any] = {}

    def __getitem__(self, item: str) -> Any:
        """Get an item from the cache or retrieve it using the getter method.

        Args:
            item: Key to retrieve

        Returns:
            The value associated with the key
        """
        # Return cached value if available
        if item in self.cache:
            return self.cache[item]

        # Otherwise retrieve using getter method and cache the result
        value = self.getter_method(item)
        self.cache[item] = value
        return value


class ParameterCache:
    """Cache for calibration parameters of different types.

    This class provides a dictionary-like interface for accessing different types
    of calibration parameters (curves, maps, values, etc.) with caching.
    """

    def set_parent(self, parent: "Calibration") -> None:
        """Set the parent calibration object and initialize caches.

        Args:
            parent: The parent Calibration object that provides loading methods
        """
        self.parent = parent

        # Initialize caches for different parameter types
        self.curves = DictLike(
            partialmethod(parent.load_curve_or_map, category="CURVE", num_axes=1)
        )
        self.maps = DictLike(
            partialmethod(parent.load_curve_or_map, category="MAP", num_axes=2)
        )
        self.cuboids = DictLike(
            partialmethod(parent.load_curve_or_map, category="CUBOID", num_axes=3)
        )
        self.cube4s = DictLike(
            partialmethod(parent.load_curve_or_map, category="CUBE_4", num_axes=4)
        )
        self.cube5s = DictLike(
            partialmethod(parent.load_curve_or_map, category="CUBE_5", num_axes=5)
        )
        self.axis_pts = DictLike(parent.load_axis_pts)
        self.values = DictLike(parent.load_value)
        self.asciis = DictLike(parent.load_ascii)
        self.value_blocks = DictLike(parent.load_value_block)

        # Map parameter types to their respective caches
        self.dicts: dict[str, DictLike] = {
            "CURVE": self.curves,
            "AXIS_PTS": self.axis_pts,
            "VALUE": self.values,
            "ASCII": self.asciis,
            "MAP": self.maps,
            "VAL_BLK": self.value_blocks,
            "CUBOID": self.cuboids,
            "CUBE_4": self.cube4s,
            "CUBE_5": self.cube5s,
        }

    def __getitem__(self, item: str) -> DictLike:
        """Get the cache for a specific parameter type.

        Args:
            item: Parameter type (e.g., "CURVE", "MAP", "VALUE")

        Returns:
            The DictLike cache for the specified parameter type
        """
        return self.dicts.get(item)


class Calibration:
    """Base class for calibration data access and manipulation.

    This class provides methods for loading and saving calibration data of various types
    (values, curves, maps, etc.) from/to memory images or ECUs.
    """

    def __init__(
        self,
        asam_mc: AsamMC,
        image: Image,
        parameter_cache: Union[dict[str, Any], ParameterCache],
        logger: Logger,
    ) -> None:
        """Initialize the Calibration object.

        Args:
            asam_mc: ASAM MC object providing access to A2L data
            image: Memory image containing calibration data
            parameter_cache: Cache for calibration parameters
            logger: Logger for recording operations and errors
        """
        self.image = image
        self.asam_mc = asam_mc
        self.session = asam_mc.session
        self.parameter_cache = parameter_cache
        if isinstance(parameter_cache, ParameterCache):
            self.parameter_cache.set_parent(self)
        self.logger = logger
        self.mod_common = asam_mc.mod_common
        self.mod_par = asam_mc.mod_par

    def update(self) -> None:
        """Perform the actual update of parameters (write to HEX file / XCP).

        This method should be implemented by subclasses to perform the actual
        writing of calibration data to the target.
        """
        pass

    def load(self, name: str) -> Any:
        """Load a calibration parameter by name.

        This method determines the type of the parameter and calls the appropriate
        specialized loading method.

        Args:
            name: Name of the parameter to load

        Returns:
            The loaded parameter value or object

        Raises:
            ValueError: If the parameter is not found
        """
        # First try to find a characteristic with this name
        chr = (
            self.session.query(model.Characteristic)
            .filter(model.Characteristic.name == name)
            .first()
        )

        if chr is None:
            # If not a characteristic, try to find an axis points object
            axis_pts = (
                self.session.query(model.AxisPts)
                .filter(model.AxisPts.name == name)
                .first()
            )
            if axis_pts:
                return self.load_axis_pts(name)
            else:
                raise ValueError(f"Parameter '{name}' not found")

        # Dispatch to the appropriate loading method based on characteristic type
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
            case _:
                raise ValueError(f"Unsupported characteristic type: {chr.type}")

        return result

    def save(self, name: str, value: Any) -> None:
        """Save a value to a calibration parameter.

        This method determines the type of the parameter and calls the appropriate
        specialized saving method.

        A consistent API is provided: you may pass either a primitive/ndarray or
        the object returned by `load(name)` (which has `.phys`/`.raw`).

        Args:
            name: Name of the parameter to save to
            value: Value to save

        Raises:
            ValueError: If the parameter is not found
            TypeError: If the value type doesn't match the parameter type
        """
        # First try to find a characteristic with this name
        chr = (
            self.session.query(model.Characteristic)
            .filter(model.Characteristic.name == name)
            .first()
        )

        if chr is None:
            # If not a characteristic, try to find an axis points object
            axis_pts = (
                self.session.query(model.AxisPts)
                .filter(model.AxisPts.name == name)
                .first()
            )
            if axis_pts:
                # save_axis_pts already accepts either an AxisPts-like object or an array
                self.save_axis_pts(name, value)
            else:
                raise ValueError(f"Parameter '{name}' not found")
        else:
            # Normalize wrapper objects (from load()) to their underlying values, if needed
            def _normalize_ascii(v: Any) -> str:
                if hasattr(v, "phys"):
                    return cast(str, v.phys)
                return cast(str, v)

            def _normalize_array(v: Any) -> np.ndarray:
                if hasattr(v, "phys"):
                    return np.asarray(v.phys)
                return np.asarray(v)

            def _normalize_value(v: Any) -> Any:
                # For VALUE characteristics prefer physical value if present
                if hasattr(v, "phys"):
                    return v.phys
                if hasattr(v, "raw"):
                    # Fallback to raw if provided, will be converted accordingly by save_value
                    return v.raw
                return v

            # Dispatch to the appropriate saving method based on characteristic type
            match chr.type:
                case "ASCII":
                    self.save_ascii(name, _normalize_ascii(value))
                case "CUBOID":
                    self.save_curve_or_map(name, value)
                case "CUBE_4":
                    self.save_curve_or_map(name, value)
                case "CUBE_5":
                    self.save_curve_or_map(name, value)
                case "CURVE":
                    self.save_curve_or_map(name, value)
                case "MAP":
                    self.save_curve_or_map(name, value)
                case "VAL_BLK":
                    self.save_value_block(name, _normalize_array(value))
                case "VALUE":
                    self.save_value(name, _normalize_value(value))
                case _:
                    raise ValueError(f"Unsupported characteristic type: {chr.type}")

    def load_ascii(self, characteristic_name: str) -> klasses.Ascii:
        """Load an ASCII string characteristic.

        Args:
            characteristic_name: Name of the ASCII characteristic to load

        Returns:
            An Ascii object containing the loaded string value and metadata

        Raises:
            ValueError: If the characteristic is not found or not of type ASCII
        """
        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, "ASCII", False)

        # Determine the string length
        if characteristic.matrixDim.valid():
            length = characteristic.matrixDim.x
        else:
            length = characteristic.number

        # Read the string from memory
        value: Optional[str] = None
        try:
            value = self.image.read_string(characteristic.address, length=length)
        except Exception as e:
            self.logger.error(f"{characteristic.name!r}: {e}")
            value = None

        # Create and return the Ascii object
        return klasses.Ascii(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category="ASCII",
            _raw=value,
            _phys=value,
            displayIdentifier=characteristic.displayIdentifier,
            api=self,
        )

    def save_ascii(
        self,
        characteristic_name: str,
        value: Any,
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
    ) -> Status:
        """Save a string value to an ASCII characteristic.

        Args:
            characteristic_name: Name of the ASCII characteristic to save to
            value: String value to save
            readOnlyPolicy: Policy for handling read-only characteristics

        Returns:
            Status indicating success or failure

        Raises:
            ReadOnlyError: If the characteristic is read-only and policy is EXCEPT
            ValueError: If the characteristic is not found or not of type ASCII
        """
        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, "ASCII", True)

        # Check if the characteristic is read-only
        if characteristic.readOnly:
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(
                    f"Characteristic '{characteristic_name}' is read-only."
                )
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR

        # Normalize: allow wrapper objects from load_ascii
        if hasattr(value, "phys"):
            value = value.phys
        elif hasattr(value, "raw"):
            value = value.raw

        # Ensure we have a string (handle None as empty string)
        value = "" if value is None else str(value)

        # Determine the string length
        if characteristic.matrixDim:
            length = characteristic.matrixDim.x
        else:
            length = characteristic.number

        # Adjust the string to the required length
        # Truncate if too long
        value = value[:length]
        # Pad with nulls if too short
        value = value.ljust(length, "\x00")

        # Write the string to memory
        self.image.write_string(characteristic.address, length=length, value=value)
        return Status.OK

    def load_value_block(self, characteristic_name: str) -> klasses.ValueBlock:
        """Load a value block characteristic.

        Args:
            characteristic_name: Name of the value block characteristic to load

        Returns:
            A ValueBlock object containing the loaded values and metadata

        Raises:
            ValueError: If the characteristic is not found or not of type VAL_BLK
        """
        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, "VAL_BLK", False)

        # Initialize empty arrays
        raw: np.ndarray = np.array([])
        phys: np.ndarray = np.array([])

        # Calculate shape and size
        shape = characteristic.fnc_np_shape[::-1]
        num_func_values = reduce(operator.mul, shape, 1)
        length = num_func_values * asam_type_size(characteristic.fnc_asam_dtype)

        # Read the array from memory
        try:
            raw = self.image.read_ndarray(
                addr=characteristic.address,
                length=length,
                dtype=get_data_type(
                    characteristic.fnc_asam_dtype, self.byte_order(characteristic)
                ),
                shape=shape,
                order=characteristic.fnc_np_order,
                bit_mask=characteristic.bitMask,
            )
        except Exception as e:
            self.logger.error(f"{characteristic.name!r}: {e}")
        else:
            # Convert to physical values if read was successful
            phys = self.int_to_physical(characteristic, raw)

        # Create and return the ValueBlock object
        return klasses.ValueBlock(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category="VAL_BLK",
            _raw=raw,
            _phys=phys,
            displayIdentifier=characteristic.displayIdentifier,
            shape=shape,
            unit=characteristic.physUnit,
            is_numeric=self.is_numeric(characteristic.compuMethod),
            api=self,
        )

    def save_value_block(
        self,
        characteristic_name: str,
        values: np.ndarray,
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
    ) -> Status:
        """Save values to a value block characteristic.

        Args:
            characteristic_name: Name of the value block characteristic to save to
            values: Array of values to save
            readOnlyPolicy: Policy for handling read-only characteristics

        Returns:
            Status indicating success or failure

        Raises:
            ReadOnlyError: If the characteristic is read-only and policy is EXCEPT
            ValueError: If the characteristic is not found, not of type VAL_BLK,
                        or if the shape of values doesn't match the expected shape
        """
        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, "VAL_BLK", True)

        # Check if the characteristic is read-only
        if characteristic.readOnly:
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(
                    f"Characteristic '{characteristic_name}' is read-only."
                )
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR

        # Normalize input to numpy physical array (support wrapper from load_value_block)
        if hasattr(values, "phys"):
            phys_vals = np.asarray(values.phys)
        else:
            phys_vals = np.asarray(values)

        # Expected external shape matches what load_value_block returns
        expected_shape = characteristic.fnc_np_shape[::-1]

        # Verify that the shape of the values matches the expected shape
        if phys_vals.shape != expected_shape:
            raise ValueError(
                f"Shape mismatch: characteristic '{characteristic_name}' expects {expected_shape}, got {phys_vals.shape}"
            )

        # Convert to internal representation and write to memory
        int_vals = self.physical_to_int(characteristic, phys_vals)
        self.image.write_ndarray(
            addr=characteristic.address,
            array=int_vals,
            order=characteristic.fnc_np_order,
        )
        return Status.OK

    def load_value(self, characteristic_name: str) -> klasses.Value:
        """Load a scalar value characteristic.

        Args:
            characteristic_name: Name of the value characteristic to load

        Returns:
            A Value object containing the loaded value and metadata

        Raises:
            ValueError: If the characteristic is not found or not of type VALUE
        """
        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, "VALUE", False)

        # Handle virtual characteristics (computed from other characteristics)
        virtual_characteristic = characteristic.virtual_characteristic
        raw = 0
        if virtual_characteristic is not None:
            vc_values = []
            formula = virtual_characteristic.formula
            # Collect values from referenced characteristics
            for chx_name in virtual_characteristic.characteristics:
                category = self.characteristic_category(chx_name)
                chx = self.parameter_cache[category].get(chx_name)
                vc_values.append(chx.phys)
            # Apply the formula to compute the value
            fx = Formula(
                formula=formula, system_constants=self.asam_mc.mod_par.systemConstants
            )
            result = fx.int_to_physical(*vc_values)
            self.logger.debug(
                f"Virtual characteristic {characteristic_name} computed value: {result}"
            )

        # Get the data type for reading
        fnc_asam_dtype = characteristic.fnc_asam_dtype
        reader = get_data_type(fnc_asam_dtype, self.byte_order(characteristic))

        # Handle bit-masked values
        if characteristic.bitMask:
            raw = self.image.read_numeric(
                characteristic.address, reader, bit_mask=characteristic.bitMask
            )
            # Right-shift to get rid of trailing zeros (s. ASAM 2-MC spec)
            raw >>= ffs(characteristic.bitMask)
            is_bool = characteristic.bitMask in SINGLE_BITS
        else:
            # Read normal values
            try:
                raw = self.image.read_numeric(characteristic.address, reader)
            except Exception as e:
                self.logger.error(f"{characteristic.name!r}: {e}")
                raw = 0
            is_bool = False

        # Determine the physical unit
        if (
            characteristic.physUnit is None
            and characteristic._conversionRef != "NO_COMPU_METHOD"
        ):
            unit = characteristic.compuMethod.unit
        else:
            unit = characteristic.physUnit

        # Convert to physical value
        phys = self.int_to_physical(characteristic, raw)

        # Determine the category based on the value type
        is_numeric = self.is_numeric(characteristic.compuMethod)
        if is_numeric:
            if is_bool:
                category = "BOOLEAN"
            else:
                category = "VALUE"
        else:
            category = "TEXT"

        # Special case for dependent characteristics
        if characteristic.dependent_characteristic:
            category = "DEPENDENT_VALUE"

        # Create and return the Value object
        return klasses.Value(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category=category,
            _raw=raw,
            _phys=phys,
            displayIdentifier=characteristic.displayIdentifier,
            unit=unit,
            is_numeric=is_numeric,
            api=self,
        )

    def save_value(
        self,
        characteristic_name: str,
        value: ValueType,
        extendedLimits: bool = False,
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
        limitsPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
    ) -> Status:
        """Save a value to a scalar value characteristic.

        Args:
            characteristic_name: Name of the value characteristic to save to
            value: Value to save (float, int, bool, or str)
            extendedLimits: Whether to check extended limits
            readOnlyPolicy: Policy for handling read-only characteristics
            limitsPolicy: Policy for handling values outside limits

        Returns:
            Status indicating success or failure

        Raises:
            TypeError: If value is not of the expected type
            ReadOnlyError: If the characteristic is read-only and policy is EXCEPT
            RangeError: If the value is outside limits and policy is EXCEPT
            ValueError: If the characteristic is not found, not of type VALUE,
                        or if a string value is not in the allowed set
        """
        # Normalize: allow wrapper objects from load_value
        if hasattr(value, "phys"):
            value = value.phys
        elif hasattr(value, "raw"):
            value = value.raw

        # Validate value type
        if not isinstance(value, (float, int, bool, str)):
            raise TypeError("value must be float, int, bool or str")

        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, "VALUE", True)

        # Check if the characteristic is read-only
        if characteristic.readOnly:
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(
                    f"Characteristic '{characteristic_name}' is read-only."
                )
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR

        # Handle text values for verbal tables
        if characteristic.compuMethod.conversionType == "TAB_VERB":
            text_values = characteristic.compuMethod.tab_verb.get("text_values")
            if value not in text_values:
                raise ValueError(f"value must be in {text_values} got {value}.")
        # Convert boolean values to integers
        elif isinstance(value, bool):
            value = int(value)
        # Handle string values that represent booleans
        elif isinstance(value, str) and value in ("true", "false"):
            value = BOOLEAN_MAP[value]
        # Reject other string values
        elif isinstance(value, str):
            raise ValueError("value of type str must be 'true' or 'false'")

        # Get the data type for writing
        dtype = get_data_type(
            characteristic.fnc_asam_dtype, self.byte_order(characteristic)
        )

        # Check if the value is within limits
        if isinstance(value, (int, float)) and not check_limits(
            characteristic, value, extendedLimits
        ):
            self.logger.info(f"Characteristic '{characteristic_name}' is out of range")
            if limitsPolicy == ExecutionPolicy.EXCEPT:
                raise RangeError(
                    f"Characteristic '{characteristic_name}' is out of range"
                )
            elif limitsPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.RANGE_ERROR

        # Convert to internal representation
        phys = self.physical_to_int(characteristic, value)

        # Handle bit-masked values
        if characteristic.bitMask:
            phys = int(phys)
            phys <<= ffs(characteristic.bitMask)

        # Write to memory
        self.image.write_numeric(characteristic.address, phys, dtype)
        return Status.OK

    def load_axis_pts(self, axis_pts_name: str) -> klasses.AxisPts:
        """Load axis points.

        Args:
            axis_pts_name: Name of the axis points to load

        Returns:
            An AxisPts object containing the loaded axis points and metadata

        Raises:
            ValueError: If the axis points are not found
        """
        # Get the axis points definition
        ap = self.get_axis_pts(axis_pts_name)

        # Read axis values and arrays
        axis_values = self.read_axes_values(ap, "x")
        axis_arrays = self.read_axes_arrays(ap, "x")
        axes = ap.record_layout_components.get("axes")
        axis_info = axes.get("x")

        # Handle different axis categories
        if axis_info.category == "COM_AXIS":
            raw = axis_arrays.get("axis_pts")
            no_axis_pts = axis_values.get("no_axis_pts")
        elif axis_info.category == "RES_AXIS":
            raw = axis_arrays.get("axis_rescale")
            no_axis_pts = axis_values.get("no_rescale") * 2
        else:
            self.logger.warning(f"Unsupported axis category: {axis_info.category}")
            raw = np.array([])
            no_axis_pts = 0

        # Limit to the actual number of points
        if raw is not None and no_axis_pts is not None:
            raw = raw[:no_axis_pts]

            # Handle reversed storage
            if axis_info.reversed_storage:
                raw = raw[::-1]

            # Convert to physical values
            phys = self.int_to_physical(ap, raw)
        else:
            raw = np.array([])
            phys = np.array([])

        # Get the unit
        unit = ap.compuMethod.refUnit

        # Create and return the AxisPts object
        return klasses.AxisPts(
            name=ap.name,
            comment=ap.longIdentifier,
            category=axis_info.category,
            _raw=raw,
            _phys=phys,
            displayIdentifier=ap.displayIdentifier,
            paired=False,  # Will be removed in future versions
            unit=unit,
            reversed_storage=False,  # Will be removed in future versions
            is_numeric=self.is_numeric(ap.compuMethod),
            api=self,
        )

    def save_axis_pts(self, axis_pts_name: str, values: np.ndarray) -> Status:
        """Save values to axis points.

        Args:
            axis_pts_name: Name of the axis points to save to
            values: Array of values to save (can be a klasses.AxisPts-like with .phys or a numpy array)

        Returns:
            Status indicating success or failure

        Raises:
            TypeError: If the axis points are not physically allocated
            ValueError: If the values array has wrong dimensions or size
        """
        # Get the axis points definition
        ap = self.get_axis_pts(axis_pts_name)

        # Normalize input to a 1D numpy array of physical values
        phys_vals = None
        if hasattr(values, "phys"):
            phys_vals = np.asarray(values.phys)
        else:
            phys_vals = np.asarray(values)

        # Read axis values and info
        # axis_values = self.read_axes_values(ap, "x")
        axes = ap.record_layout_components.get("axes")
        axis_info = axes.get("x")

        # Check if the axis is physically allocated
        if axis_info.category == "FIX_AXIS":
            raise TypeError(
                f"AXIS_PTS {axis_pts_name!r} is not physically allocated, use A2L to change."
            )

        # Validate the values array
        if phys_vals.ndim != 1:
            raise ValueError("values must be a 1D array")

        # Determine component name and sizing rules based on category
        component_name = "axis_pts"
        if axis_info.category == "RES_AXIS":
            component_name = "axis_rescale"
            # For RES_AXIS, values come in pairs (index, value) -> length must be even
            if phys_vals.size % 2 != 0:
                raise ValueError(
                    "RES_AXIS values length must be even (pairs of index and value)"
                )

        # Check array size against constraints
        if component_name == "axis_pts":
            # Handle COM_AXIS sizing
            if "no_axis_pts" not in axis_info.elements:
                # Fixed size axis
                if phys_vals.size != ap.maxAxisPoints:
                    raise ValueError(
                        f"values: expected an array with {ap.maxAxisPoints} elements."
                    )
            elif phys_vals.size > ap.maxAxisPoints:
                # Variable size axis but too many points
                raise ValueError(
                    f"values size ({phys_vals.size}) exceeds maxAxisPoints ({ap.maxAxisPoints})"
                )
            else:
                # Variable size axis, update the number of points
                no_axis_pts = axis_info.elements.get("no_axis_pts")
                data_type = get_data_type(no_axis_pts.data_type, self.byte_order(ap))
                self.image.write_numeric(
                    addr=no_axis_pts.address, value=phys_vals.size, dtype=data_type
                )
        else:
            # RES_AXIS sizing uses no_rescale (number of pairs)
            max_pairs = (
                ap.maxAxisPoints
            )  # per A2L this is the maximum number of rescale points
            if (phys_vals.size // 2) > max_pairs:
                raise ValueError(
                    f"values size ({phys_vals.size // 2} pairs) exceeds maxAxisPoints ({max_pairs})"
                )
            # Update the number of rescale pairs if adjustable
            if "no_rescale" in axis_info.elements:
                no_rescale = axis_info.elements.get("no_rescale")
                dtype_nr = get_data_type(no_rescale.data_type, self.byte_order(ap))
                self.image.write_numeric(
                    addr=no_rescale.address, value=(phys_vals.size // 2), dtype=dtype_nr
                )

        # Convert to internal representation
        int_values = self.physical_to_int(ap, phys_vals)

        # Apply reversed storage if needed
        if getattr(axis_info, "reversed_storage", False):
            int_values = int_values[::-1]

        # Write to memory using the appropriate component
        self.write_nd_array(ap, "x", component_name, int_values)
        return Status.OK

    def load_curve_or_map(
        self, characteristic_name: str, category: str, num_axes: int
    ) -> Union[
        klasses.Cube4, klasses.Cube5, klasses.Cuboid, klasses.Curve, klasses.Map
    ]:
        """Load a curve or map characteristic.

        Args:
            characteristic_name: Name of the characteristic to load
            category: Type of characteristic ("CURVE", "MAP", "CUBOID", etc.)
            num_axes: Number of axes (1 for curve, 2 for map, etc.)

        Returns:
            A calibration object containing the loaded values and metadata

        Raises:
            ValueError: If the characteristic is not found or not of the specified type
        """
        # Get the appropriate class for this category
        klass = klasses.get_calibration_class(category)

        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, category, True)
        # Initialize empty array
        raw = np.array([])

        # Get the computation method
        if characteristic.compuMethod != "NO_COMPU_METHOD":
            characteristic_cm = characteristic.compuMethod.name
        else:
            characteristic_cm = "NO_COMPU_METHOD"
        chr_cm = CompuMethod.get(self.session, characteristic_cm)

        # Get function unit and data type
        fnc_unit = chr_cm.unit
        fnc_datatype = (
            characteristic.record_layout_components.get("elements")
            .get("fnc_values")
            .data_type
        )

        # Get axes information
        axes_container = self.get_axes(characteristic, num_axes)

        # Calculate size and shape
        num_func_values = reduce(operator.mul, axes_container.shape, 1)
        length = num_func_values * asam_type_size(fnc_datatype)

        # Get function values information
        fnc_values = characteristic.record_layout_components["elements"].get(
            "fnc_values"
        )
        address = fnc_values.address
        data_type = fnc_values.data_type
        order = characteristic.fnc_np_order

        # Read the array from memory
        try:
            raw = self.image.read_ndarray(
                addr=address,
                length=length,
                dtype=get_data_type(
                    data_type,
                    self.byte_order(characteristic),
                ),
                shape=axes_container.shape,
                order=order,
            )
        except Exception as e:
            self.logger.error(f"{characteristic.name!r}: {e}")
            raw = np.array([])
            phys = np.array([])
        else:
            # Flip axes if needed
            if axes_container.flip_axes:
                raw = np.flip(raw, axis=axes_container.flip_axes)

            # Convert to physical values
            try:
                phys = chr_cm.int_to_physical(raw)
            except Exception as e:
                self.logger.error(
                    f"Exception converting values for {characteristic.name!r}: {e}"
                )
                self.logger.error(
                    f"COMPU_METHOD: {chr_cm.name!r} ==> {chr_cm.evaluator!r}"
                )
                # Create empty physical values array with same shape as raw
                if raw.size > 0:
                    phys = np.zeros_like(raw, dtype=float)
                else:
                    phys = np.array([])
        # Create and return the appropriate calibration object
        return klass(
            name=characteristic.name,
            comment=characteristic.longIdentifier,
            category=category,
            displayIdentifier=characteristic.displayIdentifier,
            _raw=raw,
            _phys=phys,
            fnc_unit=fnc_unit,
            axes=axes_container.axes,
            is_numeric=self.is_numeric(characteristic.compuMethod),
            api=self,
        )

    def save_curve_or_map(
        self,
        characteristic_name: str,
        values: Union[
            klasses.Cube4, klasses.Cube5, klasses.Cuboid, klasses.Curve, klasses.Map
        ],
        readOnlyPolicy: ExecutionPolicy = ExecutionPolicy.EXCEPT,
        raw_changed: bool = False,
    ) -> Status:
        """Save values to a curve or map characteristic.

        Args:
            characteristic_name: Name of the characteristic to save to
            values: The wrapper returned by load_curve_or_map (Curve/Map/Cuboid/Cube4/Cube5)
            readOnlyPolicy: Policy for handling read-only characteristics
            raw_changed: Set to True if the raw values were changed and the physical values need to be recalculated.

        Returns:
            Status indicating success or failure

        Raises:
            ValueError: If the characteristic is not found or if the shape of values doesn't match
            ReadOnlyError: If characteristic is read-only and policy is EXCEPT
        """
        # Get the characteristic definition
        characteristic = self.get_characteristic(characteristic_name, None, True)
        if characteristic is None:
            raise ValueError(f"Characteristic '{characteristic_name}' not found")

        # Determine category and number of axes from the characteristic definition
        category = characteristic.type
        axes_map = {"CURVE": 1, "MAP": 2, "CUBOID": 3, "CUBE_4": 4, "CUBE_5": 5}
        num_axes = axes_map.get(category)
        if num_axes is None:
            raise ValueError(f"Unsupported characteristic type: {category}")

        # Read-only handling
        if getattr(characteristic, "readOnly", False):
            self.logger.info(f"Characteristic '{characteristic_name}' is READ-ONLY!")
            if readOnlyPolicy == ExecutionPolicy.EXCEPT:
                raise ReadOnlyError(
                    f"Characteristic '{characteristic_name}' is read-only."
                )
            elif readOnlyPolicy == ExecutionPolicy.RETURN_ERROR:
                return Status.READ_ONLY_ERROR

        # Get axes information
        axes_container = self.get_axes(characteristic, num_axes)

        # Ensure the values object has the correct shape
        expected_shape = axes_container.shape
        if raw_changed:
            if values.raw.shape != expected_shape:
                raise ValueError(
                    f"Raw values shape {values.raw.shape} does not match expected shape {expected_shape}"
                )
        else:
            if values.phys.shape != expected_shape:
                raise ValueError(
                    f"Physical values shape {values.phys.shape} does not match expected shape {expected_shape}"
                )

        self.logger.debug(
            f"Saving {category} '{characteristic_name}' with shape {expected_shape}"
        )

        # Convert between physical and internal representation and update the values object
        if raw_changed:
            # Raw values changed, so update physical values
            int_values = np.asarray(values.raw)
            values.phys = self.int_to_physical(characteristic, int_values)
        else:
            # Physical values changed, so update raw values
            phys_vals = np.asarray(values.phys)
            int_values = self.physical_to_int(characteristic, phys_vals)
            values.raw = int_values

        # Flip axes back for reversed storage if needed
        if axes_container.flip_axes:
            int_values = np.flip(int_values, axis=axes_container.flip_axes)

        # Get function values information and write to memory
        elements = characteristic.record_layout_components.get("elements")
        fnc_values = elements.get("fnc_values")
        address = fnc_values.address
        self.image.write_ndarray(
            addr=address, array=int_values, order=characteristic.fnc_np_order
        )
        return Status.OK

    def get_axes(self, characteristic: Characteristic, num_axes: int) -> AxesContainer:
        """Get axis information for a characteristic.

        This method extracts axis information from a characteristic, including
        axis values, shapes, and metadata.

        Args:
            characteristic: The characteristic to get axes for
            num_axes: Number of axes to process

        Returns:
            An AxesContainer with axis information

        Raises:
            ValueError: If there's an error processing the axes
        """
        shape = []
        axes = []

        # Read axis values
        axes_values = self.read_axes_values(characteristic)

        # Track axes that need to be flipped
        flip_position = 0
        flipper = []

        # Process each axis
        for idx, axis_descr in enumerate(characteristic.axisDescriptions):
            # Get basic axis information
            axis_name = AXES[idx]
            max_axis_points = axis_descr.maxAxisPoints

            # Get computation method
            axis_cm_name = (
                "NO_COMPU_METHOD"
                if axis_descr.compuMethod == "NO_COMPU_METHOD"
                else axis_descr.compuMethod.name
            )
            axis_cm = CompuMethod.get(self.session, axis_cm_name)
            axis_unit = axis_cm.unit

            # Get axis category
            axis_category = axis_descr.attribute
            reversed_storage = False
            axis_pts_ref = None
            flip_position -= 1

            # Process based on axis category
            match axis_category:
                case "STD_AXIS":
                    # Standard axis with values in the characteristic
                    axis_values = axes_values.get(axis_name, {})
                    axis_arrays = self.read_axes_arrays(characteristic, axis_name)
                    axis_info = characteristic.axis_info(axis_name)
                    reversed_storage = axis_info.reversed_storage

                    # Determine number of axis points
                    if "fix_no_axis_pts" in axis_values:
                        no_axis_points = axis_values.get("fix_no_axis_pts")
                    elif "no_axis_pts" in axis_values:
                        no_axis_points = axis_values.get("no_axis_pts")
                    else:
                        no_axis_points = max_axis_points

                    # Get and process axis values
                    raw_axis_values = axis_arrays.get("axis_pts")
                    if raw_axis_values is not None:
                        raw_axis_values = raw_axis_values[:no_axis_points]
                        if reversed_storage:
                            raw_axis_values = raw_axis_values[::-1]
                        converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                    else:
                        raw_axis_values = np.array([])
                        converted_axis_values = np.array([])

                case "CURVE_AXIS":
                    # Axis referencing a curve
                    ref_obj = self.parameter_cache["CURVE"][
                        axis_descr.curveAxisRef.name
                    ]
                    axis_pts_ref = axis_descr.curveAxisRef.name
                    raw_axis_values = []
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw)
                    reversed_storage = ref_obj.axes[0].reversed_storage

                case "COM_AXIS":
                    # Axis referencing axis points
                    ref_obj = self.parameter_cache["AXIS_PTS"][
                        axis_descr.axisPtsRef.name
                    ]
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = ref_obj.raw
                    converted_axis_values = ref_obj.phys
                    reversed_storage = ref_obj.reversed_storage
                    no_axis_points = len(ref_obj.raw)

                case "RES_AXIS":
                    # Rescale axis
                    self.logger.debug(f"Processing RES_AXIS for {characteristic.name}")
                    ref_obj = self.parameter_cache["AXIS_PTS"][
                        axis_descr.axisPtsRef.name
                    ]
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = ref_obj.raw
                    converted_axis_values = ref_obj.phys
                    reversed_storage = ref_obj.reversed_storage
                    no_axis_points = len(ref_obj.raw)

                case "FIX_AXIS":
                    # Fixed axis with values defined in A2L
                    if axis_descr.fixAxisParDist.valid():
                        # Fixed axis with distance parameter
                        par_dist = axis_descr.fixAxisParDist
                        raw_axis_values = fix_axis_par_dist(
                            par_dist.offset,
                            par_dist.distance,
                            par_dist.numberapo,
                        )
                    elif axis_descr.fixAxisPar.valid():
                        # Fixed axis with shift parameter
                        par = axis_descr.fixAxisPar
                        raw_axis_values = fix_axis_par(
                            par.offset, par.shift, par.numberapo
                        )
                    elif axis_descr.fixAxisParList:
                        # Fixed axis with explicit list of values
                        raw_axis_values = axis_descr.fixAxisParList
                    else:
                        self.logger.warning(
                            f"FIX_AXIS without parameters for {characteristic.name}"
                        )
                        raw_axis_values = np.array([])

                    no_axis_points = len(raw_axis_values)
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                    axis_pts_ref = None

                case _:
                    # Unsupported axis category
                    self.logger.warning(f"Unsupported axis category: {axis_category}")
                    raw_axis_values = np.array([])
                    converted_axis_values = np.array([])
                    no_axis_points = 0

            # Update shape information
            shape.insert(0, no_axis_points)

            # Track axes that need to be flipped
            if reversed_storage:
                flipper.append(flip_position)

            # Create and add axis container
            axes.append(
                klasses.AxisContainer(
                    name=axis_name,
                    # comment="", # axis_descr.comment,
                    input_quantity=axis_descr.inputQuantity,
                    category=axis_category,
                    unit=axis_unit,
                    reversed_storage=reversed_storage,
                    raw=raw_axis_values,
                    phys=converted_axis_values,
                    axis_pts_ref=axis_pts_ref,
                    is_numeric=self.is_numeric(axis_cm),
                    # api=self,
                )
            )

        # Create and return axes container
        return AxesContainer(axes, shape=tuple(shape), flip_axes=flipper)

    def int_to_physical(
        self, characteristic: Union[Characteristic, AxisPts], int_values: np.ndarray
    ) -> np.ndarray:
        """Convert ECU internal values to physical representation.

        Args:
            characteristic: The characteristic or axis points containing the computation method
            int_values: Internal values to convert

        Returns:
            Physical values
        """
        cm = self.get_compu_method(characteristic)
        return cm.int_to_physical(int_values)

    def physical_to_int(
        self,
        characteristic: Union[Characteristic, AxisPts],
        physical_values: Union[np.ndarray, float, int],
    ) -> np.ndarray:
        """Convert physical values to ECU internal representation.

        Args:
            characteristic: The characteristic or axis points containing the computation method
            physical_values: Physical values to convert

        Returns:
            Internal values with the appropriate data type
        """
        cm = self.get_compu_method(characteristic)
        value = cm.physical_to_int(physical_values)
        return value.astype(characteristic.fnc_np_dtype)

    def get_compu_method(
        self, characteristic: Union[Characteristic, AxisPts]
    ) -> CompuMethod:
        """Get the computation method for a characteristic or axis points.

        Args:
            characteristic: The characteristic or axis points to get the computation method for

        Returns:
            The computation method
        """
        cm_name = (
            "NO_COMPU_METHOD"
            if characteristic.compuMethod == "NO_COMPU_METHOD"
            else characteristic.compuMethod.name
        )
        return CompuMethod.get(self.session, cm_name)

    def get_characteristic(
        self, characteristic_name: str, type_name: str, save: bool = False
    ) -> Characteristic:
        """Get a characteristic by name and verify its type.

        Args:
            characteristic_name: Name of the characteristic to get
            type_name: Expected type of the characteristic
            save: Whether the characteristic will be used for saving

        Returns:
            The characteristic

        Raises:
            ValueError: If the characteristic is not found
            TypeError: If the characteristic is not of the expected type
        """
        characteristic = self._load_characteristic(characteristic_name, type_name)
        direction = "Saving" if save else "Loading"
        self.logger.debug(
            f"{direction} {type_name} '{characteristic.name}' @0x{characteristic.address:08x}"
        )
        return characteristic

    def characteristic_category(self, characteristic_name: str) -> str:
        """Get the category (type) of a characteristic.

        Args:
            characteristic_name: Name of the characteristic

        Returns:
            The category (type) of the characteristic

        Raises:
            ValueError: If the characteristic is not found
        """
        try:
            characteristic = Characteristic.get(self.session, characteristic_name)
        except ValueError:
            raise ValueError(
                f"Characteristic '{characteristic_name}' not found"
            ) from None
        return characteristic.type

    def _load_characteristic(
        self, characteristic_name: str, category: str
    ) -> Characteristic:
        """Load a characteristic by name and verify its type.

        Args:
            characteristic_name: Name of the characteristic to load
            category: Expected type of the characteristic

        Returns:
            The characteristic

        Raises:
            ValueError: If the characteristic is not found
            TypeError: If the characteristic is not of the expected type
        """
        try:
            characteristic = Characteristic.get(self.session, characteristic_name)
        except ValueError:
            raise ValueError(
                f"Characteristic '{characteristic_name}' not found"
            ) from None

        if characteristic.type != category:
            raise TypeError(
                f"Characteristic '{characteristic_name}' is not of type '{category}'"
            )

        return characteristic

    def get_axis_pts(self, axis_pts_name: str, save: bool = False) -> AxisPts:
        """Get axis points by name.

        Args:
            axis_pts_name: Name of the axis points to get
            save: Whether the axis points will be used for saving

        Returns:
            The axis points

        Raises:
            ValueError: If the axis points are not found
        """
        axis_pts = self._load_axis_pts(axis_pts_name)
        direction = "Saving" if save else "Loading"
        self.logger.debug(
            f"{direction} AXIS_PTS '{axis_pts.name}' @0x{axis_pts.address:08x}"
        )
        return axis_pts

    def _load_axis_pts(self, axis_pts_name: str) -> AxisPts:
        """Load axis points by name.

        Args:
            axis_pts_name: Name of the axis points to load

        Returns:
            The axis points

        Raises:
            ValueError: If the axis points are not found
        """
        try:
            axis_pts = AxisPts.get(self.session, axis_pts_name)
        except ValueError:
            raise ValueError(f"Axis points '{axis_pts_name}' not found") from None

        return axis_pts

    def byte_order(self, obj: Union[AxisPts, Characteristic]) -> ByteOrder:
        """Get byte-order for A2L element.

        Args:
            obj: The A2L element (AxisPts, Characteristic, etc.) to get byte order for

        Returns:
            ByteOrder: The byte order (BIG_ENDIAN or LITTLE_ENDIAN)
        """
        return (
            ByteOrder.BIG_ENDIAN
            if obj.byteOrder
            or self.mod_common.byteOrder in ("MSB_FIRST", "LITTLE_ENDIAN")
            else ByteOrder.LITTLE_ENDIAN
        )

    def update_record_layout(
        self, obj: Union[AxisPts, Characteristic]
    ) -> dict[tuple[str, str], int]:
        """Update record layout addresses based on actual element counts.

        This method reads the actual number of elements for axes and updates
        the addresses of subsequent elements accordingly.

        Args:
            obj: The object (AxisPts or Characteristic) to update record layout for

        Returns:
            Dictionary of patches applied to addresses
        """
        patches: dict[tuple[str, str], int] = {}
        components = obj.record_layout_components
        offset = 0

        # Process each position element
        for name, attr in components["position"]:
            # Apply offset from previous patches
            if offset:
                aligned_address = obj.record_layout.alignment.align(
                    attr.data_type, attr.address + offset
                )
                attr.address = aligned_address
                self.logger.debug(
                    f"Updating RecordLayout for {obj.name!r} / {obj.record_layout.name!r}:  -> [{aligned_address}]"
                )
            if name in ("no_axis_pts", "no_rescale"):
                info = components.get("axes").get(attr.axis)
                try:
                    value = self.image.read_numeric(
                        attr.address,
                        get_data_type(attr.data_type, self.byte_order(obj)),
                    )
                except InvalidAddressError as e:
                    value = None
                    self.logger.error(f"{obj.name!r}: {e}")
                else:
                    # Update actual element count and calculate patch if needed
                    info.actual_element_count = value
                    if value != info.maximum_element_count:
                        if name == "no_axis_pts":
                            patch_name = "axis_pts"
                        elif name == "no_rescale":
                            patch_name = "axis_rescale"
                        patches[(patch_name, attr.axis)] = (
                            value - info.maximum_element_count
                        )

            # Apply patches to axis points or rescale points
            elif name in ("axis_pts", "axis_rescale"):
                tmp = patches.pop((name, attr.axis), None)
                if tmp is not None:
                    offset += tmp

        return patches

    def read_axes_values(
        self, obj: Union[AxisPts, Characteristic], axis_name: Optional[str] = None
    ) -> dict[str, dict[str, Any]]:
        """Read axis values (not arrays) from memory.

        Args:
            obj: The object (AxisPts or Characteristic) to read axis values for
            axis_name: Optional name of a specific axis to read

        Returns:
            Dictionary of axis values by axis name and value name
        """
        # Update record layout to ensure addresses are correct
        self.update_record_layout(obj)

        # Initialize result dictionary
        result: dict[str, dict[str, Any]] = defaultdict(dict)

        # Get axes from record layout
        components = obj.record_layout_components
        axes = components.get("axes")

        # Process each axis
        for ax_name in axes.keys():
            axis_info = axes.get(ax_name)
            axis_elements = axis_info.elements

            # Process each element in the axis
            for name, attr in axis_elements.items():
                if name not in ("axis_pts", "axis_rescale"):
                    # Handle fixed number of axis points
                    if name == "fix_no_axis_pts":
                        value = attr.number
                    else:
                        # Read value from memory
                        try:
                            value = self.image.read_numeric(
                                attr.address,
                                get_data_type(attr.data_type, self.byte_order(obj)),
                            )
                        except InvalidAddressError as e:
                            value = None
                            self.logger.error(f"{obj.name!r} {ax_name}-axis: {e}")
                        else:
                            # Update actual element count for adjustable axes
                            if axis_info.adjustable:
                                if name == "no_axis_pts" or name == "no_rescale":
                                    axis_info.actual_element_count = value

                    # Store the value in the result
                    result[ax_name][name] = value

        # Return result for specific axis or all axes
        if axis_name is not None and result:
            return result[axis_name]
        else:
            return result

    def read_axes_arrays(
        self, obj: Union[AxisPts, Characteristic], axis_name: Optional[str] = None
    ) -> dict[str, dict[str, np.ndarray]]:
        """Read axis arrays from memory.

        Args:
            obj: The object (AxisPts or Characteristic) to read axis arrays for
            axis_name: Optional name of a specific axis to read

        Returns:
            Dictionary of axis arrays by axis name and array name
        """
        # Initialize result dictionary
        result: dict[str, dict[str, np.ndarray]] = defaultdict(dict)

        # Get axes from record layout
        components = obj.record_layout_components
        axes = components.get("axes")

        # Process each axis
        for ax_name in axes.keys():
            axis_info = axes.get(ax_name)
            number_of_elements = (
                axis_info.actual_element_count or axis_info.maximum_element_count
            )
            axis_elements = axis_info.elements
            # Process each element in the axis
            for name, attr in axis_elements.items():
                if name in ("axis_pts", "axis_rescale"):
                    # Double the number of elements for rescale points
                    if name == "axis_rescale":
                        number_of_elements = number_of_elements << 1

                    # Read array from memory
                    try:
                        values = self.image.read_ndarray(
                            attr.address,
                            length=number_of_elements * asam_type_size(attr.data_type),
                            dtype=get_data_type(attr.data_type, self.byte_order(obj)),
                        )
                    except InvalidAddressError as e:
                        values = np.array([])
                        self.logger.error(f"{obj.name!r} {ax_name}-axis: {e}")

                    # Store the array in the result
                    result[ax_name][name] = values

        # Return result for specific axis or all axes
        if axis_name is not None and result:
            return result[axis_name]
        else:
            return result

    def read_nd_array(
        self,
        axis_pts: AxisPts,
        axis_name: str,
        component_name: str,
        no_elements: int,
        shape: Optional[tuple[int, ...]] = None,
        order: Optional[str] = None,
    ) -> np.ndarray:
        """Read an n-dimensional array from memory.

        Args:
            axis_pts: The axis points to read from
            axis_name: Name of the axis
            component_name: Name of the component to read
            no_elements: Number of elements to read
            shape: Optional shape of the array
            order: Optional memory order ('C' or 'F')

        Returns:
            The read array
        """
        # Get axis information
        axis_info = axis_pts.record_layout_components["axes"].get(axis_name)
        data_type = axis_info.data_type
        component = axis_info.elements.get(component_name)
        address = component.address

        # Calculate length in bytes
        length = no_elements * asam_type_size(data_type)

        # Read array from memory
        np_arr = self.image.read_ndarray(
            addr=address,
            length=length,
            dtype=get_data_type(data_type, self.byte_order(axis_pts)),
            shape=shape,
            order=order,
        )

        return np_arr

    def write_nd_array(
        self,
        axis_pts: AxisPts,
        axis_name: str,
        component_name: str,
        np_arr: np.ndarray,
        order: Optional[str] = None,
    ) -> None:
        """Write an n-dimensional array to memory.

        Args:
            axis_pts: The axis points to write to
            axis_name: Name of the axis
            component_name: Name of the component to write
            np_arr: Array to write
            order: Optional memory order ('C' or 'F')
        """
        # Get axis and component information
        axes = axis_pts.record_layout_components.get("axes")
        axis = axes.get(axis_name)
        component = axis.elements[component_name]

        # Write array to memory
        self.image.write_ndarray(addr=component.address, array=np_arr, order=order)

    def is_numeric(self, compu_method: CompuMethod) -> bool:
        """Check if a computation method produces numeric values.

        Args:
            compu_method: The computation method to check

        Returns:
            True if the computation method produces numeric values, False otherwise
        """
        return (
            compu_method == "NO_COMPU_METHOD"
            or compu_method.conversionType != "TAB_VERB"
        )


class OnlineCalibration(Calibration):
    """Calibration class for online calibration via XCP.

    This class provides methods for calibrating ECUs via XCP protocol.
    """

    __slots__ = "xcp_master"

    def __init__(self, xcp_master: Any) -> None:
        """Initialize the OnlineCalibration object.

        Args:
            xcp_master: XCP master object for communication with the ECU
        """
        self.xcp_master = xcp_master


class OfflineCalibration(Calibration):
    """Calibration class for offline calibration via hex files.

    This class provides methods for calibrating hex files.
    """

    __slots__ = ("hexfile_name", "hexfile_type")

    def __init__(
        self,
        a2l_db: DB,
        image: Image,
        hexfile_name: Optional[str] = None,
        hexfile_type: Optional[str] = None,
        loglevel: str = "WARN",
    ) -> None:
        """Initialize the OfflineCalibration object.

        Args:
            a2l_db: A2L database
            image: Memory image containing calibration data
            hexfile_name: Optional name of the hex file
            hexfile_type: Optional type of the hex file
            loglevel: Logging level
        """
        parameter_chache = ParameterCache()
        super().__init__(a2l_db, image, parameter_chache, Logger(loglevel))
        self.hexfile_name = hexfile_name
        self.hexfile_type = hexfile_type
