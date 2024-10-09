#!/usr/bin/env python
"""Optimize data-structures like memory sections."""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2022 by Christoph Schueler <cpu12.gems.googlemail.com>

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

from collections import defaultdict, namedtuple
from dataclasses import dataclass, field
from itertools import groupby
from operator import attrgetter
from typing import Dict, List, Tuple, Union

from sortedcontainers import SortedListWithKey


def sort_by_address_and_ext(e):
    return (
        e[0].ext,
        e[0].address,
    )


OdtEntry = namedtuple("OdtEntry", "odt_idx, odt_entry_idx, offset")


class DaqList:
    """ """

    def __init__(self, odts, measurement_summary):
        self.odts = odts
        self.measurement_summary = measurement_summary
        adl = SortedListWithKey(key=sort_by_address_and_ext)
        for odt_idx, odt in enumerate(odts):
            for odt_entry_idx, odt_entry in enumerate(odt):
                adl.add((odt_entry, odt_idx, odt_entry_idx))
        # print(adl)
        self.adl = adl
        flo = []
        for name, address, ext, datatype, typesize, cm in measurement_summary:
            res = self.find(address, ext)
            print(name, hex(address), datatype, typesize, cm, res)
            flo.append((name, hex(address), datatype, typesize, cm, res))

    def find(self, address, ext=0):
        """ """
        last_idx = len(self.adl) - 1
        idx = self.adl.bisect_key((ext, address)) - 1
        if idx < 0 or idx > last_idx:
            return None
        else:
            entry, odt_idx, odt_entry_idx = self.adl[idx]
            if entry.ext != ext:
                return None
            if entry.address <= address < entry.address + entry.length:
                offset = address - entry.address
                return (odt_idx, odt_entry_idx, offset)
            else:
                return None


@dataclass(init=True, repr=True, eq=True)
class McObject:
    """Measurement and Calibration objects have an address, address-extension, and a length.

    Used as input for optimization algorithms.
    """

    name: str
    address: int
    ext: int = 0
    length: int = 0

    def __post_init__(self):
        if self.length <= 0:
            raise ValueError("length must be positive")

    def __contains__(self, address: int, ext: int = 0) -> bool:
        return (self.ext == ext) and (
            self.address <= address < self.address + self.length
        )

    """
    def index(self, address: int) -> int:
        if address not in self:
            raise ValueError("0x{:08x} is not in address range.".format(address))
        else:
            return address - self.address
    """


def make_continuous_blocks(
    chunks: List[McObject], upper_bound=None, upper_bound_initial=None
) -> List[McObject]:
    """Try to make continous blocks from a list of small, unordered `chunks`.

    Parameters
    ----------
    chunks: list of `McObject`

    Returns
    -------
    sorted list of `McObject`
    """

    KEY = lambda x: (x.ext, x.address)

    values = []
    # 1. Groupy by address.
    for key, value in groupby(sorted(chunks, key=KEY), key=KEY):
        # 2. Pick the largest one.
        values.append(max(value, key=attrgetter("length")))
    result_sections = []
    last_section = None
    last_ext = None
    while values:
        section = values.pop(0)
        if (
            last_section
            and section.address <= last_section.address + last_section.length
        ) and not (section.ext != last_ext):
            last_end = last_section.address + last_section.length - 1
            current_end = section.address + section.length - 1
            if last_end > section.address:
                pass
            else:
                offset = current_end - last_end
                if upper_bound:
                    if last_section.length + offset <= upper_bound:
                        last_section.length += offset
                    else:
                        result_sections.append(
                            McObject(
                                name="",
                                address=section.address,
                                ext=section.ext,
                                length=section.length,
                            )
                        )
                else:
                    last_section.length += offset
        else:
            # Create a new section.
            result_sections.append(
                McObject(
                    name="",
                    address=section.address,
                    ext=section.ext,
                    length=section.length,
                )
            )
        last_section = result_sections[-1]
        last_ext = last_section.ext
    return result_sections
