#!/usr/bin/env python
"""Bin-packing algorithms.

Used for instance to optimally assign measurements to ODTs.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2021 by Christoph Schueler <cpu12.gems.googlemail.com>

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

from typing import List


class Bin:
    """ """

    def __init__(self, size):
        self.size = size
        self.residual_capacity = size
        self.entries = []

    def append(self, entry):
        self.entries.append(entry)

    @property
    def __len__(self) -> int:
        return len(self.entries)

    def __eq__(self, other) -> bool:
        return self.residual_capacity == other.residual_capacity and self.entries == other.entries

    def __str__(self) -> str:
        return f"Bin(residual_capacity: {self.residual_capacity}  entries: {self.entries})"

    __repr__ = __str__


def first_fit_decreasing(items, bin_size: int) -> List[Bin]:
    """bin-packing with first-fit-decreasing algorithm.

    Parameters
    ----------
    items: list
        items that need to be stored/allocated.

    bin_size: int

    Returns
    -------
    list
        Resulting bins
    """
    bins = [Bin(size=bin_size)]  # Initial bin
    for item in sorted(items, key=lambda x: x.length, reverse=True):
        for bin in bins:
            if bin.residual_capacity >= item.length:
                bin.append(item)
                bin.residual_capacity -= item.length
                break
        else:
            new_bin = Bin(size=bin_size)
            bins.append(new_bin)
            new_bin.append(item)
            new_bin.residual_capacity -= item.length
    return bins
