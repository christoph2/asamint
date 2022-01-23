#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Model representing calibration data.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020 by Christoph Schueler <cpu12.gems.googlemail.com>

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


class BaseCharacteristic:
    """ """

    PROPERTIES = ("name", "comment", "category", "displayIdentifier")

    def __init__(self, **kws):
        for obj in (BaseCharacteristic, self):
            for k in obj.PROPERTIES:
                v = kws.pop(k)
                setattr(self, k, v)

    def __str__(self):
        result = []
        result.append("{}(".format(self.__class__.__name__))
        result.append(
            "".join(
                "{} = '{}', ".format(k, v) for k, v in self._props(BaseCharacteristic)
            )
        )
        result.append("".join("{} = '{}', ".format(k, v) for k, v in self._props(self)))
        result.append(")")
        return "".join(result)

    def _props(self, obj):
        result = []
        for k in obj.PROPERTIES:
            value = getattr(self, k)
            result.append(
                (
                    k,
                    value,
                )
            )
        return result

    __repr__ = __str__


class NDimContainer(BaseCharacteristic):
    """ """

    PROPERTIES = ("raw_values", "converted_values", "fnc_unit", "axes")


class Ascii(BaseCharacteristic):
    """ """

    PROPERTIES = ("length", "value")


class AxisPts(BaseCharacteristic):
    """ """

    PROPERTIES = (
        "raw_values",
        "converted_values",
        "paired",
        "unit",
        "reversed_storage",
    )

    @property
    def axis_points_raw(self):
        if self.paired:
            self.raw_values[0::2]
        else:
            return None

    @property
    def virtual_axis_points_raw(self):
        if self.paired:
            self.raw_values[1::2]
        else:
            return None

    @property
    def axis_points_converted(self):
        if self.paired:
            self.converted_values[0::2]
        else:
            return None

    @property
    def virtual_axis_points_converted(self):
        if self.paired:
            self.converted_values[1::2]
        else:
            return None


class Cube4(NDimContainer):
    """ """


class Cube5(NDimContainer):
    """ """


class Cuboid(NDimContainer):
    """ """


class Curve(NDimContainer):
    """ """


class Map(NDimContainer):
    """ """


class Value(BaseCharacteristic):
    """ """

    PROPERTIES = ("raw_value", "converted_value", "unit")


class ValueBlock(BaseCharacteristic):
    """ """

    PROPERTIES = ("raw_values", "converted_values", "shape", "unit")


class AxisContainer:
    """ """

    def __init__(
        self,
        category: str,
        unit: str,
        raw_values,
        converted_values,
        reversed_storage=False,
        axis_pts_ref=None,
        curve_axis_ref=None,
    ):
        self.category = category
        self.unit = unit
        self.raw_values = raw_values
        self.converted_values = converted_values
        self.reversed_storage = reversed_storage
        self.axis_pts_ref = axis_pts_ref
        self.curve_axis_ref = curve_axis_ref

    def __str__(self):
        return """
AxisContainer {{
    category            = "{}";
    unit                = "{}";
    reversed_storage    = {};
    raw_values          = {};
    converted_values    = {};
    axis_pts_ref        = {};
    curve_axis_ref      = {};
}}""".format(
            self.category,
            self.unit,
            self.reversed_storage,
            self.raw_values,
            self.converted_values,
            self.axis_pts_ref,
            self.curve_axis_ref,
        )

    __repr__ = __str__


def get_calibration_class(name: str):
    """ """
    return {
        "ASCII": Ascii,
        "AXIS_PTS": AxisPts,
        "CUBE4": Cube4,
        "CUBE5": Cube5,
        "CUBOID": Cuboid,
        "CURVE": Curve,
        "MAP": Map,
        "VALUE": Value,
        "VAL_BLK": ValueBlock,
    }.get(name)
