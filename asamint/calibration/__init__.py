#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

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
from collections import OrderedDict, defaultdict
from enum import IntEnum

from objutils import Image, Section, dump, load
from objutils.exceptions import InvalidAddressError
from pya2l import model
from pya2l.api.inspect import AxisPts, Characteristic, ModPar
from pyxcp.checksum import check
from pyxcp.cpp_ext.cpp_ext import McObject
from pyxcp.daq_stim.optimize import make_continuous_blocks

from asamint.asam import AsamMC
from asamint.asam.epk import Epk
from asamint.calibration import api
from asamint.calibration.mapfile import MapFile
from asamint.model.calibration import klasses
from asamint.model.calibration.klasses import MemoryObject, MemoryType
from asamint.utils import adjust_to_word_boundary, current_timestamp


class CalibrationState(IntEnum):
    DEFAULT = 0
    CHANGED = 1
    PRELIM_CALIBRATED = 2
    CALIBRATED = 3
    CHECKED = 4
    COMPLETED = 5


def dimension(obj, axis: str = "X") -> int:
    pass


def xdimension(obj) -> int:
    return dimension(obj, "X")


def ydimension(obj) -> int:
    return dimension(obj, "Y")


def zdimension(obj) -> int:
    return dimension(obj, "Z")


def axis(obj, index: int = 0):
    pass


def xaxis(obj):
    pass


def yaxis(obj):
    pass


def zaxis(obj):
    pass


def phys(obj):
    pass


def raw(obj):
    return obj.raw


