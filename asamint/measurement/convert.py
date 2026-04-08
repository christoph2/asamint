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

import os
from dataclasses import dataclass, field
from typing import List

import h5py
import numpy as np

from asamint.adapters.a2l import inspect, model
from asamint.adapters.mdf import MDF
from asamint.asam import AsamMC
from asamint.config import get_application

FN = r"C:\Users\HP\PycharmProjects\asamint\asamint\examples\VectorXCP\VectorAutosar_20260106_154305h5.h5"

os.chdir(r"C:\Users\HP\PycharmProjects\asamint\asamint\examples\VectorXCP")


@dataclass
class Measurement:
    measurement: inspect.Measurement


@dataclass
class Group:
    group: inspect.Group
    measurements: list[Measurement] = field(default_factory=list)


class VectorAutosar(AsamMC):
    def __init__(self, file_name: str, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.h5 = h5py.File(file_name, mode="r+", libver="latest")
        # h5py.string_dtype(encoding="utf8")
        self.active_group = []
        self.groups: list[Group] = []
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
                group = Group(group=group_name)
                self.groups.append(group)
                self.active_group.append(group)
                self.traverse(attr)
                self.active_group.pop()
            elif isinstance(attr, h5py.Dataset):
                print(f"{attr.name} ==> {attr.parent}")
                name_parts = attr.name.rsplit("/")
                if name_parts[-1] in ("timestamp0", "timestamp1"):
                    continue
                meas_name = name_parts[-2]
                meas = inspect.Measurement.get(self.session, meas_name)
                if meas:
                    if self.active_group:
                        measurement = Measurement(measurement=meas)
                        self.active_group[-1].measurements.append(measurement)

                    cm = meas.compuMethod
                    if cm.conversionType == "TAB_VERB":
                        tp = h5py.string_dtype(encoding="utf8")
                    else:
                        tp = np.float64
                    dataset = self.h5.create_dataset(
                        f"{attr.parent.name}/physical",
                        shape=(0,),
                        maxshape=(None,),
                        dtype=tp,
                        chunks=attr.chunks,
                    )
                    for row in self.read_values(attr):
                        phys_values = cm.int_to_physical(row)
                        old_len = len(dataset)
                        dataset.resize(old_len + len(phys_values), axis=0)
                        dataset[old_len:] = phys_values


mc = VectorAutosar(FN)
app = get_application()
app.log.info(f"Loaded {FN!r} with {len(mc.groups)} groups.")
for group in mc.groups:
    app.log.info(f" Group: {group.group} with {len(group.measurements)} measurements.")
    for meas in group.measurements:
        app.log.info(f"   Measurement: {meas.measurement.name}")

MF = r"C:\Users\Public\Documents\Vector\CANape Examples 21.0\RaceTrackDemo\MeasurementFiles\SummitPoint_09637700.mf4"

mf = MDF(MF)
print(mf)
