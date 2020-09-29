#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

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


class Bin:
    """

    """

    def __init__(self, size = MAX_ODT_ENTRY_SIZE):
        self.size = size
        self.residual_capacity = size   # initial Bin is empty
        self.entries = []

    def append(self, entry):
        self.entries.append(entry)

    def __eq__(self, other):
        self.residual_capacity == other.residual_capacity

    def __lt__(self, other):
        self.residual_capacity < other.residual_capacity

    def __str__(self):
        return "Bin(residual_capacity: {}  entries: {})".format(self.residual_capacity, self.entries)

    __repr__ = __str__


def first_fit_decreasing(items, bin_size):
    """Solve the classic bin-packing problem with first-fit-decreasing algorithm.

    Parameters
    ----------
    items: dict
        items that need to be stored/allocated.

    bin_size: int

    Returns
    -------
    """
    bins = [Bin(size = bin_size)]   # Initial bin
    missing = []
    for key, size in sorted(items.items(), key = lambda x: x[1], reverse = True):
        #print(key, size)
        for bin in bins:
            if bin.residual_capacity >= size:
                bin.append(key)
                bin.residual_capacity -= size
                break
        else:
            new_bin = Bin(size = bin_size)
            bins.append(new_bin)
            new_bin.append(key)
            new_bin.residual_capacity -= size
    return bins


#result = first_fit_decreasing(TO_ALLOCATE, MAX_ODT_ENTRY_SIZE)
#print(result, len(result))