class CalibrationData:
    """Fetch calibration parameters from HEX file or XCP slave and create an in-memory representation.

    Parameters
    ----------
    project_config

    experiment_config

    Note
    ----
    This is meant as a base-class for CDF, DCM, ...
    Don't use directly.
    """

    def __init__(self, asam_mc: AsamMC, *args, **kws) -> None:
        self.asam_mc = asam_mc
        self.config = asam_mc.config
        self.logger = self.config.log
        self._parameters = {
            k: OrderedDict()
            for k in (
                "AXIS_PTS",
                "VALUE",
                "VAL_BLK",
                "ASCII",
                "CURVE",
                "MAP",
                "CUBOID",
                "CUBE_4",
                "CUBE_5",
            )
        }
        self.memory_map = defaultdict(list)
        self.memory_errors = defaultdict(list)
        self.epk = Epk(self)

    def close(self):
        self.asam_mc.close()

    @property
    def session(self):
        return self.asam_mc.session

    @property
    def query(self):
        return self.asam_mc.query

    def get_memory_ranges(self) -> list[McObject]:
        """Get memory blocks/ranges relevant for calibration."""
        result = []
        a2l_epk = self.epk.from_a2l()
        if a2l_epk:
            epk_addr, epk_len = self.epk.epk_address_and_length()
            result.append(McObject("EPK", epk_addr, 0, epk_len, ""))
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(ax.name, ax.address, 0, mem_size, ""))
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))
        blocks = make_continuous_blocks(result)
        return blocks

    def validata_image(self, image: Image, cs_length: int = 128):
        for section in image.sections:
            offset = 0
            section_length = len(section)
            remaining_bytes = section_length % cs_length
            block_count = section_length // cs_length
            for idx in range(block_count):
                address = section.address + offset
                block = section.data[offset : offset + cs_length]
                self.asam_mc.xcp_master.setMta(address, 0)
                xcp_checksum = self.asam_mc.xcp_master.buildChecksum(cs_length)
                checksum = check(block, str(xcp_checksum.checksumType))
                equal = checksum == xcp_checksum.checksum
                print(f"Address: 0x{address:08X} XCPChecksum {xcp_checksum.checksum} Checksum: {checksum} ==> {equal}")
                offset += cs_length
            if remaining_bytes > 0:
                block = section.data[offset : offset + remaining_bytes]
                address = section.address + offset
                self.asam_mc.xcp_master.setMta(address, 0)
                xcp_checksum = self.asam_mc.xcp_master.buildChecksum(remaining_bytes)
                checksum = check(block, str(xcp_checksum.checksumType))
                equal = checksum == xcp_checksum.checksum
                print(f"Address: 0x{address:08X} XCPChecksum {xcp_checksum.checksum} Checksum: {checksum} ==> {equal}")

    def get_image_from_xcp(self) -> Image:
        # row_length
        sections = []
        blocks = self.get_memory_ranges()
        self.asam_mc.xcp_connect()
        total_size = functools.reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching {total_size / 1024:.2f} KBytes calibration data from XCP slave.")
        num_blocks = len(blocks)
        for idx in range(num_blocks):
            block = blocks[idx]
            # Adjust length to multiples of 4 (There are double-word checksum types).
            adj_length = adjust_to_word_boundary(block.length, 2)

            if idx < num_blocks - 1:
                dist = blocks[idx + 1].address - block.address
                length = min(dist, adj_length)
            else:
                length = adj_length
            self.asam_mc.xcp_master.setMta(block.address, block.ext)
            data = self.asam_mc.xcp_master.pull(length)
            sections.append(Section(block.address, data))
        return Image(sections)

    ###
    ###
    ###

    def load_hex(self):
        self._load_axis_pts()
        self._load_values()
        self._load_asciis()
        self._load_value_blocks()
        self._load_curves()
        self._load_maps()
        self._load_cubes()

        calibration_log = klasses.dump_characteristics(self._parameters)
        file_name = self.asam_mc.generate_filename(".json")
        file_name = self.asam_mc.sub_dir("logs") / file_name
        self.logger.info(f"Writing calibration log to {file_name!s}")
        with open(file_name, "wb") as of:
            of.write(calibration_log)
        from asamint.cdf.importer import DBImporter

        imp = DBImporter("test_db", self._parameters, self.logger)
        imp.run()
        imp.close()
        mm = MapFile("test_db.map", self.memory_map, self.memory_errors)
        mm.run()

    ##
    ##
    def load_hex_file(self, xcp_master=None, hexfile: str = None, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------
        xcp_master:

        hexfile: str
            if None, `MASTER_HEXFILE` and `MASTER_HEXFILE_TYPE` from project_config is used.

        hexfile_type: "ihex" | "srec"
        """
        if xcp_master:
            self.check_epk_xcp(xcp_master)
            self.image = self.upload_parameters(xcp_master)
            # image.file_name = None
            self.logger.info("Using image from XCP slave.")
        else:
            if not hexfile:
                hexfile = self.config.general.master_hexfile
                hexfile_type = self.config.general.master_hexfile_type
            with open(f"{hexfile}", "rb") as inf:
                self.logger.info(f"Loading characteristics from {hexfile!r}.")
                self.image = load(hexfile_type, inf)
        if not self.image:
            raise ValueError("Empty calibration image.")
        self.api = api.Calibration(self.asam_mc, self.image, self._parameters, self.logger)

    ##
    ##

    def load_characteristics(self, xcp_master=None, hexfile: str = None, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------
        xcp_master:

        hexfile: str
            if None, `MASTER_HEXFILE` and `MASTER_HEXFILE_TYPE` from project_config is used.

        hexfile_type: "ihex" | "srec"
        """
        if xcp_master:
            self.check_epk_xcp(xcp_master)
            self.image = self.upload_parameters(xcp_master)
            # image.file_name = None
            self.logger.info("Using image from XCP slave.")
        else:
            if not hexfile:
                hexfile = self.config.general.master_hexfile
                hexfile_type = self.config.general.master_hexfile_type
            with open(f"{hexfile}", "rb") as inf:
                self.logger.info(f"Loading characteristics from {hexfile!r}.")
                self.image = load(hexfile_type, inf)
        if not self.image:
            raise ValueError("Empty calibration image.")
        self.api = api.Calibration(self.asam_mc, self.image, self._parameters, self.logger)
        self.load_hex()

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

        # self.check_epk_xcp(xcp_master)
        if file_type:
            file_type = file_type.lower()
        if file_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        ram_segments = []
        mod_par = self.asam_mc.mod_par
        for segment in mod_par.memorySegments:
            if segment["memoryType"] == "RAM" or segment["name"] == "CALRAM":
                ram_segments.append(
                    (
                        segment["address"],
                        segment["size"],
                    )
                )
        if not ram_segments:
            return  # ECU program doesn't define any RAM segments.
        sections = []
        xcp_master.setCalPage(0x83, 0, 0)  # TODO: Requires paging information from IF_DATA section.
        page = 0
        for addr, size in ram_segments:
            xcp_master.setMta(addr)
            mem = xcp_master.pull(size)
            sections.append(Section(start_address=addr, data=mem))
        file_name = f'CalRAM{current_timestamp()}_P{page}.{"hex" if file_type == "ihex" else "srec"}'
        file_name = self.asam_mc.sub_dir("hexfiles") / file_name
        img = Image(sections=sections, join=False)
        with open(f"{file_name}", "wb") as outf:
            dump(file_type, outf, img, row_length=32)
        self.logger.info(f"CalRAM written to {file_name}")
        return img

    def download_calram(self, xcp_master, module_name: str = None, data: bytes = None):
        """Tansfer RAM segments from MCS to ECU.

        Parameters
        ----------

        Returns
        -------
        """
        if not data:
            return
        self.check_epk_xcp(xcp_master)
        # ram_segments = []
        mp = ModPar(self.session, module_name or None)
        segment = mp.memorySegments[0]
        if segment["memoryType"] == "RAM":
            xcp_master.setMta(segment["address"])
            # xcp_master.setMta(0x4000)
            xcp_master.push(data)
        # for segment in mp.memorySegments:
        #    if segment['memoryType'] == "RAM":
        #        ram_segments.append((segment['address'], segment['size'], ))
        # if not ram_segments:
        #    return None # ECU program doesn't define RAM segments.
        # sections = []
        # for addr, size in ram_segments:
        #    xcp_master.setMta(addr)
        #    mem = xcp_master.fetch(size)
        #    sections.append(Section(start_address = addr, data = mem))

    def upload_parameters(self, xcp_master, save_to_file: bool = True, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------

        xcp_master:

        save_to_file: bool

        hexfile_type: "ihex" | "srec"


        Returns
        -------
        `Image`

        """
        if hexfile_type:
            hexfile_type = hexfile_type.lower()
        if hexfile_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        result = []
        a2l_epk = self.epk.from_a2l()
        if a2l_epk:
            epk, address = a2l_epk
            result.append(McObject("EPK", address, 0, len(epk), ""))
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(ax.name, ax.address, 0, mem_size, ""))
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))
        blocks = make_continuous_blocks(result)
        total_size = functools.reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching a total of {total_size / 1024:.2f} KBytes from XCP slave")
        sections = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address=block.address, data=mem[: block.length]))
        img = Image(sections=sections, join=True)
        if save_to_file:
            file_name = f'CalParams{current_timestamp()}.{"hex" if hexfile_type == "ihex" else "srec"}'
            file_name = self.sub_dir("hexfiles") / file_name
            with open(f"{file_name}", "wb") as outf:
                dump(hexfile_type, outf, img, row_length=32)
            self.logger.info(f"CalParams written to {file_name}")
        return img

    def _load_asciis(self) -> None:
        self.logger.info("ASCIIs")
        for characteristic in self.characteristics("ASCII"):
            self.logger.debug(f"Processing ASCII '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["ASCII"][characteristic.name] = self.api.load_ascii(characteristic.name)

    def _load_value_blocks(self) -> None:
        self.logger.info("VAL_BLKs")
        for characteristic in self.characteristics("VAL_BLK"):
            self.logger.debug(f"Processing VAL_BLK '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["VAL_BLK"][characteristic.name] = self.api.load_value_block(characteristic.name)

    # @profile
    def _load_values(self) -> None:
        self.logger.info("VALUEs")
        for characteristic in self.characteristics("VALUE"):
            self.logger.debug(f"Processing VALUE '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["VALUE"][characteristic.name] = self.api.load_value(characteristic.name)

    def _load_axis_pts(self) -> None:
        self.logger.info("AXIS_PTSs")
        for ap in self.axis_points():
            self.logger.debug(f"Processing AXIS_PTS '{ap.name}' @0x{ap.address:08x}")
            self._parameters["AXIS_PTS"][ap.name] = self.api.load_axis_pts(ap.name)

    def _load_curves(self) -> None:
        self.logger.info("CURVEs")
        self._load_curves_and_maps("CURVE", 1)

    def _load_maps(self) -> None:
        self.logger.info("MAPs")
        self._load_curves_and_maps("MAP", 2)

    def _load_cubes(self):
        self.logger.info("CUBOIDs")
        self._load_curves_and_maps("CUBOID", 3)
        self.logger.info("CUBE_4s")
        self._load_curves_and_maps("CUBE_4", 4)
        self.logger.info("CUBE_5s")
        self._load_curves_and_maps("CUBE_5", 5)

    def _order_curves(self, curves):
        """Remove forward references from CURVE list."""
        curves = list(curves)[::1]  # Don't destroy the generator, make a copy.
        curves_by_name = {c.name: (pos, c) for pos, c in enumerate(curves)}
        while True:
            ins_pos = 0
            for curr_pos in range(len(curves)):
                curve = curves[curr_pos]
                axis_descr = curve.axisDescriptions[0]
                if axis_descr.attribute == "CURVE_AXIS":
                    if axis_descr.curveAxisRef.name in curves_by_name:
                        ref_pos, ref_curve = curves_by_name.get(axis_descr.curveAxisRef.name)
                        if ref_pos > curr_pos:
                            # Swap
                            t_curve = curves[ins_pos]
                            curves[ins_pos] = curves[ref_pos]
                            curves[ref_pos] = t_curve
                            curves_by_name[curves[ins_pos].name] = (
                                ins_pos,
                                curves[ins_pos],
                            )
                            curves_by_name[curves[ref_pos].name] = (
                                ref_pos,
                                curves[ref_pos],
                            )
                            ins_pos += 1
            if ins_pos == 0:
                break  # No more swaps, we're done.
        return curves

    def _load_curves_and_maps(self, category: str, num_axes: int):
        characteristics = self.characteristics(category)
        if num_axes == 1:
            # CURVEs may reference other CURVEs, so some ordering is required.
            characteristics = self._order_curves(characteristics)
        for characteristic in characteristics:
            self.logger.debug(f"Processing {category} '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters[f"{category}"][characteristic.name] = self.api.load_curve_or_map(
                characteristic.name, category, num_axes
            )

    def log_memory_errors(self, exc: Exception, memory_type: MemoryType, name: str, address: int, length):
        if isinstance(exc, InvalidAddressError):
            self.memory_errors[address].append(MemoryObject(memory_type=memory_type, name=name, address=address, length=length))

    @property
    def parameters(self):
        return self._parameters

    def axis_points(self):
        """ """
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            try:
                ap = AxisPts.get(self.session, a.name)
            except Exception as e:
                self.logger.error(e)
                continue
            yield ap

    def characteristics(self, category: str) -> Characteristic:
        """ """
        query = self.query(model.Characteristic.name).filter(model.Characteristic.type == category)
        for characteristic in query.all():
            yield Characteristic.get(self.session, characteristic.name)
