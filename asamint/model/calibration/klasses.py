#!/usr/bin/env python
"""Model representing calibration data.

Provides dataclass-based DTOs for all calibration parameter types
(scalars, curves, maps, cubes) as well as axis containers, memory
objects, and JSON serialisation helpers.
"""

from __future__ import annotations

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2026 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import json
import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy.ext.associationproxy import (
    _AssociationDict,
    _AssociationList,
    _AssociationSet,
)


def enable_strict_float_errors() -> None:
    """Configure numpy to raise on divide-by-zero.

    Call this explicitly where needed rather than relying on a
    module-level side-effect.
    """
    np.seterr(divide="raise")


# Apply at import time for backward compatibility; callers may also invoke
# ``enable_strict_float_errors()`` explicitly after resetting numpy state.
enable_strict_float_errors()

logger = logging.getLogger(__name__)


class JSONEncoder(json.JSONEncoder):
    """JSON serialiser for calibration dataclasses, numpy arrays, and UUIDs."""

    _SIMPLE_TYPES: dict[type, Any] = {
        datetime: lambda o: o.isoformat(),
        np.ndarray: lambda o: o.tolist(),
        np.integer: int,
        np.floating: float,
        _AssociationList: list,
        _AssociationSet: list,
        _AssociationDict: dict,
        UUID: str,
    }

    def default(self, o: object) -> Any:
        """Serialise non-standard types.

        Args:
            o: Object to serialise.

        Returns:
            JSON-compatible representation.

        Raises:
            TypeError: If *o* cannot be serialised by any known handler.
        """
        if is_dataclass(o) and not isinstance(o, type):
            return o.asdict() if hasattr(o, "asdict") else asdict(o)
        for cls, converter in self._SIMPLE_TYPES.items():
            if isinstance(o, cls):
                return converter(o)
        return super().default(o)


