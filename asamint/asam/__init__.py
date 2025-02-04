#!/usr/bin/env python
"""
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

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
__author__ = "Christoph Schueler"


import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

import pya2l.model as model
from pya2l import DB
from pya2l.api.inspect import Group, Measurement, ModCommon, ModPar
from sqlalchemy import func, or_

from asamint.config import get_application
from asamint.utils import current_timestamp, partition


def create_xcp_master():
    from pyxcp.master import Master

    from asamint.config import get_application

    app = get_application()
    xcp_config = app.xcp
    master = Master(
        xcp_config.transport.layer, config=xcp_config  # policy=policy, transport_layer_interface=transport_layer_interface
    )
    return master


@dataclass
class Group:
    name: str
    sub_groups: list[Group] = field(default_factory=list)


class Directory:
    """Maintains A2L FUNCTION and  GROUP hierachy."""

    def __init__(self, session):
        self.session = session
        self.group_by_rid = {}
        self.group_by_name = {}
        self.function_by_rid = {}
        self.function_by_name = {}
        self.group_treee = []

        gr = self.session.query(model.Group).all()
        for g in gr:
            self.group_by_rid[g.rid] = g
            self.group_by_name[g.groupName] = g
        fc = self.session.query(model.Function).all()
        for f in fc:
            self.function_by_rid[f.rid] = f
            self.function_by_name[f.name] = f
            # print(f)
        # print("=" * 80)
        root_groups, gr = partition(lambda g: g.root is not None, gr)

        if root_groups:
            # print("ROOT")
            for g in root_groups:
                self.group_treee.append(Group(g.groupName))
                # print(g, g.sub_group.identifier)   # 'groupLongIdentifier', 'groupName'

            # print("*** NON-ROOT")
            # for g in gr:
            #    print(g, g.sub_group)   # 'groupLongIdentifier', 'groupName'
        else:
            pass
            # print("*** NO ROOT GROUPS")
        # print("KRUPS", self.group_treee)

    def create_sub_tree(self):
        pass


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

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "SUBJECT": (str, True, ""),
        "DESCRIPTION": (str, False, ""),  # Long description, used as header comment.
        "SHORTNAME": (str, True, ""),  # Contributes to filename generation.
    }

    SUB_DIRS = {  # Could be made cofigurable.
        "measurements": "measurements",
        "parameters": "parameters",
        "hexfiles": "hexfiles",
        "logs": "logs",
    }

    def __init__(self, project_config=None, experiment_config=None, *args, **kws):
        self.config = get_application()
        self.logger = self.config.log

        self.shortname = self.config.general.shortname
        self.a2l_encoding = self.config.general.a2l_encoding
        self.a2l_dynamic = self.config.general.a2l_dynamic
        self.a2l_file = self.config.general.a2l_file
        self.author = self.config.general.author
        self.company = self.config.general.company
        self.department = self.config.general.department
        self.project = self.config.general.project
        self.master_hexfile = self.config.general.master_hexfile
        self.master_hexfile_type = self.config.general.master_hexfile_type

        self.xcp_master = create_xcp_master()
        self.xcp_connected = False

        # self.xcp_master.connect()
        # self.xcp_connected = True

        if not self.a2l_dynamic:
            self.open_create_session(
                self.a2l_file,
                encoding=self.a2l_encoding,
            )

        self.cond_create_directories()

        self.mod_common = ModCommon.get(self.session)
        self.mod_par = ModPar.get(self.session) if ModPar.exists(self.session) else None

        self.directory = Directory(self.session)
        self.on_init(project_config, experiment_config, *args, **kws)

    def cond_create_directories(self) -> None:
        """ """
        SUB_DIRS = [
            "experiments",
            "measurements",
            "parameters",
            "hexfiles",
            "logs",
        ]
        for dir_name in SUB_DIRS:
            if not os.access(dir_name, os.F_OK):
                self.logger.info(f"Creating directory {dir_name!r}")
                os.mkdir(dir_name)

    def open_create_session(self, a2l_file, encoding="latin-1"):
        if not hasattr(AsamBaseType, "_session_obj"):
            db = DB()
            AsamBaseType._session_obj = db.open_create(a2l_file, encoding=encoding)

    def on_init(self, *args, **kws):
        raise NotImplementedError()

    def loadConfig(self, project_config, experiment_config):
        """Load configuration data."""
        # project_config = Configuration(self.__class__.PROJECT_PARAMETER_MAP or {}, project_config or {})
        # experiment_config = Configuration(self.__class__.EXPERIMENT_PARAMETER_MAP or {}, experiment_config or {})
        # self.project_config.update(project_config)
        # self.experiment_config.update(experiment_config)

    def sub_dir(self, name) -> Path:
        return Path(self.SUB_DIRS.get(name))

    def generate_filename(self, extension, extra=None):
        """Automatically generate filename from configuration plus timestamp."""
        project = self.shortname
        subject = f"SUBJ_{self.shortname}"  #  self.experiment_config.get("SHORTNAME")
        if extra:
            return f"{project}_{subject}{current_timestamp()}_{extra}{extension}"
        else:
            return f"{project}_{subject}{current_timestamp()}{extension}"

    def close(self):
        if self.xcp_connected:
            try:
                self.xcp_master.disconnect()
            finally:
                self.xcp_master.close()
                self.xcp_connected = False

    @property
    def session(self):
        return self._session_obj

    @property
    def query(self):
        return self.session.query

    @property
    def measurements(self):
        """ """
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
        return (
            ByteOrder.BIG_ENDIAN
            if obj.byteOrder or self.mod_common.byteOrder in ("MSB_FIRST", "LITTLE_ENDIAN")
            else ByteOrder.LITTLE_ENDIAN
        )


TYPE_SIZES = {
    "BYTE": 1,
    "UBYTE": 1,
    "SBYTE": 1,
    "WORD": 2,
    "UWORD": 2,
    "SWORD": 2,
    "LONG": 4,
    "ULONG": 4,
    "SLONG": 4,
    "A_UINT64": 8,
    "A_INT64": 8,
    "FLOAT32_IEEE": 4,
    "FLOAT64_IEEE": 8,
}

OJ_READERS = {
    "UBYTE": ("uint8_le", "uint8_be"),
    "SBYTE": ("int8_le", "int8_be"),
    "UWORD": ("uint16_le", "uint16_be"),
    "SWORD": ("int16_le", "int16_be"),
    "ULONG": ("uint32_le", "uint32_be"),
    "SLONG": ("int32_le", "int32_be"),
    "A_UINT64": ("uint64_le", "uint64_be"),
    "A_INT64": ("int64_le", "int64_be"),
    "FLOAT32_IEEE": ("float32_le", "float32_be"),
    "FLOAT64_IEEE": ("float64_le", "float64_be"),
}


class ByteOrder(IntEnum):
    LITTLE_ENDIAN = 0
    BIG_ENDIAN = 1


def get_section_reader(datatype: str, byte_order: ByteOrder) -> str:
    """ """
    return OJ_READERS[datatype][byte_order]


# abt = AsamBaseType()
