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

import functools
import time
from collections import namedtuple

import pya2l.model as model
from objutils import Image, Section, dump, load
from pya2l.api.inspect import AxisPts, Characteristic, Group

from asamint.asam import TYPE_SIZES, AsamBaseType
from asamint.cdf import CDFCreator
from asamint.utils import chunks, current_timestamp
from asamint.utils.optimize import McObject, binpacking, make_continuous_blocks
from asamint.xcp.reco import LogConverter, Worker


class CalibrationData(AsamBaseType):
    """ """

    PROJECT_PARAMETER_MAP = {
        #                                   Type     Req'd   Default
        "MDF_VERSION": (str, False, "4.10"),
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
            self.logger.warn(f"EPK is invalid -- A2L: '{epk_a2l}' got '{epk_xcp}'.")
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
            epk = self.mod_par.epk.decode("ascii")
            return (epk, addr)

    def save_parameters(self, xcp_master=None, hexfile: str = None, hexfile_type: str = "ihex"):
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
                hexfile = self.master_hexfile
                hexfile_type = self.master_hexfile_type
            with open(f"{hexfile}", "rb") as inf:
                img = load(hexfile_type, inf)
            img.file_name = hexfile
        if not img:
            raise ValueError("")
        CDFCreator(self.project_config, self.experiment_config, img)

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
        if hexfile_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        result = []
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(ax.name, ax.address, mem_size))
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            chx = Characteristic.get(self.session, c.name)
            mem_size = chx.total_allocated_memory
            result.append(McObject(chx.name, chx.address, mem_size))
        blocks = make_continuous_blocks(result)
        total_size = functools.reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching a total of {total_size / 1024:.3f} KBytes from XCP slave")
        sections = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address=block.address, data=mem))
        img = Image(sections=sections, join=False)
        if save_to_file:
            file_name = "CalParams{}.{}".format(current_timestamp(), "hex" if hexfile_type == "ihex" else "srec")
            file_name = self.sub_dir("hexfiles") / file_name
            with open(f"{file_name}", "wb") as outf:
                dump(hexfile_type, outf, img, row_length=32)
            self.logger.info(f"CalParams written to {file_name}")
        return img


DaqEntry = namedtuple("DaqEntry", "bitoff length address ext")

DAQ_ID_FIELD_SIZE = {
    "IDF_ABS_ODT_NUMBER": 1,
    "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_BYTE": 2,
    "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD": 3,
    "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD_ALIGNED": 4,
}


def associate_measurement_to_odt_entry():
    """ """


