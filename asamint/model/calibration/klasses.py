#!/usr/bin/env python
"""Model representing calibration data.
"""

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
from typing import Union
from uuid import UUID

import numpy as np
from sqlalchemy.ext.associationproxy import (
    _AssociationDict,
    _AssociationList,
    _AssociationSet,
)


# numpy.seterr(all=None, divide=None, over=None, under=None, invalid=None)
np.seterr(divide="raise")


class JSONEncoder(json.JSONEncoder):
    """JSON serializer for the following dataclasses."""

    def default(self, o):
        if is_dataclass(o):
            return asdict(o)
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
    return json.dumps(chs, cls=JSONEncoder, indent=4, separators=(",", ": "), ensure_ascii=False).encode("utf-8")


@dataclass
class BaseCharacteristic:
    """ """

    name: str
    comment: str
    category: str
    displayIdentifier: str


@dataclass
class NDimContainer(BaseCharacteristic):
    """ """

    raw: list[Union[int, float]]
    phys: list[Union[int, float]]
    fnc_unit: str
    axes: list
    is_numeric: bool


@dataclass
class Ascii(BaseCharacteristic):
    """ """

    length: int
    phys: str


@dataclass
class AxisPts(BaseCharacteristic):
    """ """

    raw: list[Union[int, float]]
    phys: list[Union[int, float]]
    paired: bool
    unit: str
    reversed_storage: bool
    is_numeric: bool

    @property
    def axis_points_raw(self):
        if self.paired:
            self.raw[0::2]
        else:
            return None

    @property
    def virtual_axis_points_raw(self):
        if self.paired:
            self.raw[1::2]
        else:
            return None

    @property
    def axis_points_converted(self):
        if self.paired:
            self.phys[0::2]
        else:
            return None

    @property
    def virtual_axis_points_converted(self):
        if self.paired:
            self.phys[1::2]
        else:
            return None


@dataclass
class Cube4(NDimContainer):
    """ """


@dataclass
class Cube5(NDimContainer):
    """ """


@dataclass
class Cuboid(NDimContainer):
    """ """


@dataclass
class Curve(NDimContainer):
    """ """


@dataclass
class Map(NDimContainer):
    """ """


@dataclass
class Value(BaseCharacteristic):
    """ """

    raw: Union[int, float]
    phys: Union[int, float]
    unit: str
    is_numeric: bool = field(default=True)


@dataclass
class ValueBlock(BaseCharacteristic):
    """ """

    raw: list[Union[int, float]]
    phys: list[Union[int, float]]
    shape: list[int]
    unit: str
    is_numeric: bool = field(default=True)


@dataclass
class AxisContainer:
    """ """

    name: str
    input_quantity: str
    category: str
    unit: str
    raw: list[Union[int, float]]
    phys: list[Union[int, float]]
    reversed_storage: bool = field(default=False)
    axis_pts_ref: Union[str, None] = field(default=None)
    is_numeric: bool = field(default=True)


def get_calibration_class(name: str):
    """ """
    return {
        "ASCII": Ascii,
        "AXIS_PTS": AxisPts,
        "CUBE_4": Cube4,
        "CUBE_5": Cube5,
        "CUBOID": Cuboid,
        "CURVE": Curve,
        "MAP": Map,
        "VALUE": Value,
        "VAL_BLK": ValueBlock,
    }.get(name)


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
