#!/usr/bin/env python
"""Calibration data handling module for ASAM calibration data.

This module provides classes and functions for working with calibration data,
including loading, validating, and manipulating calibration parameters from
HEX files or XCP slaves.
"""

from __future__ import annotations

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2026 by Christoph Schueler <cpu12.gems.googlemail.com>

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

from collections import defaultdict
from collections.abc import Generator
from dataclasses import dataclass
from enum import IntEnum
from functools import reduce
from pathlib import Path
from typing import Any, Optional

from asamint.adapters.a2l import AxisPts, Characteristic, ModPar, model
from asamint.adapters.objutils import Image, InvalidAddressError, Section, dump, load
from asamint.adapters.xcp import (
    CAL_PAGE_MODE_ALL,
    CAL_PAGE_MODE_ECU,
    CAL_PAGE_MODE_XCP,
    McObject,
    PagePropertiesInfo,
    XcpCalibration,
    XcpPage,
    XcpSegment,
    compute_checksum,
    make_continuous_blocks,
)
from asamint.asam import AsamMC
from asamint.calibration import api
from asamint.calibration.api import (
    Calibration,
    ExecutionPolicy,
    OfflineCalibration,
    OnlineCalibration,
    ParameterCache,
    RangeError,
    ReadOnlyError,
    Status,
)
from asamint.calibration.mapfile import MapFile
from asamint.core.exceptions import CalibrationError
from asamint.model.calibration import klasses
from asamint.model.calibration.klasses import MemoryObject, MemoryType
from asamint.utils import adjust_to_word_boundary, current_timestamp, flatten
from pya2l.api.inspect import PrgTypeSegment, MemoryType, SegmentAttributeType


class CalibrationState(IntEnum):
    """Enumeration of possible calibration states for parameters.

    Attributes:
        DEFAULT: Initial state, parameter has default value.
        CHANGED: Parameter value has been changed.
        PRELIM_CALIBRATED: Parameter has been preliminarily calibrated.
        CALIBRATED: Parameter has been fully calibrated.
        CHECKED: Parameter has been checked for correctness.
        COMPLETED: Parameter calibration is complete and verified.
    """

    DEFAULT = 0
    CHANGED = 1
    PRELIM_CALIBRATED = 2
    CALIBRATED = 3
    CHECKED = 4
    COMPLETED = 5


# ---------------------------------------------------------------------------
# Convenience accessors
# ---------------------------------------------------------------------------


def dimension(obj: Any, axis: str = "X") -> int:
    """Get the dimension of a calibration object along a specific axis.

    Args:
        obj: Calibration object (Curve, Map, etc.).
        axis: Axis identifier (``"X"``, ``"Y"``, ``"Z"``, etc.).

    Returns:
        Number of points along the specified axis, or ``0`` if absent.
    """
    if hasattr(obj, "axes"):
        for ax in obj.axes:
            if ax.name.upper() == axis.upper():
                if hasattr(ax, "phys") and hasattr(ax.phys, "__len__"):
                    return len(ax.phys)
    return 0


def xdimension(obj: Any) -> int:
    """Number of points along the X axis."""
    return dimension(obj, "X")


def ydimension(obj: Any) -> int:
    """Number of points along the Y axis."""
    return dimension(obj, "Y")


def zdimension(obj: Any) -> int:
    """Number of points along the Z axis."""
    return dimension(obj, "Z")


def axis(obj: Any, index: int = 0) -> Any | None:
    """Get a specific axis from a calibration object by index.

    Args:
        obj: Calibration object (Curve, Map, etc.).
        index: Zero-based axis index.

    Returns:
        The axis object, or ``None`` if the index is out of range.
    """
    if hasattr(obj, "axes") and len(obj.axes) > index:
        return obj.axes[index]
    return None


def xaxis(obj: Any) -> Any | None:
    """Get the X axis (index 0)."""
    return axis(obj, 0)


def yaxis(obj: Any) -> Any | None:
    """Get the Y axis (index 1)."""
    return axis(obj, 1)


def zaxis(obj: Any) -> Any | None:
    """Get the Z axis (index 2)."""
    return axis(obj, 2)


def phys(obj: Any) -> Any | None:
    """Get the physical values from a calibration object."""
    return obj.phys if hasattr(obj, "phys") else None


def raw(obj: Any) -> Any | None:
    """Get the raw values from a calibration object."""
    return obj.raw if hasattr(obj, "raw") else None


# ---------------------------------------------------------------------------
# Parameter categories used to initialise the parameter dict.
# ---------------------------------------------------------------------------