class XCPMeasurement(AsamBaseType):
    """ """

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)

    def setup_groups(self, groups):
        result = []
        measurement_summary = []
        for name in groups:
            result.extend(self._collect_group(name, measurement_summary=measurement_summary))
        blocks = make_continuous_blocks(result)
        return blocks, measurement_summary

    def _collect_group(self, name: str, recursive: bool = True, measurement_summary: list = None):
        """ """
        result = []
        gr = Group(self.session, name)
        for meas in gr.measurements:
            if meas.is_virtual:
                continue
            measurement_summary.append(
                (
                    meas.name,
                    meas.ecuAddress,
                    meas.ecuAddressExtension,
                    meas.datatype,
                    TYPE_SIZES.get(meas.datatype),
                    meas.compuMethod.name,
                )
            )
            result.append(McObject(meas.name, meas.ecuAddress, TYPE_SIZES.get(meas.datatype)))
        if recursive:
            for sg in gr.subgroups:
                result.extend(
                    self._collect_group(
                        sg.name,
                        recursive=recursive,
                        measurement_summary=measurement_summary,
                    )
                )
        return result

    def start_measurement(self, xcp_master, groups=None):
        self.uncompressed_size = 0
        self.intermediate_storage = []

        xcp_master.cro_callback = self.wockser

        self.worker = Worker("rekorder")

        blocks, measurement_summary = self.setup_groups(groups)

        slp = xcp_master.slaveProperties
        max_dto = slp["maxDto"]
        # byteOrder = slp["byteOrder"]

        maxWriteDaqMultipleElements = slp.maxWriteDaqMultipleElements  # TODO: Optional service.
        maxWriteDaqMultipleElements = 0  # Don't use for now

        daq_info = xcp_master.getDaqInfo()
        daq_proc = daq_info["processor"]
        idf = daq_proc["keyByte"]["identificationField"]
        idf_size = DAQ_ID_FIELD_SIZE[idf]
        bin_size = max_dto - idf_size
        bins = binpacking.first_fit_decreasing(items=blocks, bin_size=bin_size)
        # for bin in bins:
        #    for entry in sorted(bin.entries, key = lambda e: e.address):
        #        print(entry)
        bin_count = len(bins)

        # Create / Allocate DAQs
        xcp_master.freeDaq()
        xcp_master.allocDaq(1)
        xcp_master.allocOdt(0, bin_count)
        daqs = []
        odts = []
        for odt_num in range(bin_count):
            bin = bins[odt_num]
            xcp_master.allocOdtEntry(0, odt_num, bin.num_entries)
            odt_entries = []
            for odt_entry_num in range(bin.num_entries):
                odt_entry = bin.entries[odt_entry_num]
                odt_entries.append(
                    DaqEntry(
                        bitoff=0xFF,
                        length=odt_entry.length,
                        ext=0,
                        address=odt_entry.address,
                    )
                )
            odts.append(odt_entries)
        daqs.append(odts)
        # pprint(daqs, indent = 4)
        # daq_list = DaqList(odts, measurement_summary)

        """
        daq_list.find(0xe10be)
        daq_list.find(0xe10be, ext = 1)
        daq_list.find(0x125438)
        daq_list.find(0x125439)
        daq_list.find(0x12543a)
        #daq_list.find(0x125438, 3)
        daq_list.find(0x1000, 0)
        #daq_list.find(0x1000, 1)
        daq_list.find(0x12543c)
        daq_list.find(0x12543d)
        """

        # Write DAQs.
        for daq_idx, daq in enumerate(daqs):
            for odt_idx, odt in enumerate(daq):
                xcp_master.setDaqPtr(daq_idx, odt_idx, 0)
                if maxWriteDaqMultipleElements:
                    for requ in chunks(odt, maxWriteDaqMultipleElements):
                        xcp_master.writeDaqMultiple(
                            [
                                dict(
                                    bitOffset=r.bitoff,
                                    size=r.length,
                                    address=r.address,
                                    addressExt=r.ext,
                                )
                                for r in requ
                            ]
                        )
                else:
                    for _, odt_entry in enumerate(odt):
                        xcp_master.writeDaq(
                            odt_entry.bitoff,
                            odt_entry.length,
                            odt_entry.ext,
                            odt_entry.address,
                        )

        xcp_master.setDaqListMode(mode=0x10, daqListNumber=0, eventChannelNumber=3, prescaler=1, priority=0)
        print("startStopDaqList #0", xcp_master.startStopDaqList(0x02, 0))
        # xcp_master.setDaqListMode(0x10, 1, 2, 1, 0) # , 2)
        # print("startStopDaqList #1", xcp_master.startStopDaqList(0x02, 1))

        self.worker.start()

        xcp_master.startStopSynch(0x01)

        time.sleep(5.0 * 2)  # * 200
        xcp_master.startStopSynch(0x00)
        # xcp_master.freeDaq()
        self.worker.shutdown_event.set()
        self.worker.join()

        lc = LogConverter(slp, daq_info, "rekorder")
        lc.start()
        lc.join()

    def wockser(self, catagory, *args):
        response, counter, length, timestamp = args
        raw_data = response.tobytes()
        self.intermediate_storage.append(
            (
                counter,
                timestamp,
                raw_data,
            )
        )
        self.uncompressed_size += len(raw_data) + 12
        if self.uncompressed_size > 10 * 1024:
            self.worker.frame_queue.put(self.intermediate_storage)
            self.intermediate_storage = []
            self.uncompressed_size = 0
