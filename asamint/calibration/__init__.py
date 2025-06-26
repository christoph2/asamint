#!/usr/bin/env python
"""
Calibration data handling module for ASAM calibration data.

This module provides classes and functions for working with calibration data,
including loading, validating, and manipulating calibration parameters from
HEX files or XCP slaves.
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
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

from collections.abc import Generator

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
    """Enumeration of possible calibration states for parameters.

    Attributes:
        DEFAULT: Initial state, parameter has default value
        CHANGED: Parameter value has been changed
        PRELIM_CALIBRATED: Parameter has been preliminarily calibrated
        CALIBRATED: Parameter has been fully calibrated
        CHECKED: Parameter has been checked for correctness
        COMPLETED: Parameter calibration is complete and verified
    """

    DEFAULT = 0
    CHANGED = 1
    PRELIM_CALIBRATED = 2
    CALIBRATED = 3
    CHECKED = 4
    COMPLETED = 5


def dimension(obj: Any, axis: str = "X") -> int:
    """Get the dimension of a calibration object along a specific axis.

    Args:
        obj: Calibration object (Curve, Map, etc.)
        axis: Axis identifier ("X", "Y", "Z", etc.)

    Returns:
        Number of points along the specified axis
    """
    if hasattr(obj, "axes"):
        for ax in obj.axes:
            if ax.name.upper() == axis.upper():
                if hasattr(ax, "phys") and hasattr(ax.phys, "__len__"):
                    return len(ax.phys)
    return 0


def xdimension(obj: Any) -> int:
    """Get the dimension of a calibration object along the X axis.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        Number of points along the X axis
    """
    return dimension(obj, "X")


def ydimension(obj: Any) -> int:
    """Get the dimension of a calibration object along the Y axis.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        Number of points along the Y axis
    """
    return dimension(obj, "Y")


def zdimension(obj: Any) -> int:
    """Get the dimension of a calibration object along the Z axis.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        Number of points along the Z axis
    """
    return dimension(obj, "Z")


def axis(obj: Any, index: int = 0) -> Optional[Any]:
    """Get a specific axis from a calibration object by index.

    Args:
        obj: Calibration object (Curve, Map, etc.)
        index: Index of the axis to retrieve

    Returns:
        The axis object or None if not found
    """
    if hasattr(obj, "axes") and len(obj.axes) > index:
        return obj.axes[index]
    return None


def xaxis(obj: Any) -> Optional[Any]:
    """Get the X axis from a calibration object.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        The X axis object or None if not found
    """
    return axis(obj, 0)


def yaxis(obj: Any) -> Optional[Any]:
    """Get the Y axis from a calibration object.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        The Y axis object or None if not found
    """
    return axis(obj, 1)


def zaxis(obj: Any) -> Optional[Any]:
    """Get the Z axis from a calibration object.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        The Z axis object or None if not found
    """
    return axis(obj, 2)


def phys(obj: Any) -> Any:
    """Get the physical values from a calibration object.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        Physical values of the calibration object
    """
    return obj.phys if hasattr(obj, "phys") else None


def raw(obj: Any) -> Any:
    """Get the raw values from a calibration object.

    Args:
        obj: Calibration object (Curve, Map, etc.)

    Returns:
        Raw values of the calibration object
    """
    return obj.raw if hasattr(obj, "raw") else None


class CalibrationData:
    """Fetch calibration parameters from HEX file or XCP slave and create an in-memory representation.

    This class provides methods for loading, validating, and manipulating calibration data
    from various sources (HEX files, XCP slaves). It serves as a base class for more specific
    calibration data handlers.

    Args:
        asam_mc: ASAM MC object providing access to A2L data

    Note:
        This is meant as a base-class for CDF, DCM, etc.
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

    def close(self) -> None:
        """Close the connection to the ASAM MC object."""
        self.asam_mc.close()

    @property
    def session(self) -> Any:
        """Get the database session from the ASAM MC object.

        Returns:
            Database session for executing queries
        """
        return self.asam_mc.session

    @property
    def query(self) -> Any:
        """Get the query object from the ASAM MC object.

        Returns:
            Query object for building database queries
        """
        return self.asam_mc.query

    def get_memory_ranges(self) -> list[McObject]:
        """Get memory blocks/ranges relevant for calibration.

        This method identifies all memory regions that contain calibration data,
        including EPK (if present), axis points, and characteristics.

        Returns:
            List of memory objects representing continuous memory blocks
        """
        result = []

        # Add EPK (Electronic Product Key) if present
        a2l_epk = self.epk.from_a2l()
        if a2l_epk:
            epk_addr, epk_len = self.epk.epk_address_and_length()
            result.append(McObject("EPK", epk_addr, 0, epk_len, ""))

        # Add all axis points
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(ax.name, ax.address, 0, mem_size, ""))

        # Add all characteristics
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))

        # Optimize by merging adjacent memory blocks
        blocks = make_continuous_blocks(result)
        return blocks

    def validate_image(self, image: Image, cs_length: int = 128) -> None:
        """Validate an image by comparing checksums with the XCP slave.

        This method verifies the integrity of a memory image by calculating checksums
        for each block and comparing them with checksums calculated by the XCP slave.

        Args:
            image: Memory image to validate
            cs_length: Length of each checksum block in bytes
        """
        for section in image.sections:
            offset = 0
            section_length = len(section)
            remaining_bytes = section_length % cs_length
            block_count = section_length // cs_length

            # Process full-sized blocks
            for idx in range(block_count):
                address = section.address + offset
                block = section.data[offset : offset + cs_length]
                self.asam_mc.xcp_master.setMta(address, 0)
                xcp_checksum = self.asam_mc.xcp_master.buildChecksum(cs_length)
                checksum = check(block, str(xcp_checksum.checksumType))
                equal = checksum == xcp_checksum.checksum
                self.logger.info(f"Address: 0x{address:08X} XCPChecksum {xcp_checksum.checksum} Checksum: {checksum} ==> {equal}")
                offset += cs_length

            # Process remaining bytes (partial block)
            if remaining_bytes > 0:
                block = section.data[offset : offset + remaining_bytes]
                address = section.address + offset
                self.asam_mc.xcp_master.setMta(address, 0)
                xcp_checksum = self.asam_mc.xcp_master.buildChecksum(remaining_bytes)
                checksum = check(block, str(xcp_checksum.checksumType))
                equal = checksum == xcp_checksum.checksum
                self.logger.info(f"Address: 0x{address:08X} XCPChecksum {xcp_checksum.checksum} Checksum: {checksum} ==> {equal}")

    # Keep the old method name for backward compatibility
    validata_image = validate_image

    def get_image_from_xcp(self) -> Image:
        """Get a memory image from the XCP slave.

        This method retrieves all calibration data from the XCP slave and creates
        a memory image containing the data.

        Returns:
            Memory image containing the calibration data
        """
        sections = []

        # Get memory ranges to fetch
        blocks = self.get_memory_ranges()

        # Connect to XCP slave
        self.asam_mc.xcp_connect()

        # Calculate total size for logging
        total_size = functools.reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching {total_size / 1024:.2f} KBytes calibration data from XCP slave.")

        # Process each memory block
        num_blocks = len(blocks)
        for idx in range(num_blocks):
            block = blocks[idx]

            # Adjust length to multiples of 4 (for double-word checksum types)
            adj_length = adjust_to_word_boundary(block.length, 2)

            # Determine actual length to fetch (avoid overlapping with next block)
            if idx < num_blocks - 1:
                dist = blocks[idx + 1].address - block.address
                length = min(dist, adj_length)
            else:
                length = adj_length

            # Fetch data from XCP slave
            self.asam_mc.xcp_master.setMta(block.address, block.ext)
            data = self.asam_mc.xcp_master.pull(length)

            # Add section to the list
            sections.append(Section(block.address, data))

        # Create and return the image
        return Image(sections)

    def load_hex(self) -> None:
        """Load all calibration parameters from the current image.

        This method loads all types of calibration parameters (axis points, values,
        ASCII strings, value blocks, curves, maps, and cubes) from the current image
        and generates a calibration log.
        """
        # Load all types of calibration parameters
        self._load_axis_pts()
        self._load_values()
        self._load_asciis()
        self._load_value_blocks()
        self._load_curves()
        self._load_maps()
        self._load_cubes()

        # Generate and save calibration log
        calibration_log = klasses.dump_characteristics(self._parameters)
        file_name = self.asam_mc.generate_filename(".json")
        file_name = self.asam_mc.sub_dir("logs") / file_name
        self.logger.info(f"Writing calibration log to {file_name!s}")
        with open(file_name, "wb") as of:
            of.write(calibration_log)

        # Import parameters to database
        from asamint.cdf.importer import DBImporter

        imp = DBImporter("test_db", self._parameters, self.logger)
        imp.run()
        imp.close()

        # Generate memory map file
        mm = MapFile("test_db.map", self.memory_map, self.memory_errors)
        mm.run()

    def load_hex_file(self, xcp_master: Any = None, hexfile: Optional[str] = None, hexfile_type: str = "ihex") -> None:
        """Load a hex file or get calibration data from XCP slave.

        This method loads calibration data either from a hex file or directly from an XCP slave.

        Args:
            xcp_master: XCP master object for communication with the ECU. If provided,
                        data will be fetched from the XCP slave instead of a hex file.
            hexfile: Path to the hex file to load. If None and xcp_master is None,
                     the master hexfile from the configuration will be used.
            hexfile_type: Type of hex file ("ihex" or "srec")

        Raises:
            ValueError: If the resulting calibration image is empty
        """
        if xcp_master:
            # Get data from XCP slave
            self.check_epk_xcp(xcp_master)
            self.image = self.upload_parameters(xcp_master)
            self.logger.info("Using image from XCP slave.")
        else:
            # Load from hex file
            if not hexfile:
                # Use default from configuration
                hexfile = self.config.general.master_hexfile
                hexfile_type = self.config.general.master_hexfile_type

            # Open and load the hex file
            with open(f"{hexfile}", "rb") as inf:
                self.logger.info(f"Loading characteristics from {hexfile!r}.")
                self.image = load(hexfile_type, inf)

        # Validate the image
        if not self.image:
            raise ValueError("Empty calibration image.")

        # Create the calibration API object
        self.api = api.Calibration(self.asam_mc, self.image, self._parameters, self.logger)

    def load_characteristics(self, xcp_master: Any = None, hexfile: Optional[str] = None, hexfile_type: str = "ihex") -> None:
        """Load a hex file or get calibration data from XCP slave and process all characteristics.

        This method loads calibration data either from a hex file or directly from an XCP slave,
        then processes all characteristics by calling load_hex().

        Args:
            xcp_master: XCP master object for communication with the ECU. If provided,
                        data will be fetched from the XCP slave instead of a hex file.
            hexfile: Path to the hex file to load. If None and xcp_master is None,
                     the master hexfile from the configuration will be used.
            hexfile_type: Type of hex file ("ihex" or "srec")

        Raises:
            ValueError: If the resulting calibration image is empty

        Note:
            This method is similar to load_hex_file() but also calls load_hex() to process
            all characteristics after loading the image.
        """
        # Load the hex file or get data from XCP slave (same as load_hex_file)
        if xcp_master:
            # Get data from XCP slave
            self.check_epk_xcp(xcp_master)
            self.image = self.upload_parameters(xcp_master)
            self.logger.info("Using image from XCP slave.")
        else:
            # Load from hex file
            if not hexfile:
                # Use default from configuration
                hexfile = self.config.general.master_hexfile
                hexfile_type = self.config.general.master_hexfile_type

            # Open and load the hex file
            with open(f"{hexfile}", "rb") as inf:
                self.logger.info(f"Loading characteristics from {hexfile!r}.")
                self.image = load(hexfile_type, inf)

        # Validate the image
        if not self.image:
            raise ValueError("Empty calibration image.")

        # Create the calibration API object
        self.api = api.Calibration(self.asam_mc, self.image, self._parameters, self.logger)

        # Process all characteristics
        self.load_hex()

    def upload_calram(self, xcp_master: Any, file_type: str = "ihex") -> Optional[Image]:
        """Transfer RAM segments from ECU to MCS (Measurement, Calibration, and Stimulation).

        This method reads all RAM segments from the ECU and saves them to a hex file.

        Args:
            xcp_master: XCP master object for communication with the ECU
            file_type: Type of hex file to create ("ihex" or "srec")

        Returns:
            Image object containing the RAM segments, or None if no RAM segments are defined

        Raises:
            ValueError: If file_type is not "ihex" or "srec"

        Note:
            Depending on your calibration concept, CalRAM may or may not cover all of your parameters.
            See upload_parameters() for a more comprehensive approach.
        """
        # Validate file type
        if file_type:
            file_type = file_type.lower()
        if file_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")

        # Find RAM segments in the module parameters
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

        # Return if no RAM segments are defined
        if not ram_segments:
            return None  # ECU program doesn't define any RAM segments

        # Set calibration page (TODO: Use paging information from IF_DATA section)
        sections = []
        xcp_master.setCalPage(0x83, 0, 0)
        page = 0

        # Read each RAM segment
        for addr, size in ram_segments:
            xcp_master.setMta(addr)
            mem = xcp_master.pull(size)
            sections.append(Section(start_address=addr, data=mem))

        # Create image from sections
        img = Image(sections=sections, join=False)

        # Save to file
        file_name = f'CalRAM{current_timestamp()}_P{page}.{"hex" if file_type == "ihex" else "srec"}'
        file_name = self.asam_mc.sub_dir("hexfiles") / file_name
        with open(f"{file_name}", "wb") as outf:
            dump(file_type, outf, img, row_length=32)
        self.logger.info(f"CalRAM written to {file_name}")

        return img

    def download_calram(self, xcp_master: Any, module_name: Optional[str] = None, data: Optional[bytes] = None) -> None:
        """Transfer RAM segments from MCS (Measurement, Calibration, and Stimulation) to ECU.

        This method writes data to the RAM segment of the ECU.

        Args:
            xcp_master: XCP master object for communication with the ECU
            module_name: Name of the module to download to
            data: Data to write to the RAM segment

        Returns:
            None

        Note:
            If data is None, this method does nothing.
        """
        # Return if no data to download
        if not data:
            return

        # Verify EPK before downloading
        self.check_epk_xcp(xcp_master)

        # Get module parameters
        mp = ModPar(self.session, module_name or None)

        # Get the first memory segment (assuming it's the one we want)
        segment = mp.memorySegments[0]

        # Write data to RAM segment
        if segment["memoryType"] == "RAM":
            xcp_master.setMta(segment["address"])
            xcp_master.push(data)
            self.logger.info(f"Downloaded {len(data)} bytes to RAM at address 0x{segment['address']:X}")
        else:
            self.logger.warning(f"Segment {segment['name']} is not RAM type, skipping download")

    def upload_parameters(self, xcp_master: Any, save_to_file: bool = True, hexfile_type: str = "ihex") -> Image:
        """Upload all calibration parameters from the ECU.

        This method retrieves all calibration parameters from the ECU, including EPK,
        axis points, and characteristics, and optionally saves them to a hex file.

        Args:
            xcp_master: XCP master object for communication with the ECU
            save_to_file: Whether to save the parameters to a hex file
            hexfile_type: Type of hex file to create ("ihex" or "srec")

        Returns:
            Image object containing all calibration parameters

        Raises:
            ValueError: If hexfile_type is not "ihex" or "srec"
        """
        # Validate hex file type
        if hexfile_type:
            hexfile_type = hexfile_type.lower()
        if hexfile_type not in ("ihex", "srec"):
            raise ValueError("'hexfile_type' must be either 'ihex' or 'srec'")

        # Collect all memory objects to upload
        result = []

        # Add EPK (Electronic Product Key) if present
        a2l_epk = self.epk.from_a2l()
        if a2l_epk:
            epk, address = a2l_epk
            result.append(McObject("EPK", address, 0, len(epk), ""))

        # Add all axis points
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(ax.name, ax.address, 0, mem_size, ""))

        # Add all characteristics
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))

        # Optimize by merging adjacent memory blocks
        blocks = make_continuous_blocks(result)

        # Calculate total size for logging
        total_size = functools.reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching a total of {total_size / 1024:.2f} KBytes from XCP slave")

        # Upload each memory block
        sections = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address=block.address, data=mem[: block.length]))

        # Create image from sections
        img = Image(sections=sections, join=True)

        # Save to file if requested
        if save_to_file:
            file_name = f'CalParams{current_timestamp()}.{"hex" if hexfile_type == "ihex" else "srec"}'
            file_name = self.asam_mc.sub_dir("hexfiles") / file_name
            with open(f"{file_name}", "wb") as outf:
                dump(hexfile_type, outf, img, row_length=32)
            self.logger.info(f"CalParams written to {file_name}")

        return img

    def _load_asciis(self) -> None:
        """Load all ASCII string characteristics from the current image.

        This method loads all ASCII string characteristics from the current image
        and stores them in the parameters dictionary.
        """
        self.logger.info("Loading ASCII string characteristics")
        for characteristic in self.characteristics("ASCII"):
            self.logger.debug(f"Processing ASCII '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["ASCII"][characteristic.name] = self.api.load_ascii(characteristic.name)

    def _load_value_blocks(self) -> None:
        """Load all value block characteristics from the current image.

        This method loads all value block characteristics from the current image
        and stores them in the parameters dictionary.
        """
        self.logger.info("Loading value block characteristics")
        for characteristic in self.characteristics("VAL_BLK"):
            self.logger.debug(f"Processing VAL_BLK '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["VAL_BLK"][characteristic.name] = self.api.load_value_block(characteristic.name)

    def _load_values(self) -> None:
        """Load all scalar value characteristics from the current image.

        This method loads all scalar value characteristics from the current image
        and stores them in the parameters dictionary.
        """
        self.logger.info("Loading scalar value characteristics")
        for characteristic in self.characteristics("VALUE"):
            self.logger.debug(f"Processing VALUE '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["VALUE"][characteristic.name] = self.api.load_value(characteristic.name)

    def _load_axis_pts(self) -> None:
        """Load all axis points from the current image.

        This method loads all axis points from the current image
        and stores them in the parameters dictionary.
        """
        self.logger.info("Loading axis points")
        for ap in self.axis_points():
            self.logger.debug(f"Processing AXIS_PTS '{ap.name}' @0x{ap.address:08x}")
            self._parameters["AXIS_PTS"][ap.name] = self.api.load_axis_pts(ap.name)

    def _load_curves(self) -> None:
        """Load all curve characteristics from the current image.

        This method loads all curve characteristics from the current image
        and stores them in the parameters dictionary.
        """
        self.logger.info("Loading curve characteristics")
        self._load_curves_and_maps("CURVE", 1)

    def _load_maps(self) -> None:
        """Load all map characteristics from the current image.

        This method loads all map characteristics from the current image
        and stores them in the parameters dictionary.
        """
        self.logger.info("Loading map characteristics")
        self._load_curves_and_maps("MAP", 2)

    def _load_cubes(self) -> None:
        """Load all cube characteristics from the current image.

        This method loads all cube characteristics (CUBOID, CUBE_4, CUBE_5)
        from the current image and stores them in the parameters dictionary.
        """
        self.logger.info("Loading cuboid characteristics")
        self._load_curves_and_maps("CUBOID", 3)
        self.logger.info("Loading 4D cube characteristics")
        self._load_curves_and_maps("CUBE_4", 4)
        self.logger.info("Loading 5D cube characteristics")
        self._load_curves_and_maps("CUBE_5", 5)

    def _order_curves(self, curves: list[Characteristic]) -> list[Characteristic]:
        """Reorder curves to resolve forward references.

        This method reorders a list of curve characteristics to ensure that
        curves referenced by other curves appear before the curves that reference them.

        Args:
            curves: List of curve characteristics to reorder

        Returns:
            Reordered list of curve characteristics
        """
        # Make a copy of the generator to avoid destroying it
        curves = list(curves)[::1]

        # Create a dictionary mapping curve names to their positions and objects
        curves_by_name = {c.name: (pos, c) for pos, c in enumerate(curves)}

        # Reorder curves until no more swaps are needed
        while True:
            ins_pos = 0
            for curr_pos in range(len(curves)):
                curve = curves[curr_pos]
                axis_descr = curve.axisDescriptions[0]

                # Check if this curve references another curve
                if axis_descr.attribute == "CURVE_AXIS":
                    if axis_descr.curveAxisRef.name in curves_by_name:
                        ref_pos, ref_curve = curves_by_name.get(axis_descr.curveAxisRef.name)

                        # If the referenced curve appears after this curve, swap them
                        if ref_pos > curr_pos:
                            # Swap the curves
                            t_curve = curves[ins_pos]
                            curves[ins_pos] = curves[ref_pos]
                            curves[ref_pos] = t_curve

                            # Update the position dictionary
                            curves_by_name[curves[ins_pos].name] = (
                                ins_pos,
                                curves[ins_pos],
                            )
                            curves_by_name[curves[ref_pos].name] = (
                                ref_pos,
                                curves[ref_pos],
                            )
                            ins_pos += 1

            # If no swaps were made, we're done
            if ins_pos == 0:
                break

        return curves

    def _load_curves_and_maps(self, category: str, num_axes: int) -> None:
        """Load curve or map characteristics from the current image.

        This method loads curve or map characteristics with the specified number of axes
        from the current image and stores them in the parameters dictionary.

        Args:
            category: Category of characteristics to load (CURVE, MAP, CUBOID, etc.)
            num_axes: Number of axes (1 for curves, 2 for maps, etc.)
        """
        # Get all characteristics of the specified category
        characteristics = self.characteristics(category)

        # For curves, we need to handle forward references
        if num_axes == 1:
            # CURVEs may reference other CURVEs, so some ordering is required
            characteristics = self._order_curves(characteristics)

        # Load each characteristic
        for characteristic in characteristics:
            self.logger.debug(f"Processing {category} '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters[f"{category}"][characteristic.name] = self.api.load_curve_or_map(
                characteristic.name, category, num_axes
            )

    def log_memory_errors(self, exc: Exception, memory_type: MemoryType, name: str, address: int, length: int) -> None:
        """Log memory errors for invalid addresses.

        This method logs memory errors when an invalid address is encountered
        during memory access operations.

        Args:
            exc: Exception that occurred during memory access
            memory_type: Type of memory object being accessed
            name: Name of the memory object
            address: Address of the memory object
            length: Length of the memory object in bytes
        """
        if isinstance(exc, InvalidAddressError):
            self.memory_errors[address].append(MemoryObject(memory_type=memory_type, name=name, address=address, length=length))
            self.logger.error(f"Invalid address 0x{address:08X} for {memory_type.name} '{name}'")

    @property
    def parameters(self) -> dict[str, dict[str, Any]]:
        """Get all loaded calibration parameters.

        Returns:
            Dictionary of calibration parameters organized by category
        """
        return self._parameters

    def axis_points(self) -> Generator[AxisPts, None, None]:
        """Get all axis points defined in the A2L file.

        Yields:
            AxisPts objects for each axis points definition
        """
        # Query all axis points ordered by address
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()

        # Yield each axis points object
        for a in axis_pts:
            try:
                ap = AxisPts.get(self.session, a.name)
                yield ap
            except Exception as e:
                self.logger.error(f"Error loading axis points '{a.name}': {e}")
                continue

    def characteristics(self, category: str) -> Generator[Characteristic, None, None]:
        """Get all characteristics of a specific category.

        Args:
            category: Category of characteristics to retrieve (VALUE, CURVE, MAP, etc.)

        Yields:
            Characteristic objects for each characteristic of the specified category
        """
        # Query all characteristics of the specified category
        query = self.query(model.Characteristic.name).filter(model.Characteristic.type == category)

        # Yield each characteristic
        for characteristic in query.all():
            try:
                yield Characteristic.get(self.session, characteristic.name)
            except Exception as e:
                self.logger.error(f"Error loading {category} '{characteristic.name}': {e}")
                continue
