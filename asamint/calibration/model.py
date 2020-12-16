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
    """
    """

    PROPERTIES = ("name", "comment", "category", "displayIdentifier")

    def __init__(self, **kws):
        for obj in (BaseCharacteristic, self):
            for k in obj.PROPERTIES:
                v = kws.pop(k)
                setattr(self, k, v)

    def __str__(self):
        result = []
        result.append("{}(".format(self.__class__.__name__))
        result.append(''.join("{} = '{}', ".format(k, v) for k,v in self._props(BaseCharacteristic)))
        result.append(''.join("{} = '{}', ".format(k, v) for k,v in self._props(self)))
        result.append(")")
        return ''.join(result)

    def _props(self, obj):
        result = []
        for k in obj.PROPERTIES:
            value = getattr(self, k)
            result.append((k, value, ))
        return result

    __repr__ = __str__


class Ascii(BaseCharacteristic):
    """
    """
    PROPERTIES = ("length", "value")


class AxisPts(BaseCharacteristic):
    """
    """
    PROPERTIES = ("raw_values", "converted_values", "paired", "unit")


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


class Cube4(BaseCharacteristic):
    """
    """


class Cube5(BaseCharacteristic):
    """
    """


class Cuboid(BaseCharacteristic):
    """
    """


class Curve(BaseCharacteristic):
    """
    """
    PROPERTIES = (
        "raw_fnc_values", "converted_fnc_values", "x_axis_unit", "fnc_unit",
        "curve_axis_ref", "axis_pts_ref", "raw_axis_values", "converted_axis_values"
    )


class Map(BaseCharacteristic):
    """
    """


class Value(BaseCharacteristic):
    """
    """
    PROPERTIES = ("raw_value", "converted_value", "unit")


class ValueBlock(BaseCharacteristic):
    """
    """
    PROPERTIES = ("raw_values", "converted_values", "shape", "unit")


class AxisContainer:
    """
    """

    def __init__(self):
        pass