_PARAMETER_CATEGORIES: tuple[str, ...] = (
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


# ---------------------------------------------------------------------------
# A2L page-access helpers
# ---------------------------------------------------------------------------


def _a2l_access_to_flags(access_str: Any) -> tuple[bool, bool]:
    """Convert an A2L page-access string to ``(with_counterpart, without_counterpart)`` flags.

    A2L uses tokens such as ``ECU_ACCESS_DONT_CARE``, ``XCP_WRITE_ACCESS_WITH_ECU_ONLY``
    and ``XCP_READ_ACCESS_NOT_ALLOWED``.  This function maps them to the two boolean fields
    used by :class:`~asamint.adapters.xcp.PagePropertiesInfo`.

    Args:
        access_str: Raw A2L access token (case-insensitive).

    Returns:
        Tuple ``(with_counterpart, without_counterpart)`` suitable for a
        :class:`~asamint.adapters.xcp.PagePropertiesInfo` pair of fields.
    """
    token = str(access_str).upper()
    if "NOT_ALLOWED" in token:
        return False, False
    if "WITHOUT" in token:
        return False, True
    if "WITH_" in token:  # WITH_ECU_ONLY / WITH_XCP_ONLY (but not WITHOUT)
        return True, False
    # DONT_CARE or unrecognised → allow both
    return True, True


def page_properties_from_a2l(
    ecu_access: Any,
    xcp_read: Any,
    xcp_write: Any,
) -> PagePropertiesInfo:
    """Build a :class:`~asamint.adapters.xcp.PagePropertiesInfo` from A2L IF_DATA access tokens.

    Args:
        ecu_access: A2L ``ECU_ACCESS_*`` token (e.g. ``"ECU_ACCESS_DONT_CARE"``).
        xcp_read:   A2L ``XCP_READ_ACCESS_*`` token.
        xcp_write:  A2L ``XCP_WRITE_ACCESS_*`` token.

    Returns:
        :class:`~asamint.adapters.xcp.PagePropertiesInfo` with all six boolean flags set.
    """
    ecu_with, ecu_without = _a2l_access_to_flags(ecu_access)
    read_with, read_without = _a2l_access_to_flags(xcp_read)
    write_with, write_without = _a2l_access_to_flags(xcp_write)
    return PagePropertiesInfo(
        ecu_access_with_xcp=ecu_with,
        ecu_access_without_xcp=ecu_without,
        xcp_read_access_with_ecu=read_with,
        xcp_read_access_without_ecu=read_without,
        xcp_write_access_with_ecu=write_with,
        xcp_write_access_without_ecu=write_without,
    )


@dataclass(slots=True)
class A2lPageEntry:
    """Structured representation of a single PAGE entry from A2L IF_DATA/XCP/SEGMENT/PAGE.

    Attributes:
        logical_segment: XCP logical segment number (address extension of the SEGMENT block).
        page_number:     XCP page number within the segment.
        properties:      Decoded access-flag flags as :class:`~asamint.adapters.xcp.PagePropertiesInfo`.
    """

    logical_segment: int
    page_number: int
    properties: PagePropertiesInfo


class CalibrationData:
    """Fetch calibration parameters from HEX file or XCP slave and create an in-memory representation.

    This class provides methods for loading, validating, and manipulating
    calibration data from various sources (HEX files, XCP slaves).  It serves
    as a base class for CDF, DCM, and similar exporters.

    Args:
        asam_mc: ASAM MC object providing access to A2L data.

    Note:
        This is meant as a base-class for CDF, DCM, etc.
        Don't use directly.
    """

    def __init__(self, asam_mc: AsamMC, *args: Any, **kws: Any) -> None:
        self.asam_mc = asam_mc
        self.config = asam_mc.config
        self.logger = self.config.log
        self._parameters: dict[str, dict[str, Any]] = {k: {} for k in _PARAMETER_CATEGORIES}
        self.memory_map: defaultdict[int, list[MemoryObject]] = defaultdict(list)
        self.memory_errors: defaultdict[int, list[MemoryObject]] = defaultdict(list)

    # -- Context-manager protocol ------------------------------------------

    def __enter__(self) -> CalibrationData:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection to the ASAM MC object."""
        self.asam_mc.close()

    @property
    def session(self) -> Any:
        """Database session from the ASAM MC object."""
        return self.asam_mc.session

    @property
    def query(self) -> Any:
        """Query callable from the ASAM MC object."""
        return self.asam_mc.query

    # -- Memory layout -----------------------------------------------------

    def get_memory_ranges(self) -> list[McObject]:
        """Identify all ECU memory regions that contain calibration data.

        Returns:
            Merged list of memory objects representing continuous blocks.
        """
        result: list[McObject] = []

        # EPK (Electronic Product Key)
        a2l_epk = self.epk.from_a2l()
        if a2l_epk:
            epk_addr, epk_len = self.epk.epk_address_and_length()
            result.append(McObject("EPK", epk_addr, 0, epk_len, ""))

        # Axis points
        for a in self.query(model.AxisPts).order_by(model.AxisPts.address).all():
            ax = AxisPts.get(self.session, a.name)
            result.append(McObject(ax.name, ax.address, 0, ax.total_allocated_memory, ""))

        # Add all characteristics
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))

        return make_continuous_blocks(result)

    # -- Validation --------------------------------------------------------

    def validate_image(self, image: Image, cs_length: int = 128) -> None:
        """Validate an image by comparing checksums with the XCP slave.

        Iterates over every section in the image, splitting it into
        blocks of *cs_length* bytes and comparing the local checksum
        against the one computed by the ECU.

        Args:
            image: Memory image to validate.
            cs_length: Length of each checksum block in bytes.
        """
        for section in image.sections:
            offset = 0
            section_length = len(section)
            remaining_bytes = section_length % cs_length
            block_count = section_length // cs_length

            # Full-sized blocks
            for _ in range(block_count):
                address = section.address + offset
                block = section.data[offset : offset + cs_length]
                self.asam_mc.xcp_master.setMta(address, 0)
                xcp_checksum = self.asam_mc.xcp_master.buildChecksum(cs_length)
                checksum = compute_checksum(block, str(xcp_checksum.checksumType))
                equal = checksum == xcp_checksum.checksum
                self.logger.info(
                    "Address: 0x%08X XCPChecksum %s Checksum: %s ==> %s",
                    address,
                    xcp_checksum.checksum,
                    checksum,
                    equal,
                )
                offset += cs_length

            # Partial trailing block
            if remaining_bytes > 0:
                address = section.address + offset
                block = section.data[offset : offset + remaining_bytes]
                self.asam_mc.xcp_master.setMta(address, 0)
                xcp_checksum = self.asam_mc.xcp_master.buildChecksum(remaining_bytes)
                checksum = compute_checksum(block, str(xcp_checksum.checksumType))
                equal = checksum == xcp_checksum.checksum
                self.logger.info(
                    "Address: 0x%08X XCPChecksum %s Checksum: %s ==> %s",
                    address,
                    xcp_checksum.checksum,
                    checksum,
                    equal,
                )

    # Backward-compatible typo alias.
    validata_image = validate_image

    # -- XCP upload / download ---------------------------------------------

    def get_image_from_xcp(self) -> Image:
        """Retrieve all calibration data from the XCP slave.

        Returns:
            Memory image containing the calibration data.
        """
        blocks = self.get_memory_ranges()
        self.asam_mc.xcp_connect()

        total_size = sum(b.length for b in blocks)
        self.logger.info(
            "Fetching %.2f KBytes calibration data from XCP slave.",
            total_size / 1024,
        )

        sections: list[Section] = []
        num_blocks = len(blocks)
        for idx in range(num_blocks):
            block = blocks[idx]
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

    # -- HEX loading -------------------------------------------------------

    def check_epk_xcp(self, xcp_master: Any) -> bool | None:
        """Compare EPK from A2L with EPK from ECU."""
        return self.asam_mc.epk.check_epk_xcp(xcp_master)

    def _prepare_image(
        self,
        xcp_master: Any | None,
        hexfile: str | Path | None,
        hexfile_type: str,
        *,
        join_sections: bool = False,
    ) -> Image:
        """Load or upload a calibration image.

        Common logic shared by :meth:`load_hex_file` and
        :meth:`load_characteristics`.

        Args:
            xcp_master: XCP master – if given, data is fetched from the slave.
            hexfile: Path to the hex file; ``None`` falls back to config.
            hexfile_type: ``"ihex"`` or ``"srec"``.
            join_sections: Whether to merge adjacent sections in the image.

        Returns:
            Loaded or uploaded :class:`Image`.

        Raises:
            CalibrationError: If the resulting image is empty.
        """
        if xcp_master:
            self.check_epk_xcp(xcp_master)
            image = self.upload_parameters(xcp_master)
            self.logger.info("Using image from XCP slave.")
        else:
            if not hexfile:
                hexfile = Path(self.config.general.master_hexfile).absolute()
                hexfile_type = self.config.general.master_hexfile_type
            hex_path = Path(hexfile)
            self.logger.info("Loading characteristics from %r.", str(hex_path))
            with hex_path.open("rb") as inf:
                image = load(hexfile_type, inf)
            if join_sections:
                image.join_sections()

        if not image:
            raise CalibrationError("Empty calibration image.")
        return image

    def load_hex(self) -> None:
        """Load all calibration parameters from the current image.

        Processes axis points, values, ASCII strings, value blocks,
        curves, maps, and cubes; then writes a calibration JSON log and
        imports into the MSRSW + HDF5 databases.
        """
        self._load_axis_pts()
        self._load_values()
        self._load_asciis()
        self._load_value_blocks()
        self._load_curves()
        self._load_maps()
        self._load_cubes()

        # Calibration log
        calibration_log = klasses.dump_characteristics(self._parameters)
        log_path = self.asam_mc.sub_dir("logs") / self.asam_mc.generate_filename(".json")
        self.logger.info("Writing calibration log to %s", log_path)
        log_path.write_bytes(calibration_log)

        # Database import
        from asamint.cdf.importer import DBImporter

        db_name = self.asam_mc.generate_filename(None)
        imp = DBImporter(db_name, self._parameters, self.logger)
        imp.run()
        imp.close()

        # Memory map file
        map_name = self.asam_mc.generate_filename(".map")
        mm = MapFile(
            self.asam_mc.session,
            map_name,
            self.asam_mc.calibration_memory_map,
            self.memory_errors,
        )
        mm.run()

    def load_hex_file(
        self,
        xcp_master: Any | None = None,
        hexfile: str | Path | None = None,
        hexfile_type: str = "ihex",
    ) -> None:
        """Load a hex file or fetch calibration data from an XCP slave.

        Args:
            xcp_master: XCP master object.  If provided, data is fetched
                from the XCP slave instead of a hex file.
            hexfile: Path to the hex file.  ``None`` falls back to the
                master hexfile from the configuration.
            hexfile_type: ``"ihex"`` or ``"srec"``.

        Raises:
            CalibrationError: If the resulting image is empty.
        """
        self.image = self._prepare_image(xcp_master, hexfile, hexfile_type)
        self.api = api.Calibration(
            self.asam_mc,
            self.image,
            self._parameters,
            self.logger,
        )

    def load_characteristics(
        self,
        xcp_master: Any | None = None,
        hexfile: str | Path | None = None,
        hexfile_type: str = "ihex",
    ) -> None:
        """Load a hex file (or XCP data) and process all characteristics.

        Same as :meth:`load_hex_file` followed by :meth:`load_hex`.

        Args:
            xcp_master: XCP master object.
            hexfile: Path to the hex file.
            hexfile_type: ``"ihex"`` or ``"srec"``.

        Raises:
            CalibrationError: If the resulting image is empty.
        """
        self.image = self._prepare_image(
            xcp_master,
            hexfile,
            hexfile_type,
            join_sections=True,
        )
        self.api = api.Calibration(
            self.asam_mc,
            self.image,
            self._parameters,
            self.logger,
        )

        # Validate the image
        if not self.image:
            raise ValueError("Empty calibration image.")

        # Create the calibration API object
        self.api = api.Calibration(self.asam_mc, self.image, self._parameters, self.logger)

        # Process all characteristics
        self.load_hex()

    # -- CalRAM upload / download ------------------------------------------

    def upload_calram(self, xcp_master: Any, file_type: str = "ihex") -> Optional[Image]:
        """Transfer RAM segments from ECU to MCS (Measurement, Calibration, and Stimulation).

        Reads all RAM segments from the ECU and saves them to a hex file.

        Args:
            xcp_master: XCP master object.
            file_type: ``"ihex"`` or ``"srec"``.
        """
        if file_type:
            file_type = file_type.lower()
        if file_type not in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")

        mod_par = self.asam_mc.mod_par
        calram_segments = self._get_calram_segments(mod_par)
        if not calram_segments:
            return None

        sections: list[Section] = []
        selected_pages: list[int] = []

        for segment in calram_segments:
            logical_segment, page = self._select_cal_page(segment, prefer_write=True)
            selected_pages.append(page)
            xcp_master.setCalPage(0x03, logical_segment, page)
            xcp_master.setMta(segment.address)
            mem = xcp_master.pull(segment.size)
            sections.append(Section(start_address=segment.address, data=mem))

        img = Image(sections=sections, join=False)

        page_label = self._format_page_label(selected_pages)
        ext = "hex" if file_type == "ihex" else "srec"
        file_name = self.asam_mc.sub_dir("hexfiles") / f"CalRAM{current_timestamp()}_P{page_label}.{ext}"
        with file_name.open("wb") as outf:
            dump(file_type, outf, img, row_length=32)
        self.logger.info("CalRAM written to %s", file_name)

        return img

    @staticmethod
    def _segment_memory_type_name(segment: Any) -> str:
        """Return the memory-type name of a segment, or ``""``."""
        memory_type = getattr(segment, "memoryType", None)
        if memory_type is None:
            return ""
        return getattr(memory_type, "name", str(memory_type))

    @classmethod
    def _is_calram_segment(cls, segment: Any) -> bool:
        """Decide whether *segment* is a calibration RAM segment."""
        return (
            cls._segment_memory_type_name(segment) == "RAM"
            or getattr(segment, "name", "") == "CALRAM"
            or bool(cls._extract_segment_pages(segment))
        )

    @classmethod
    def _get_calram_segments(cls, mod_par: Any) -> list[Any]:
        return [segment for segment in getattr(mod_par, "memorySegments", []) if cls._is_calram_segment(segment)]

    @staticmethod
    def _extract_segment_pages(segment: Any) -> list[A2lPageEntry]:
        """Parse ``IF_DATA/XCP/SEGMENT/PAGE`` entries from an A2L memory segment.

        Handles two formats:

        * **pya2l model format** – ``segment.if_data`` carries a ``.flatmap`` attribute.
        * **Plain list/dict format** – used by unit tests and raw IF_DATA structures.

        Args:
            segment: A2L memory segment object (real pya2l model or test stub).

        Returns:
            List of :class:`A2lPageEntry` objects, one per PAGE definition.
        """
        if_data = getattr(segment, "if_data", None) or []

        if hasattr(if_data, "flatmap"):
            return CalibrationData._entries_from_flatmap(if_data)

        if isinstance(if_data, list):
            return CalibrationData._entries_from_dict(if_data)

        return []

    @staticmethod
    def _entries_from_flatmap(if_data: Any) -> list[A2lPageEntry]:
        """Build :class:`A2lPageEntry` list from a pya2l ORM flatmap object.

        The pya2l flatmap ``PAGE`` value is a list-of-lists where each inner entry
        has the form ``(logical_segment, page_num, ecu_access, xcp_read[, xcp_write])``.
        """
        entries: list[A2lPageEntry] = []
        raw_segment: list[Any] = if_data.flatmap.get("SEGMENT") or []
        raw_pages: list[Any] = if_data.flatmap.get("PAGE") or []
        if not raw_segment or not raw_pages:
            return entries
        segment = raw_segment[0]
        logical_seg = segment[0] if len(segment) > 0 else 0
        for raw in raw_pages[0]:
            if not isinstance(raw, (list, tuple)) or len(raw) < 4:
                continue
            # logical_seg = 0
            page_num, ecu_acc, xcp_r, xcp_w = raw[:4]
            # logical_seg = int(raw[0])
            page_num = int(raw[0])
            ecu_acc = raw[1]
            xcp_r = raw[2]
            xcp_w = raw[3]
            entries.append(
                A2lPageEntry(
                    logical_segment=logical_seg,
                    page_number=page_num,
                    properties=page_properties_from_a2l(ecu_acc, xcp_r, xcp_w),
                )
            )
        return entries

    @staticmethod
    def _entries_from_dict(if_data: list[Any]) -> list[A2lPageEntry]:
        """Build :class:`A2lPageEntry` list from a plain list/dict IF_DATA structure.

        Expected structure::

            [{"XCP": [{"SEGMENT": [seg_num, addr_ext, ..., {"PAGE": [...]}]}]}]
        """
        entries: list[A2lPageEntry] = []
        for item in if_data:
            if not isinstance(item, dict):
                continue
            for xcp_block in item.get("XCP") or []:
                if not isinstance(xcp_block, dict):
                    continue
                entries.extend(CalibrationData._entries_from_segment_block(xcp_block))
        return entries

    @staticmethod
    def _entries_from_segment_block(xcp_block: dict[str, Any]) -> list[A2lPageEntry]:
        """Parse one ``SEGMENT`` block within an XCP IF_DATA dict."""
        entries: list[A2lPageEntry] = []
        seg_data = xcp_block.get("SEGMENT")
        if not isinstance(seg_data, (list, tuple)) or len(seg_data) < 2:
            return entries
        # SEGMENT layout: [seg_number, address_extension, compress, encrypt, max_map, {"PAGE": [...]}]
        logical_seg = int(seg_data[1])
        for part in seg_data:
            if not isinstance(part, dict) or "PAGE" not in part:
                continue
            for page_entry in part["PAGE"]:
                entry = CalibrationData._parse_page_entry(logical_seg, page_entry)
                if entry is not None:
                    entries.append(entry)
        return entries

    @staticmethod
    def _parse_page_entry(logical_seg: int, page_entry: Any) -> A2lPageEntry | None:
        """Convert a raw PAGE list ``[num, ecu, xcp_read, xcp_write]`` to :class:`A2lPageEntry`."""
        if not isinstance(page_entry, (list, tuple)) or not page_entry:
            return None
        page_num = int(page_entry[0])
        ecu_acc = page_entry[1] if len(page_entry) > 1 else "ECU_ACCESS_DONT_CARE"
        xcp_r = page_entry[2] if len(page_entry) > 2 else "XCP_READ_ACCESS_DONT_CARE"
        xcp_w = page_entry[3] if len(page_entry) > 3 else "XCP_WRITE_ACCESS_DONT_CARE"
        return A2lPageEntry(
            logical_segment=logical_seg,
            page_number=page_num,
            properties=page_properties_from_a2l(ecu_acc, xcp_r, xcp_w),
        )

    @staticmethod
    def _page_access_allowed(access: Any) -> bool:
        """Check whether a raw A2L page-access flag string permits the operation.

        .. deprecated::
            Prefer :func:`page_properties_from_a2l` and the
            :class:`~asamint.adapters.xcp.PagePropertiesInfo` helper properties.
        """
        return "NOT_ALLOWED" not in str(access)

    @classmethod
    def _select_cal_page(cls, segment: Any, *, prefer_write: bool) -> tuple[int, int]:
        """Choose the best calibration page from an A2L memory segment.

        Selection priority (when *prefer_write* is ``True``):

        1. First page whose :attr:`~asamint.adapters.xcp.PagePropertiesInfo.xcp_write_access`
           is ``True``.
        2. First page whose :attr:`~asamint.adapters.xcp.PagePropertiesInfo.xcp_read_access`
           is ``True``.
        3. The first page defined in the segment (fallback).

        When *prefer_write* is ``False``, step 1 is skipped.

        Args:
            segment:      A2L memory segment object.
            prefer_write: If ``True``, prefer a page that allows XCP write access.

        Returns:
            ``(logical_segment, page_number)`` tuple for use with ``SET_CAL_PAGE``.
        """
        pages = cls._extract_segment_pages(segment)
        if not pages:
            return 0, 0

        if prefer_write:
            for entry in pages:
                if entry.properties.xcp_write_access:
                    return entry.logical_segment, entry.page_number

        for entry in pages:
            if entry.properties.xcp_read_access:
                return entry.logical_segment, entry.page_number

        first = pages[0]
        return first.logical_segment, first.page_number

    @staticmethod
    def _format_page_label(selected_pages: list[int]) -> str:
        """Build a human-readable page label from the selection."""
        if not selected_pages:
            return "0"
        unique_pages = list(dict.fromkeys(selected_pages))
        return "-".join(str(p) for p in unique_pages)

    def create_xcp_calibration(self, xcp_master: Any) -> Any:
        """Create an XCP :class:`~pyxcp.master.calibration.Calibration` paging manager.

        The returned object provides a high-level interface for segment/page
        management (``set_page``, ``get_page``, ``copy_page``, ``set_freeze_mode``,
        ``save_all``, …) backed by the pyXCP ``Calibration`` class.

        The manager is **pre-populated** from the A2L IF_DATA SEGMENT/PAGE
        definitions so that access-flag validation (via
        :class:`~asamint.adapters.xcp.PagePropertiesInfo`) works even before a
        live ``refresh()`` call against the ECU.  If you want up-to-date ECU
        state, call ``manager.refresh()`` afterwards.

        Args:
            xcp_master: A connected pyXCP ``Master`` instance.

        Returns:
            A :class:`~pyxcp.master.calibration.Calibration` instance seeded with
            A2L segment data.  Returns ``None`` when the installed pyxcp version
            does not provide the ``Calibration`` class.

        Example::

            with create_master(config) as master:
                cal = calibration_data.create_xcp_calibration(master)
                cal.set_xcp_page(segment=0, page=1)
                # …work on the RAM page…
                cal.save_all()
        """
        if XcpCalibration is None or XcpPage is None or XcpSegment is None:
            self.logger.warning(
                "XcpCalibration is not available in the installed pyxcp version; upgrade pyxcp to use the full paging API."
            )
            return None

        cal: Any = XcpCalibration(xcp_master)

        mod_par = getattr(self.asam_mc, "mod_par", None)
        if mod_par is None:
            return cal

        for segment in getattr(mod_par, "memorySegments", []):
            page_entries = self._extract_segment_pages(segment)
            if not page_entries:
                continue

            logical_seg = page_entries[0].logical_segment

            xcp_pages: dict[int, Any] = {
                entry.page_number: XcpPage(
                    segment_number=logical_seg,
                    page_number=entry.page_number,
                    properties=entry.properties,
                )
                for entry in page_entries
            }

            xcp_segment: Any = XcpSegment(
                number=logical_seg,
                max_pages=len(xcp_pages),
                address_extension=logical_seg,
                max_mapping=0,
                compression_method=0,
                encryption_method=0,
                pages=xcp_pages,
                address=getattr(segment, "address", None),
                length=getattr(segment, "size", None),
            )
            cal.segments[logical_seg] = xcp_segment
            self.logger.debug(
                "A2L segment → XCP segment %d: %d page(s) pre-loaded from IF_DATA.",
                logical_seg,
                len(xcp_pages),
            )

        if cal.segments:
            cal.max_segments = len(cal.segments)
            cal._initialized = True

        return cal

    def download_calram(
        self,
        xcp_master: Any,
        module_name: str | None = None,
        data: bytes | None = None,
    ) -> None:
        """Transfer RAM segments from MCS to ECU.

        Args:
            xcp_master: XCP master object.
            module_name: Name of the module to download to.
            data: Data to write to the RAM segment.
        """
        if not data:
            return

        self.check_epk_xcp(xcp_master)

        mp = ModPar(self.session, module_name or None)
        segments = self._get_calram_segments(mp)
        if not segments:
            self.logger.warning("No calibration segment found for download")
            return
        segment = segments[0]

        logical_segment, page = self._select_cal_page(segment, prefer_write=True)
        xcp_master.setCalPage(0x83, logical_segment, page)
        if self._is_calram_segment(segment):
            xcp_master.setMta(segment.address)
            xcp_master.push(data)
            self.logger.info(f"Downloaded {len(data)} bytes to RAM at address 0x{segment.address:X}")
        else:
            self.logger.warning(f"Segment {segment.name} is not RAM type, skipping download")

    def upload_segments(self) -> Optional[Path]:
        result = []
        segments = self.asam_mc.mod_par.memorySegments
        if not segments:
            return None
        for segment in segments:
            if segment.prgType == PrgTypeSegment.CODE:
                continue
            address = segment.address
            name = segment.name
            self.asam_mc.xcp_master.setMta(address)
            print(f"Fetching segment {name} at address 0x{address:X} {segment.size} bytes")
            data = self.asam_mc.xcp_master.pull(segment.size)
            result.append((name, data))
        return result

    def upload_parameters(self, xcp_master: Any, save_to_file: bool = True, hexfile_type: str = "ihex") -> Image:
        """Upload all calibration parameters from the ECU.

        Args:
            xcp_master: XCP master object.
            save_to_file: Whether to save the result to a hex file.
            hexfile_type: ``"ihex"`` or ``"srec"``.

        Returns:
            Image containing all calibration parameters.

        Raises:
            ValueError: If *hexfile_type* is invalid.
        """
        if hexfile_type:
            hexfile_type = hexfile_type.lower()
        if hexfile_type not in ("ihex", "srec"):
            raise ValueError("'hexfile_type' must be either 'ihex' or 'srec'")

        result: list[McObject] = []

        for a in self.query(model.AxisPts).order_by(model.AxisPts.address).all():
            ax = AxisPts.get(self.session, a.name)
            result.append(McObject(ax.name, ax.address, 0, ax.total_allocated_memory, ""))

        # Add all characteristics
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            characteristic = Characteristic.get(self.session, c.name)
            if characteristic is None:
                self.logger.warning("Characteristic %s not found", c.name)
                continue
            result.append(McObject(characteristic.name, characteristic.address, 0, characteristic.total_allocated_memory, ""))
            mem_size = characteristic.total_allocated_memory
            result.append(McObject(characteristic.name, characteristic.address, 0, mem_size, ""))

        blocks = make_continuous_blocks(result)

        # Calculate total size for logging
        total_size = reduce(lambda a, s: s.length + a, blocks, 0)
        self.logger.info(f"Fetching a total of {total_size / 1024:.2f} KBytes from XCP slave")

        sections: list[Section] = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address=block.address, data=mem[: block.length]))

        img = Image(sections=sections, join=True)

        if save_to_file:
            file_name = f"CalParams{current_timestamp()}.{'hex' if hexfile_type == 'ihex' else 'srec'}"
            file_name = self.asam_mc.sub_dir("hexfiles") / file_name
            with open(f"{file_name}", "wb") as outf:
                dump(hexfile_type, outf, img, row_length=32)
            self.logger.info("CalParams written to %s", file_name)

        return img

    # -- Parameter loaders (private) ---------------------------------------

    def _load_asciis(self) -> None:
        """Load all ASCII string characteristics from the current image."""
        self.logger.info("Loading ASCII string characteristics")
        for characteristic in self.characteristics("ASCII"):
            if characteristic is None:
                continue
            self.logger.debug(f"Processing ASCII '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["ASCII"][characteristic.name] = self.api.load_ascii(characteristic.name)

    def _load_value_blocks(self) -> None:
        """Load all value-block characteristics from the current image."""
        self.logger.info("Loading value block characteristics")
        for characteristic in self.characteristics("VAL_BLK"):
            if characteristic is None:
                continue
            self.logger.debug(f"Processing VAL_BLK '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["VAL_BLK"][characteristic.name] = self.api.load_value_block(characteristic.name)

    def _load_values(self) -> None:
        """Load all scalar-value characteristics from the current image."""
        self.logger.info("Loading scalar value characteristics")
        for characteristic in self.characteristics("VALUE"):
            if characteristic is None:
                continue
            self.logger.debug(f"Processing VALUE '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters["VALUE"][characteristic.name] = self.api.load_value(characteristic.name)

    def _load_axis_pts(self) -> None:
        """Load all axis-points from the current image."""
        self.logger.info("Loading axis points")
        for ap in self.axis_points():
            if ap is None:
                continue
            self.logger.debug("Processing AXIS_PTS '%s' @0x%08x", ap.name, ap.address)
            self._parameters["AXIS_PTS"][ap.name] = self.api.load_axis_pts(ap.name)

    def _load_curves(self) -> None:
        """Load all curve characteristics."""
        self.logger.info("Loading curve characteristics")
        self._load_curves_and_maps("CURVE", 1)

    def _load_maps(self) -> None:
        """Load all map characteristics."""
        self.logger.info("Loading map characteristics")
        self._load_curves_and_maps("MAP", 2)

    def _load_cubes(self) -> None:
        """Load all cube characteristics (CUBOID, CUBE_4, CUBE_5)."""
        self.logger.info("Loading cuboid characteristics")
        self._load_curves_and_maps("CUBOID", 3)
        self.logger.info("Loading 4D cube characteristics")
        self._load_curves_and_maps("CUBE_4", 4)
        self.logger.info("Loading 5D cube characteristics")
        self._load_curves_and_maps("CUBE_5", 5)

    def _order_curves(self, curves: list[Characteristic]) -> list[Characteristic]:
        """Reorder curves so that referenced curves appear before referencing ones.

        Args:
            curves: List of curve characteristics.

        Returns:
            Topologically sorted list.
        """
        curves = list(curves)[::1]
        curves_by_name: dict[str, tuple[int, Characteristic]] = {c.name: (pos, c) for pos, c in enumerate(curves)}

        while True:
            ins_pos = 0
            for curr_pos in range(len(curves)):
                curve = curves[curr_pos]
                axis_descr = curve.axisDescriptions[0]
                if axis_descr.attribute == "CURVE_AXIS":
                    if axis_descr.curveAxisRef.name in curves_by_name:
                        ref_pos, ref_curve = curves_by_name.get(axis_descr.curveAxisRef.name)

                        # If the referenced curve appears after this curve, swap them
                        if ref_pos > curr_pos:
                            curves[ins_pos], curves[ref_pos] = (
                                curves[ref_pos],
                                curves[ins_pos],
                            )
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
                break

        return curves

    def _load_curves_and_maps(self, category: str, num_axes: int) -> None:
        """Load curve / map / cube characteristics.

        Args:
            category: Category key (``"CURVE"``, ``"MAP"``, etc.).
            num_axes: Expected number of axes.
        """
        characteristics = self.characteristics(category)
        if num_axes == 1:
            characteristics = self._order_curves(characteristics)

        for characteristic in characteristics:
            self.logger.debug(f"Processing {category} '{characteristic.name}' @0x{characteristic.address:08x}")
            self._parameters[f"{category}"][characteristic.name] = self.api.load_curve_or_map(
                characteristic.name, category, num_axes
            )

    # -- Memory error logging ----------------------------------------------

    def log_memory_errors(
        self,
        exc: Exception,
        memory_type: MemoryType,
        name: str,
        address: int,
        length: int,
    ) -> None:
        """Record a memory-access error for later reporting.

        Args:
            exc: The exception that occurred.
            memory_type: Category of the memory object.
            name: Parameter name.
            address: ECU address that failed.
            length: Expected region length.
        """
        if isinstance(exc, InvalidAddressError):
            self.memory_errors[address].append(MemoryObject(memory_type=memory_type, name=name, address=address, length=length))
            self.logger.error(f"Invalid address 0x{address:08X} for {memory_type.name} '{name}'")

    @property
    def parameters(self) -> dict[str, dict[str, Any]]:
        """All loaded calibration parameters, keyed by category."""
        return self._parameters

    def generate_c_structs(
        self,
        log_path: str | Path | None = None,
        template: str | Path | None = None,
        out_basename: str | None = None,
    ) -> Path:
        """Generate a C header with structs/arrays from a calibration JSON log.

        Convenience wrapper around
        :func:`asamint.calibration.codegen.generate_c_structs_from_log`.

        Args:
            log_path: Path to JSON log; ``None`` picks the most recent.
            template: Optional Jinja2 template path.
            out_basename: Base name for the output header file.

        Returns:
            Path to the written header file.
        """
        from .codegen import generate_c_structs_from_log

        tpath = Path(template) if template else None
        out_path: Path | None = None
        if out_basename:
            out_name = out_basename if out_basename.endswith(".h") else f"{out_basename}.h"
            code_dir = self.asam_mc.sub_dir("code")
            code_dir.mkdir(exist_ok=True)
            out_path = code_dir / out_name
        return generate_c_structs_from_log(self.asam_mc, Path(log_path) if log_path else None, out_path, tpath)

    def axis_points(self) -> Generator[AxisPts, None, None]:
        """Yield all axis-points defined in the A2L file."""
        for a in self.query(model.AxisPts).order_by(model.AxisPts.address).all():
            try:
                yield AxisPts.get(self.session, a.name)
            except (AttributeError, ValueError, KeyError) as exc:
                self.logger.error("Error loading axis points '%s': %s", a.name, exc)

    def characteristics(self, category: str) -> Generator[Characteristic, None, None]:
        """Yield all characteristics of a given *category*.

        Args:
            category: ``"VALUE"``, ``"CURVE"``, ``"MAP"``, etc.
        """
        # Query all characteristics of the specified category
        query = self.query(model.Characteristic.name).filter(model.Characteristic.type == category)

        # Yield each characteristic
        for characteristic in query.all():
            try:
                yield Characteristic.get(self.session, characteristic.name)
            except (AttributeError, ValueError, KeyError) as e:
                self.logger.error(f"Error loading {category} '{characteristic.name}': {e}")
                continue
