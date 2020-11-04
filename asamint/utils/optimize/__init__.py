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
    prev_section = McObject()
    while values:
        section = values.pop(0)
        if section.address == prev_section.address + prev_section.length and result_sections:
            last_segment = result_sections[-1]
            last_segment.length += section.length
        else:
            # Create a new section.
            result_sections.append(McObject(address = section.address, length = section.length))
        prev_section = section
    return result_sections
