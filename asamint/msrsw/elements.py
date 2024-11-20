#!/usr/bin/env python
"""Dataclass equivalents to MSRSW-XML elements.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2024 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import typing
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ShortName:
    value: str | None


@dataclass
class LongName:
    value: str | None


@dataclass
class DisplayName:
    value: str | None


@dataclass
class Category:
    value: str | None


@dataclass
class UnitDisplayName:
    value: str | None


@dataclass
class ModelLink:
    value: str | None


@dataclass
class V:
    value: int | float


@dataclass
class VF:
    value: float


@dataclass
class VT:
    value: str


@dataclass
class VH:
    value: str


@dataclass
class VG:
    label: str = ""
    values: list[V | VF | VT] = field(default_factory=list)


@dataclass
class A2LFunction:
    name: str = ""


@dataclass
class A2LGroup:
    name: str = ""


@dataclass
class InstanceRef:
    name: str = ""


@dataclass
class CriterionRef:
    name: str | None


@dataclass
class CriterionValue:
    criterion_ref: CriterionRef
    vt: VT


@dataclass
class ArraySize:
    dimensions: tuple[int]


@dataclass
class ArrayIndex:
    value: int


@dataclass
class ValueContainer:
    unit_display_name: UnitDisplayName
    array_size: ArraySize
    values: VG


@dataclass
class AxisContainer:
    category: Category
    unit_display_name: UnitDisplayName
    array_size: ArraySize
    values: VG
    instance_ref: InstanceRef


@dataclass
class P:
    value: str


@dataclass
class Remark:
    values: list[P]


@dataclass
class HistoryEntry:
    state: str | None = None
    date: datetime | None = None
    csus: str | None = None
    cspr: str | None = None
    cswp: str | None = None
    csto: str | None = None
    cstv: str | None = None
    cspi: str | None = None
    csdi: str | None = None
    remark: Remark | None = None


@dataclass
class Flags:
    category: Category
    flag: bool
    csus: str
    date: datetime
    remark: Remark


@dataclass
class InstancePropsVariant:
    criterion_values: list[CriterionValue]
    value_container: ValueContainer
    axis_containers: AxisContainer
    history: list[HistoryEntry]
    flags: Flags


@dataclass
class Instance:
    shortname: ShortName
    array_index: ArrayIndex
    longname: LongName
    displayname: DisplayName
    category: Category
    feature_ref: A2LFunction
    value_container: ValueContainer
    axis_containers: AxisContainer
    history: list[HistoryEntry]
    flags: Flags | None
    model_link: ModelLink
    variants: list[InstancePropsVariant]
    children: list[typing.Any]
