#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Optimize data-structures like memory sections."""

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

from itertools import groupby
from operator import attrgetter

class McObject:
    """Measurement and Calibration objects have an address and a length.

    Used as input for optimization algorithms.
    """

    def __init__(self, name = "", address = 0, length = 0):
        self.name = name
        self.address = address
        self.length = length

    def __repr__(self):
        return 'McObject(name = "{}", address = 0x{:08x}, length = {})'.format(self.name, self.address, self.length)

    def __eq__(self, other):
        return self.address == other.address and self.length == other.length

def make_continuous_blocks(chunks):
    """Try to make continous blocks from a list of small, unordered `chunks`.

    Parameters
    ----------
    chunks: list of `McObject`

    Returns
    -------
    sorted list of `McObject`
    """

    # Objects can share addresses, for instance MEASUREMENTs with different COMPU_METHODs.
    values = []
    # 1. Groupy by address.
    for key, value in groupby(sorted(chunks, key = attrgetter("address")), key = attrgetter("address")):
        # 2. Pick the largest one.
        values.append(max(value, key = attrgetter("length")))
    result_sections = []
    last_section = None
    while values:
        section = values.pop(0)
        if last_section and section.address <= last_section.address + last_section.length:
            last_end = last_section.address + last_section.length - 1
            current_end = section.address + section.length - 1
            if last_end > section.address:
                pass
            else:
                last_section.length += current_end - last_end
        else:
            # Create a new section.
            result_sections.append(McObject(address = section.address, length = section.length))
        last_section = result_sections[-1]
    return result_sections
