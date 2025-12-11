#!/usr/bin/env python
"""Model representing calibration data."""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

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
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

import numpy as np
from sqlalchemy.ext.associationproxy import (_AssociationDict,
                                             _AssociationList, _AssociationSet)

# numpy.seterr(all=None, divide=None, over=None, under=None, invalid=None)
np.seterr(divide="raise")


class JSONEncoder(json.JSONEncoder):
    """JSON serializer for the following dataclasses."""

    def default(self, o):
        if is_dataclass(o):
            try:
                result = o.asdict()
            except Exception as e:
                print(f"asdict: {e!r} ==> {type(o)}")
                return b""
            else:
                return result
        elif isinstance(o, datetime):
            return o.isoformat()
        elif isinstance(o, np.ndarray):
            return o.tolist()
        elif isinstance(o, _AssociationList):
            return list(o)
        elif isinstance(o, _AssociationSet):
            return set(o)
        elif isinstance(o, _AssociationDict):
            return dict(o)
        elif isinstance(o, UUID):
            return str(o)
        else:
            try:
                data = super().default(o)
            except Exception as e:
                print(f"JSONEncoder: {e!r} ==> {type(o)}")
                data = ""
        return data


def dump_characteristics(chs) -> bytes:
    """JSON representation of characteristic values."""
    return json.dumps(
        chs, cls=JSONEncoder, indent=4, separators=(",", ": "), ensure_ascii=False
    ).encode("utf-8")


@dataclass(kw_only=True)
class CalibratedObject:
    name: str
    comment: str
    category: str
    _raw: np.ndarray
    _phys: np.ndarray
    displayIdentifier: Optional[str] = None
    unit: Optional[str] = None  # vereinheitlicht: überall verfügbar
    fnc_unit: Optional[str] = None  # für Funktionswerte-Container
    axes: list[dict] | None = None
    is_numeric: bool | None = None
    shape: tuple[int, ...] | None = None
    api: Optional[Any] = None
    _characteristic: Optional[Any] = None

    @property
    def raw(self):
        return self._raw

    @raw.setter
    def raw(self, value):
        self._raw = np.asarray(value)
        if self.api and self._characteristic is not None:
            self._phys = self.api.int_to_physical(self._characteristic, self._raw)

    @property
    def phys(self):
        return self._phys

    @phys.setter
    def phys(self, value):
        self._phys = np.asarray(value)
        if self.api and self._characteristic is not None:
            self._raw = self.api.physical_to_int(self._characteristic, self._phys)

    def asdict(self):
        """Custom asdict that ??? fields."""
        result = {}
        for k in self.__dataclass_fields__.keys():
            if k in ("api", "_characteristic", "fnc_unit"):
                continue
            value = getattr(self, k)
            if isinstance(value, AxisContainer):
                result[k] = asdict(value)
            else:
                if k.startswith("_"):
                    k = k[1:]
                result[k] = value
        return result


# Vereinheitlichte Ableitungen verwenden CalibratedObject ohne redundante Felder
@dataclass
class Ascii(CalibratedObject):
    pass


@dataclass
class AxisPts(CalibratedObject):
    paired: bool | None = None
    reversed_storage: bool | None = None


@dataclass
class Cube4(CalibratedObject):
    """Represents a 4D cube characteristic."""

    fnc_unit: str
    axes: list[dict]
    is_numeric: bool


@dataclass
class Cube5(CalibratedObject):
    """Represents a 5D cube characteristic."""

    fnc_unit: str
    axes: list[dict]
    is_numeric: bool


@dataclass
class Cuboid(CalibratedObject):
    """Represents a cuboid characteristic."""

    fnc_unit: str
    axes: list[dict]
    is_numeric: bool


@dataclass
class Curve(CalibratedObject):
    """Represents a curve characteristic."""

    fnc_unit: str
    axes: list[dict]
    is_numeric: bool


@dataclass
class Map(CalibratedObject):
    """Represents a map characteristic."""

    fnc_unit: str
    axes: list[dict]
    is_numeric: bool


@dataclass
class NDimContainer(CalibratedObject):
    # Ein Container-Typ für CURVE, MAP, CUBOID, CUBE_4, CUBE_5, VAL_BLK
    pass


@dataclass
class Value(CalibratedObject):
    pass


# Reduzierung: ValueBlock wird von NDimContainer abgedeckt, alias für Abwärtskompatibilität
ValueBlock = NDimContainer


# AxisContainer bleibt, aber vereinheitlichte Typen
@dataclass
class AxisContainer:
    name: str
    input_quantity: str
    category: str
    unit: str | None
    raw: list[Union[int, float]]
    phys: list[Union[int, float]]
    reversed_storage: bool = field(default=False)
    axis_pts_ref: Union[str, None] = field(default=None)
    is_numeric: bool = field(default=True)

    def asdict(self):
        return asdict(self)


def get_calibration_class(name: str):
    mapping = {
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


class MemoryType(IntEnum):
    AXIS_PTS = 0
    VALUE = 1
    ASCII = 3
    VAL_BLK = 4
    CURVE = 5
    MAP = 6
    CUBOID = 7


@dataclass
class MemoryObject:
    memory_type: MemoryType
    name: str
    address: int
    length: int
