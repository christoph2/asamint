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


from enum import IntEnum
from logging import getLogger


from sqlalchemy import func, or_

from pya2l.api.inspect import (Measurement, ModCommon, ModPar)
import pya2l.model as model
from pya2l import DB
from asamint.utils import cond_create_directories, current_timestamp
from asamint.config import Configuration


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
        "AUTHOR":                   (str,    False,  ""),
        "COMPANY":                  (str,    False,  ""),
        "DEPARTMENT":               (str,    False,  ""),
        "PROJECT":                  (str,    True,   ""),
        "SHORTNAME":                (str,    True,   ""), # Contributes to filename generation.
        "SEED_N_KEY_DLL":           (str,    False,  ""),
        "MASTER_HEXFILE":           (str,    False,  ""),
        "MASTER_HEXFILE_TYPE":      (str,    False,  "ihex"),
    }

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "SUBJECT":                  (str,    True,   ""),
        "DESCRIPTION":              (str,    False,  ""), # Long description, used as header comment.
        "SHORTNAME":                (str,    True,   ""), # Contributes to filename generation.
    }

    SUB_DIRS = {    # Could be made cofigurable.
        "measurements": "measurements",
        "parameters":   "parameters",
        "hexfiles":     "hexfiles",
    }

    def __init__(self, project_config = None, experiment_config = None, *args, **kws):
        self.project_config = Configuration(AsamBaseType.PROJECT_PARAMETER_MAP or {}, project_config or {})
        self.experiment_config = Configuration(AsamBaseType.EXPERIMENT_PARAMETER_MAP or {}, experiment_config or {})
        if not hasattr(AsamBaseType, "_session_obj"):
            db = DB()
            AsamBaseType._session_obj = db.open_create(self.project_config.get("A2L_FILE"))
        cond_create_directories()
        self.logger = getLogger(self.__class__.__name__)
        self.logger.setLevel(self.project_config.get("LOGLEVEL"))
        self.mod_common = ModCommon.get(self.session)
        self.mod_par = ModPar.get(self.session)
        self.on_init(project_config, experiment_config, *args, **kws)

    def on_init(self, *args, **kws):
        raise NotImplementedError()

    def loadConfig(self, project_config, experiment_config):
        """Load configuration data.
        """
        project_config = Configuration(self.__class__.PROJECT_PARAMETER_MAP or {}, project_config or {})
        experiment_config = Configuration(self.__class__.EXPERIMENT_PARAMETER_MAP or {}, experiment_config or {})
        self.project_config.update(project_config)
        self.experiment_config.update(experiment_config)

    def sub_dir(self, name):
        return self.SUB_DIRS.get(name)

    def generate_filename(self, extension, extra = None):
        """Automatically generate filename from configuration plus timestamp.
        """
        project = self.project_config.get("SHORTNAME")
        subject = self.experiment_config.get("SHORTNAME")
        if extra:
            return "{}_{}{}_{}{}".format(project, subject, current_timestamp(), extra, extension)
        else:
            return "{}_{}{}{}".format(project, subject, current_timestamp(), extension)

    @property
    def session(self):
        return self._session_obj

    @property
    def query(self):
        return self.session.query

    @property
    def measurements(self):
        """
        """
        query = self.query(model.Measurement.name)
        query = query.filter(or_(func.regexp(model.Measurement.name, m) for m in self.experiment_config.get("MEASUREMENTS")))
        for meas in query.all():
            yield Measurement.get(self.session, meas.name)

    def byte_order(self, obj):
        """Get byte-order for A2L element.

        Parameters
        ----------
        obj: (`AxisPts` | `AxisDescr` | `Measurement` | `Characteristic`) instance.

        Returns
        -------
        `ByteOrder`:
            If element has no BYTE_ORDER, lookup MOD_COMMON else ByteOrder.BIG_ENDIAN
        """
        return ByteOrder.BIG_ENDIAN if (getattr(obj, "byteOrder") or self.mod_common.byteOrder) \
            in ("MSB_FIRST", "LITTLE_ENDIAN") else ByteOrder.LITTLE_ENDIAN


TYPE_SIZES = {
    "BYTE":         1,
    "UBYTE":        1,
    "SBYTE":        1,
    "WORD":         2,
    "UWORD":        2,
    "SWORD":        2,
    "LONG":         4,
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
    LITTLE_ENDIAN   = 0
    BIG_ENDIAN      = 1


def get_section_reader(datatype: str, byte_order: ByteOrder) -> str:
    """
    """
    return OJ_READERS[datatype][byte_order]
