#!/usr/bin/env python

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2026 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import logging
from dataclasses import dataclass, field
import os
from typing import List

import numpy as np
import h5py

from asamint.adapters.a2l import inspect, model
from asamint.config import get_application
from asamint.asam import AsamMC

logger = logging.getLogger(__name__)

FN = r"C:\Users\Chris\PycharmProjects\asamint\asamint\examples\VectorXCP\VectorAutosar_20260101_154209h5.h5"

os.chdir(r"C:\Users\Chris\PycharmProjects\asamint\asamint\examples\VectorXCP")

# C:\Users\Public\Documents\Vector\CANape Examples 23\RaceTrackDemo\MeasurementFiles\SummitPoint_09637700.mf4
# Alt, Brake, FuelLevelPct, Gear, RPM, Speed


@dataclass
class Measurement:
    measurement: inspect.Measurement


@dataclass
class Group:
    group: inspect.Group
    measurements: List[Measurement] = field(default_factory=list)


class VectorAutosar(AsamMC):
    def __init__(self, file_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.h5 = h5py.File(file_name, mode="r", libver="latest")
        # h5py.string_dtype(encoding="utf8")
        self.active_group = []
        self.groups: List[Group] = []
        self.traverse(self.h5)

    def read_values(self, attr: h5py.Dataset):
        total_size = attr.len()
        if not total_size:
            yield []
        chunks = attr.chunks
        if chunks:
            chunk_size = chunks[0]
        else:
            chunk_size = 1024
        count = total_size // chunk_size
        remaining = total_size % chunk_size
        offset = 0
        for _idx in range(count):
            yield attr[offset : offset + chunk_size]
            offset += chunk_size
        if remaining:
            yield attr[offset : offset + remaining]

    def traverse(self, elem):
        for attr in elem.values():
            if isinstance(attr, h5py.Group):
                group_name = attr.name.lstrip("/")
                group = inspect.Group.get(self.session, group_name)
                new_group = None
                if group:
                    new_group = Group(group=group)
                    self.groups.append(new_group)
                    self.active_group.append(new_group)
                self.traverse(attr)
                if group:
                    self.active_group.pop()
            elif isinstance(attr, h5py.Dataset):
                logger.debug("%s ==> %s", attr.name, attr.parent)
                meas_name = attr.name.rsplit("/")[-1]
                if meas_name in ("timestamp0", "timestamp1"):
                    continue
                meas = inspect.Measurement.get(self.session, meas_name)
                if meas:
                    if self.active_group:
                        measurement = Measurement(measurement=meas)
                        self.active_group[-1].measurements.append(measurement)

                    cm = meas.compuMethod
                    if cm.conversionType == "TAB_VERB":
                        pass
                    else:
                        pass
                    for row in self.read_values(attr):
                        phys_values = cm.int_to_physical(row)
                        logger.debug("%s", phys_values)


mc = VectorAutosar(FN)
app = get_application()


"""
Für mod_common,
tools/app_gen/main.py, Zeilen 151-155
wird ein detailierteres Vorgehen benötigt. Setze nur Werte, die nicht vorhanden sind, erstelle dafür eine Funktion
"""
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import JsonSerializer
from xsdata.formats.dataclass.parsers import JsonParser
from xsdata.formats.dataclass.serializers import XmlSerializer

from asamint.data.dtds.mdf import v42 as mdf

from lxml import etree

MDF_NS = "http://www.asam.net/mdf/v4"


def ensure_namespace(xml: str, namespace: str = MDF_NS) -> str:
    root = etree.fromstring(xml.encode("utf-8"))

    # Prüfen, ob das Root-Element bereits einen Namespace hat
    if root.tag.startswith("{"):
        # Namespace ist vorhanden → nichts tun
        return xml

    # Root hat keinen Namespace → Namespace hinzufügen
    root.tag = f"{{{namespace}}}{root.tag}"

    # Auch alle Kinder müssen in den Default-NS
    for elem in root.iter():
        if not elem.tag.startswith("{"):
            elem.tag = f"{{{namespace}}}{elem.tag}"

    # Serialisieren
    return etree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


fixed_xml = ensure_namespace(xml_input)
obj = parser.from_string(fixed_xml, mdf.Hdcomment)
