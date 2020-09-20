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
__author__ = 'Christoph Schueler'


from collections import namedtuple
from io import StringIO
from enum import IntEnum
import logging
from operator import attrgetter

from pprint import pprint

import pkgutil

from asamint.utils import cond_create_directories
from asamint.config import Configuration
from pya2l import DB


class AsamBaseType:
    """
    Parameters
    ----------

    Note: if `mdf_filename` is None, automatic filename generation kicks in and the file gets written
    to `measurements/` sub-directory.

    The other consequence is ...

    Also note the consequences:
        - Filename generation means always create a new file.
        - If `mdf_filename` is not None, **always overwrite** file.
    """

    PROJECT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "LOGLEVEL":                 (str,    False,  "WARN"),
        "A2L_FILE":                 (str,    True,   ""),
    }

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
    }

    def __init__(self, project_config = None, experiment_config = None, *args, **kws):
        self.project_config = Configuration(self.__class__.PROJECT_PARAMETER_MAP or {}, project_config or {})
        self.experiment_config = Configuration(self.__class__.EXPERIMENT_PARAMETER_MAP or {}, experiment_config or {})
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(self.project_config.get("LOGLEVEL"))
        db = DB()
        self._session_obj = db.open_create(self.project_config.get("A2L_FILE"))
        cond_create_directories()
        self.on_init(*args, **kws)

    def on_init(self, *args, **kws):
        raise NotImplementedError()


class MCObject:

    def __init__(self, name = "", address = 0, length = 0):
        self.name = name
        self.address = address
        self.length = length

    def __repr__(self):
        return 'MCObject(name = "{}", address = 0x{:08x}, length = {})'.format(self.name, self.address, self.length)


TYPE_SIZES = {
    "UBYTE":        1,
    "SBYTE":        1,
    "UWORD":        2,
    "SWORD":        2,
    "ULONG":        4,
    "SLONG":        4,
    "A_UINT64":     8,
    "A_INT64":      8,
    "FLOAT32_IEEE": 4,
    "FLOAT64_IEEE": 8,
}

OJ_READERS = {
    "UBYTE":           ("uint8_le",     "uint8_be"),
    "SBYTE":           ("int8_le",      "int8_be"),
    "UWORD":           ("uint16_le",    "uint16_be"),
    "SWORD":           ("int16_le",     "int16_be"),
    "ULONG":           ("uint32_le",    "uint32_be"),
    "SLONG":           ("int32_le",     "int32_be"),
    "A_UINT64":        ("uint64_le",    "uint64_be"),
    "A_INT64":         ("int64_le",     "int64_be"),
    "FLOAT32_IEEE":    ("float32_le",   "float32_be"),
    "FLOAT64_IEEE":    ("float64_le",   "float64_be"),
}

class ByteOrder(IntEnum):
    LITTE_ENDIAN    = 0
    BIG_ENDIAN      = 1


def get_section_reader(datatype: str, byte_order: ByteOrder) -> str:
    """
    """
    return OJ_READERS[datatype][byte_order]

def get_dtd(name: str) -> StringIO:
    return StringIO(str(pkgutil.get_data("asamint", "data/dtds/{}.dtd".format(name)), encoding = "ascii"))

def make_continuous_blocks(chunks):
    """Try to make continous blocks from a list of small, unordered `chunks`.

    `chunks` are expected to have `address` and `length` attributes.
    """

    tmp = sorted(chunks, key = attrgetter("address"))
    pprint(tmp, indent = 4)
    result_sections = []
    prev_section = MCObject()

    while tmp:
        section = tmp.pop(0)
        #print("SEC:", section)

        if section.address == prev_section.address + prev_section.length and result_sections:
            #print("APP")
            last_segment = result_sections[-1]
            #last_segment.address = section.address
            last_segment.length += section.length
            #last_segment.data.extend(section.data)
        else:
            #print("NEW")
            # Create a new section.
            result_sections.append(MCObject(address = section.address, length = section.length))
        prev_section = section
    print(result_sections)

