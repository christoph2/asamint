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

import itertools
from logging import getLogger
from operator import itemgetter
import os
from random import choice, shuffle
from string import ascii_letters
import time

from pprint import pprint

from asamint.asam import AsamBaseType
from asamint.cdf import CDFCreator
from asamint.utils.optimize import McObject, make_continuous_blocks
from asamint.utils import current_timestamp
import pya2l.model as model
from pya2l.api.inspect import Measurement, ModPar, ModCommon, Characteristic, AxisPts
from objutils import dump, load, Image, Section


class CalibrationData(AsamBaseType):
    """
    """

    PROJECT_PARAMETER_MAP = {
#                                   Type     Req'd   Default
        "MDF_VERSION":              (str,    False,   "4.10"),
    }

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)

    def upload_calram(self, xcp_master, file_type: str = "ihex"):
        """Tansfer RAM segments from ECU to MCS.

        Parameters
        ----------

        Returns
        -------
        :class:`~objutils.Image` or `None`, if there are no suitable segments to read out.

        Note
        ----
        Depending on your calibration concept, CalRAM may or may not cover all of your parameters.
        s. `upload_parameters`
        """

        if file_type:
            file_type = file_type.lower()
        if not file_type in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        ram_segments = []
        mp = ModPar(self.session, None) #  or None)
        for segment in mp.memorySegments:
            if segment['memoryType'] == "RAM":
                ram_segments.append((segment['address'], segment['size'], ))
        if not ram_segments:
            return  # ECU program doesn't define any RAM segments.
        sections = []
        xcp_master.setCalPage(0x83, 0, 0)   # TODO: Requires paging information from IF_DATA section.
        page = 0
        for addr, size in ram_segments:
            xcp_master.setMta(addr)
            mem = xcp_master.pull(size)
            sections.append(Section(start_address = addr, data = mem))
        file_name = "CalRAM{}_P{}.{}".format(current_timestamp(), page, "hex" if file_type == "ihex" else "srec")
        file_name = os.path.join(self.sub_dir("hexfiles"), file_name)
        img = Image(sections = sections, join = False)
        with open("{}".format(file_name), "wb") as outf:
            dump(file_type, outf, img, row_length = 32)
        self.logger.info("CalRAM written to {}".format(file_name))
        return img


    def download_calram(self, xcp_master, module_name : str = None, data: bytes = None):
        """Tansfer RAM segments from MCS to ECU.

        Parameters
        ----------

        Returns
        -------
        """
        if not data:
            return
        ram_segments = []
        mp = ModPar(self.session, module_name or None)
        segment = mp.memorySegments[0]
        if segment['memoryType'] == "RAM":
            xcp_master.setMta(segment['address'])
            #xcp_master.setMta(0x4000)
            xcp_master.push(data)
        #for segment in mp.memorySegments:
        #    if segment['memoryType'] == "RAM":
        #        ram_segments.append((segment['address'], segment['size'], ))
        #if not ram_segments:
        #    return None # ECU program doesn't define RAM segments.
        #sections = []
        #for addr, size in ram_segments:
        #    xcp_master.setMta(addr)
        #    mem = xcp_master.fetch(size)
        #    sections.append(Section(start_address = addr, data = mem))

    def save_parameters(self, xcp_master = None, hexfile: str = None, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------

        source: "XCP" | "FILE"
        """
        if xcp_master:
            print("XCP")
            img = self.upload_parameters(xcp_master)
        else:
            if hexfile:
                print("FILE")
            else:
                print("M-HEX")
                hexfile = self.project_config.get("MASTER_HEXFILE")
                hexfile_type = self.project_config.get("MASTER_HEXFILE_TYPE")
            with open("{}".format(hexfile), "rb") as inf:
                img = load(hexfile_type, inf)
            print(img)
        print("S-P", xcp_master, hexfile, hexfile_type)
        if not img:
            raise ValueError("")
        cdf = CDFCreator(self.session, img)

    def upload_parameters(self, xcp_master, save_to_file: bool = True, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------


        Returns
        -------
        `Image`

        """
        if hexfile_type:
            hexfile_type = hexfile_type.lower()
        if not hexfile_type in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        result = []
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(
                ax.name, ax.address, mem_size)
            )
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            chx = Characteristic.get(self.session, c.name)
            mem_size = chx.total_allocated_memory
            result.append(McObject(
                chx.name, chx.address, mem_size)
            )
        blocks = make_continuous_blocks(result)
        sections = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address = block.address, data = mem))
        img = Image(sections = sections, join = False)
        if save_to_file:
            file_name = "CalParams{}.{}".format(current_timestamp(), "hex" if hexfile_type == "ihex" else "srec")
            file_name = os.path.join(self.sub_dir("hexfiles"), file_name)
            with open("{}".format(file_name), "wb") as outf:
                dump(hexfile_type, outf, img, row_length = 32)
            self.logger.info("CalParams written to {}".format(file_name))
        return img