def dump_characteristics(chs: dict[str, dict[str, Any]]) -> bytes:
    """JSON representation of characteristic values.

    Args:
        chs: Nested parameter dictionary keyed by category then name.

    Returns:
        UTF-8 encoded JSON bytes.
    """
    return json.dumps(
        chs, cls=JSONEncoder, indent=4, separators=(",", ": "), ensure_ascii=False
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Calibration data classes
# ---------------------------------------------------------------------------


@dataclass(kw_only=True)
class CalibratedObject:
    """Base dataclass for all calibration parameter types.

    Properties ``raw`` and ``phys`` auto-synchronise via the attached
    ``api`` / ``_characteristic`` when both are set.
    """

    name: str
    comment: str
    category: str
    _raw: np.ndarray
    _phys: np.ndarray
    displayIdentifier: str | None = None
    unit: str | None = None
    fnc_unit: str | None = None
    axes: list[AxisContainer] | None = None
    is_numeric: bool | None = None
    shape: tuple[int, ...] | None = None
    api: Any = None
    _characteristic: Any = None

    @property
    def raw(self) -> np.ndarray:
        """Internal (raw/ECU) representation of the parameter."""
        return self._raw

    @raw.setter
    def raw(self, value: np.ndarray | list[int | float]) -> None:
        self._raw = np.asarray(value)
        if self.api and self._characteristic is not None:
            self._phys = self.api.int_to_physical(self._characteristic, self._raw)

    @property
    def phys(self) -> np.ndarray:
        """Physical (engineering-unit) representation of the parameter."""
        return self._phys

    @phys.setter
    def phys(self, value: np.ndarray | list[int | float]) -> None:
        self._phys = np.asarray(value)
        if self.api and self._characteristic is not None:
            self._raw = self.api.physical_to_int(self._characteristic, self._phys)

    def asdict(self) -> dict[str, Any]:
        """Serialise to a plain dict, omitting internal/transient fields.

        Fields ``api``, ``_characteristic``, and ``fnc_unit`` are excluded.
        Leading underscores are stripped from key names (``_raw`` → ``raw``).

        Returns:
            Flat dictionary suitable for JSON serialisation.
        """
        result: dict[str, Any] = {}
        for key in self.__dataclass_fields__:
            if key in ("api", "_characteristic", "fnc_unit"):
                continue
            value = getattr(self, key)
            if isinstance(value, AxisContainer):
                result[key] = asdict(value)
            elif isinstance(value, list) and value and isinstance(value[0], AxisContainer):
                result[key] = [asdict(v) for v in value]
            else:
                output_key = key.lstrip("_") if key.startswith("_") else key
                result[output_key] = value
        return result


# Vereinheitlichte Ableitungen verwenden CalibratedObject ohne redundante Felder
@dataclass
class Ascii(CalibratedObject):
    """ASCII string characteristic."""


@dataclass
class AxisPts(CalibratedObject):
    """Axis-points characteristic.

    Attributes:
        reversed_storage: Whether the axis is stored in reversed order.
    """

    reversed_storage: bool | None = None


@dataclass
class Cube4(CalibratedObject):
    """4-dimensional cube characteristic."""


@dataclass
class Cube5(CalibratedObject):
    """5-dimensional cube characteristic."""


@dataclass
class Cuboid(CalibratedObject):
    """3-dimensional cuboid characteristic."""


@dataclass
class Curve(CalibratedObject):
    """1-dimensional curve characteristic."""


@dataclass
class Map(CalibratedObject):
    """2-dimensional map characteristic."""


@dataclass
class NDimContainer(CalibratedObject):
    """Generic n-dimensional container (CURVE, MAP, CUBOID, CUBE_4, CUBE_5, VAL_BLK)."""


@dataclass
class Value(CalibratedObject):
    """Scalar value characteristic."""


# Backward-compatible alias.
ValueBlock = NDimContainer


@dataclass(slots=True)
class AxisContainer:
    """Axis data for a CURVE, MAP, or higher-dimensional characteristic.

    Attributes:
        name: Axis short-name.
        input_quantity: Input quantity reference from the A2L description.
        category: Axis category (``STD_AXIS``, ``COM_AXIS``, ``FIX_AXIS``,
            ``CURVE_AXIS``, ``RES_AXIS``).
        unit: Engineering unit string.
        raw: Raw (ECU-internal) axis values.
        phys: Physical (engineering-unit) axis values.
        reversed_storage: Whether axis values are stored in reverse order.
        axis_pts_ref: Reference to a shared AXIS_PTS entry (for COM_AXIS,
            RES_AXIS, CURVE_AXIS).
        is_numeric: ``True`` when axis values are numeric, ``False`` for
            verbal/text axes.
    """

    name: str
    input_quantity: str
    category: str
    unit: str | None
    raw: list[int | float]
    phys: list[int | float]
    reversed_storage: bool = field(default=False)
    axis_pts_ref: str | None = field(default=None)
    is_numeric: bool = field(default=True)

    def asdict(self) -> dict[str, Any]:
        """Return a plain-dict representation suitable for JSON."""
        return asdict(self)


def get_calibration_class(name: str) -> type[CalibratedObject] | None:
    """Look up the dataclass type for a calibration category name.

    Args:
        name: Category string (``"VALUE"``, ``"CURVE"``, ``"MAP"``, …).

    Returns:
        Corresponding dataclass type, or ``None`` for unknown categories.
    """
    mapping: dict[str, type[CalibratedObject]] = {
        "ASCII": Ascii,
        "AXIS_PTS": AxisPts,
        "CURVE": NDimContainer,
        "MAP": NDimContainer,
        "CUBOID": NDimContainer,
        "CUBE_4": NDimContainer,
        "CUBE_5": NDimContainer,
        "VALUE": Value,
        "VAL_BLK": NDimContainer,
    }
    return mapping.get(name)


# ---------------------------------------------------------------------------
# Memory layout helpers
# ---------------------------------------------------------------------------


class MemoryType(IntEnum):
    """Memory object category used in address-map reporting."""

    AXIS_PTS = 0
    VALUE = 1
    ASCII = 3
    VAL_BLK = 4
    CURVE = 5
    MAP = 6
    CUBOID = 7


@dataclass(slots=True)
class MemoryObject:
    """Descriptor for a contiguous ECU memory region.

    Attributes:
        memory_type: Category of calibration object occupying the region.
        name: Short-name of the calibration parameter.
        address: Start address in ECU memory.
        length: Region length in bytes.
    """

    memory_type: MemoryType
    name: str
    address: int
    length: int
