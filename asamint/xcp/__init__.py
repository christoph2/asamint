#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

"""

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

from collections import namedtuple, defaultdict
import os
from pprint import pprint
import time


from asamint.asam import AsamBaseType, TYPE_SIZES
from asamint.xcp.reco import XcpLogFileWriter
from asamint.cdf import CDFCreator
from asamint.utils.optimize import McObject, make_continuous_blocks, binpacking
from asamint.utils import current_timestamp
import pya2l.model as model
from pya2l.api.inspect import AxisPts, Characteristic, Group, Function
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
        self.a2l_epk = self.epk_from_a2l()

    def check_epk(self, xcp_master):
        """Compare EPK (EPROM Kennung) from A2L with EPK from ECU.

        Returns
        -------
            - True:     EPKs are matching.
            - False:    EPKs are not matching.
            - None:     EPK not configured in MOD_COMMON.
        """
        if not self.a2l_epk:
            return False
        epk_a2l, epk_addr = self.a2l_epk
        xcp_master.setMta(epk_addr)
        epk_xcp = xcp_master.pull(len(epk_a2l)).decode("ascii")
        ok = epk_xcp == epk_a2l
        if not ok:
            self.logger.warn("EPK is invalid -- A2L: '{}' got '{}'.".format(self.mod_par.epk, epk))
        else:
            self.logger.info("OK, found matching EPK.")
        return ok

    def epk_from_a2l(self):
        """Read EPK from A2L database.

        Returns
        -------
        """
        if self.mod_par.addrEpk is None:
            return None
        elif self.mod_par.epk is None:
            return None
        else:
            addr = self.mod_par.addrEpk[0]
            epk = epk.decode("ascii")
            return (epk, addr)

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
            img = self.upload_parameters(xcp_master)
            img.file_name = None
        else:
            if not hexfile:
                hexfile = self.project_config.get("MASTER_HEXFILE")
                hexfile_type = self.project_config.get("MASTER_HEXFILE_TYPE")
            with open("{}".format(hexfile), "rb") as inf:
                img = load(hexfile_type, inf)
            img.file_name = hexfile
        if not img:
            raise ValueError("")
        cdf = CDFCreator(self.project_config, self.experiment_config, img)

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


DaqEntry = namedtuple("DaqEntry", "daq odt entry bitoff length ext address")

DAQ_ID_FIELD_SIZE = {
    "IDF_ABS_ODT_NUMBER": 1,
    "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_BYTE": 2,
    "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD": 3,
    "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD_ALIGNED": 4,
}


class XCPMeasurement(AsamBaseType):
    """
    GROUP Measure
    """

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self.address_mapping = defaultdict(set)

    def setup_groups(self, groups):
        # 'maxDto'
        # 'maxWriteDaqMultipleElements'
        #
        # 'processor'['optimisationType', 'resolution']

        result = []
        for name in groups:
            result.extend(self._collect_group(name))
        #print("RESULT:", result, end = "\n\n")
        blocks = make_continuous_blocks(result)
        #print("BLOXxX:", blocks, end = "\n\n")

        for k, items in sorted(self.address_mapping.items(), key = lambda x: x[0]):
            print("ADDR: 0x{:08x}::{}".format(*k))
            for item in sorted(items, key = lambda x: x.name):
                print("\t", item.name)
        return blocks


    def _collect_group(self, name: str, recursive: bool = True, level = 0):
        """
        """
        result = []
        gr = Group(self.session, name)
        for meas in gr.measurements:
            spaces = "  " * level
            print(spaces, meas.name, hex(meas.ecuAddress), meas.ecuAddressExtension, meas.datatype, TYPE_SIZES.get(meas.datatype))
            result.append(McObject(
                meas.name, meas.ecuAddress, TYPE_SIZES.get(meas.datatype))
            )
            self.address_mapping[(meas.ecuAddress, meas.ecuAddressExtension)].add(meas)
        if recursive:
            for sg in gr.subgroups:
                result.extend(self._collect_group(sg.name, recursive = recursive, level = level + 1))
        return result

    def start_measurement(self, xcp_master, groups = None):
        self.uncompressed_size = 0
        self.intermediate_storage = []

        xcp_master.cro_callback = self.wockser
        self.log_writer = XcpLogFileWriter("rekorder", 10, chunk_size = 250, compression_level = 9)

        blocks = self.setup_groups(groups)

        xcp_master.freeDaq()
        slp = xcp_master.slaveProperties
        max_dto = slp["maxDto"]
        daq_info = xcp_master.getDaqInfo()
        pprint(daq_info, indent = 4)
        daq_proc = daq_info["processor"]
        daq_proc_props = daq_proc["properties"]
        idf = daq_proc["keyByte"]["identificationField"]
        idf_size = DAQ_ID_FIELD_SIZE[idf]
        bin_size = max_dto - idf_size
        print("MAX_DTO", max_dto, bin_size)
        bins = binpacking.first_fit_decreasing(items = blocks, bin_size = bin_size)
        bin_count = len(bins)
        xcp_master.allocDaq(1)
        xcp_master.allocOdt(0, bin_count)
        entries = []
        for odt_num in range(bin_count):
            bin = bins[odt_num]
            xcp_master.allocOdtEntry(0, odt_num, bin.num_entries)
            for odt_entry_num in range(bin.num_entries):
                odt_entry = bin.entries[odt_entry_num]
                entries.append(DaqEntry(daq = 0, odt = odt_num, entry = odt_entry_num, bitoff = 255, length = odt_entry.length, ext = 0, address = odt_entry.address))
        for daq, odt, entry, bitoff, size, ext, addr in entries:
            xcp_master.setDaqPtr(daq, odt, entry)
            xcp_master.writeDaq(bitoff, size, ext, addr)

        xcp_master.setDaqListMode(mode = 0x10, daqListNumber = 0, eventChannelNumber = 3, prescaler = 1, priority = 0)
        print("startStopDaqList #0", xcp_master.startStopDaqList(0x02, 0))
        #xcp_master.setDaqListMode(0x10, 1, 2, 1, 0) # , 2)
        #print("startStopDaqList #1", xcp_master.startStopDaqList(0x02, 1))
        xcp_master.startStopSynch(0x01)

        time.sleep(5.0 * 4 * 200)
        xcp_master.startStopSynch(0x00)
        #xcp_master.freeDaq()

        if self.uncompressed_size:
            print("Bytes remaining", self.uncompressed_size)
            #print(self.intermediate_storage)

        self.log_writer.close()

        """
        xcp_master.allocDaq(2)

        xcp_master.allocOdt(0, 13)
        xcp_master.allocOdt(1, 2)

        xcp_master.allocOdtEntry(0, 0, 1)
        xcp_master.allocOdtEntry(0, 1, 1)
        xcp_master.allocOdtEntry(0, 2, 1)
        xcp_master.allocOdtEntry(0, 3, 1)
        xcp_master.allocOdtEntry(0, 4, 1)
        xcp_master.allocOdtEntry(0, 5, 1)
        xcp_master.allocOdtEntry(0, 6, 1)
        xcp_master.allocOdtEntry(0, 7, 1)
        xcp_master.allocOdtEntry(0, 8, 1)
        xcp_master.allocOdtEntry(0, 9, 1)
        xcp_master.allocOdtEntry(0, 10, 1)
        xcp_master.allocOdtEntry(0, 11, 3)
        xcp_master.allocOdtEntry(0, 12, 5)

        xcp_master.allocOdtEntry(1, 0, 1)
        xcp_master.allocOdtEntry(1, 1, 1)

        de0 = (
            DaqEntry(daq=0, odt=0,  entry=0, bitoff=255, size=2, ext=0, addr=0x001BE068),
            DaqEntry(daq=0, odt=1,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE06A),
            DaqEntry(daq=0, odt=2,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE070),
            DaqEntry(daq=0, odt=3,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE076),
            DaqEntry(daq=0, odt=4,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE07C),
            DaqEntry(daq=0, odt=5,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE082),
            DaqEntry(daq=0, odt=6,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE088),
            DaqEntry(daq=0, odt=7,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE08E),
            DaqEntry(daq=0, odt=8,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE094),
            DaqEntry(daq=0, odt=9,  entry=0, bitoff=255, size=6, ext=0, addr=0x001BE09A),
            DaqEntry(daq=0, odt=10, entry=0, bitoff=255, size=6, ext=0, addr=0x001BE0A0),
            DaqEntry(daq=0, odt=11, entry=0, bitoff=255, size=2, ext=0, addr=0x001BE0A6),
            DaqEntry(daq=0, odt=11, entry=1, bitoff=255, size=1, ext=0, addr=0x001BE0CF),
            DaqEntry(daq=0, odt=11, entry=2, bitoff=255, size=3, ext=0, addr=0x001BE234),
            DaqEntry(daq=0, odt=12, entry=0, bitoff=255, size=1, ext=0, addr=0x001BE237),
            DaqEntry(daq=0, odt=12, entry=1, bitoff=255, size=1, ext=0, addr=0x001BE24F),
            DaqEntry(daq=0, odt=12, entry=2, bitoff=255, size=1, ext=0, addr=0x001BE269),
            DaqEntry(daq=0, odt=12, entry=3, bitoff=255, size=1, ext=0, addr=0x001BE5A3),
            DaqEntry(daq=0, odt=12, entry=4, bitoff=255, size=1, ext=0, addr=0x001C0003),
            DaqEntry(daq=1, odt=0 , entry=0, bitoff=255, size=2, ext=0, addr=0x001C002C),
            DaqEntry(daq=1, odt=1 , entry=0, bitoff=255, size=2, ext=0, addr=0x001C002E),
        )

        for daq, odt, entry, bitoff, size, ext, addr in de0:
            xcp_master.setDaqPtr(daq, odt, entry)
            xcp_master.writeDaq(bitoff, size, ext, addr)

        xcp_master.setDaqListMode(0x10, 0, 1, 1, 0) # , 1)
        print("startStopDaqList #0", xcp_master.startStopDaqList(0x02, 0))
        xcp_master.setDaqListMode(0x10, 1, 2, 1, 0) # , 2)
        print("startStopDaqList #1", xcp_master.startStopDaqList(0x02, 1))
        xcp_master.startStopSynch(0x01)
        """
    # Don't support virtual measurements for now, to keep things simple.

    def wockser(self, catagory, *args):
        response, counter, length, timestamp = args
        #print(catagory, response, counter, length, timestamp)   # .tobytes()
        raw_data = response.tobytes()
        self.intermediate_storage.append((counter, timestamp, raw_data, ))
        #li = DAQ_RECORD_STRUCT.pack(1, counter, timestamp, length)
        self.uncompressed_size += len(raw_data) + 12
        if self.uncompressed_size > 10 * 1024:
            #print("PUSH to worker!!")
            self.log_writer.add_xcp_frames(self.intermediate_storage)
            self.intermediate_storage = []
            self.uncompressed_size = 0
