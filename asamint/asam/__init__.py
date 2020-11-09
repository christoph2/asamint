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
from logging import getLogger

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
        self.project_config = Configuration(AsamBaseType.PROJECT_PARAMETER_MAP or {}, project_config or {})
        self.experiment_config = Configuration(AsamBaseType.EXPERIMENT_PARAMETER_MAP or {}, experiment_config or {})
        db = DB()
        self._session_obj = db.open_create(self.project_config.get("A2L_FILE"))
        cond_create_directories()
        self.logger = getLogger(self.__class__.__name__)
        self.logger.setLevel(self.project_config.get("LOGLEVEL"))
        self.on_init(project_config, experiment_config, *args, **kws)

    def on_init(self, *args, **kws):
        raise NotImplementedError()

    def loadConfig(self, project_config, experiment_config):
        """Load configuration data.
        """
        project_config = Configuration(self.__class__.PROJECT_PARAMETER_MAP or {}, project_config or {})
        print("PM:", self.__class__.PROJECT_PARAMETER_MAP, end = "\n\n")
        print("PC", project_config, end = "\n\n")
        experiment_config = Configuration(self.__class__.EXPERIMENT_PARAMETER_MAP or {}, experiment_config or {})
        self.project_config.update(project_config)
        self.experiment_config.update(experiment_config)

    @property
    def session(self):
        return self._session_obj


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
