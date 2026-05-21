#!/usr/bin/env python
"""Paging geometry: dataclasses and merge/compare logic for XCP and A2L segment/page data.

Per ASAM XCP specification, live XCP data (getPagInfo) is authoritative.
A2L data is used as fallback and to supplement fields not available via XCP
(e.g. segment ``name`` and ``longIdentifier``).  All discrepancies are logged
as warnings before the XCP value is applied.
"""

from __future__ import annotations

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


import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# A2L access-keyword → XCP boolean property mappings
# ---------------------------------------------------------------------------

# ECU_ACCESS_* → (ecuAccessWithXcp, ecuAccessWithoutXcp)
_ECU_ACCESS_MAP: dict[str, tuple[bool, bool]] = {
    "ECU_ACCESS_DONT_CARE": (True, True),
    "ECU_ACCESS_WITHOUT_XCP_ONLY": (False, True),
    "ECU_ACCESS_WITH_XCP_ONLY": (True, False),
    "ECU_ACCESS_NOT_ALLOWED": (False, False),
}

# XCP_READ_ACCESS_* → (xcpReadAccessWithEcu, xcpReadAccessWithoutEcu)
_XCP_READ_MAP: dict[str, tuple[bool, bool]] = {
    "XCP_READ_ACCESS_DONT_CARE": (True, True),
    "XCP_READ_ACCESS_WITHOUT_ECU_ONLY": (False, True),
    "XCP_READ_ACCESS_WITH_ECU_ONLY": (True, False),
    "XCP_READ_ACCESS_NOT_ALLOWED": (False, False),
}

# XCP_WRITE_ACCESS_* → (xcpWriteAccessWithEcu, xcpWriteAccessWithoutEcu)
_XCP_WRITE_MAP: dict[str, tuple[bool, bool]] = {
    "XCP_WRITE_ACCESS_DONT_CARE": (True, True),
    "XCP_WRITE_ACCESS_WITHOUT_ECU_ONLY": (False, True),
    "XCP_WRITE_ACCESS_WITH_ECU_ONLY": (True, False),
    "XCP_WRITE_ACCESS_NOT_ALLOWED": (False, False),
}


def _map_ecu_access(keyword: str) -> tuple[bool, bool]:
    """Map an A2L ``ECU_ACCESS_*`` keyword to ``(with_xcp, without_xcp)`` booleans."""
    result = _ECU_ACCESS_MAP.get(keyword)
    if result is None:
        logger.warning("Unknown ECU_ACCESS keyword %r; defaulting to DONT_CARE (True, True).", keyword)
        return (True, True)
    return result


def _map_xcp_read_access(keyword: str) -> tuple[bool, bool]:
    """Map an A2L ``XCP_READ_ACCESS_*`` keyword to ``(with_ecu, without_ecu)`` booleans."""
    result = _XCP_READ_MAP.get(keyword)
    if result is None:
        logger.warning("Unknown XCP_READ_ACCESS keyword %r; defaulting to DONT_CARE (True, True).", keyword)
        return (True, True)
    return result


def _map_xcp_write_access(keyword: str) -> tuple[bool, bool]:
    """Map an A2L ``XCP_WRITE_ACCESS_*`` keyword to ``(with_ecu, without_ecu)`` booleans."""
    result = _XCP_WRITE_MAP.get(keyword)
    if result is None:
        logger.warning("Unknown XCP_WRITE_ACCESS keyword %r; defaulting to DONT_CARE (True, True).", keyword)
        return (True, True)
    return result


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PageAccessProperties:
    """Unified page-access property flags (aligned with XCP nomenclature).

    Derived from both XCP ``GET_PAGE_INFO`` and A2L ``IF_DATA XCP PAGE`` entries.
    """

    ecu_access_with_xcp: bool
    """ECU may access this page while XCP is active."""

    ecu_access_without_xcp: bool
    """ECU may access this page when XCP is not active."""

    xcp_read_access_with_ecu: bool
    """XCP may read this page while the ECU is running."""

    xcp_read_access_without_ecu: bool
    """XCP may read this page when the ECU is not running."""

    xcp_write_access_with_ecu: bool
    """XCP may write this page while the ECU is running."""

    xcp_write_access_without_ecu: bool
    """XCP may write this page when the ECU is not running."""


@dataclass(slots=True)
class PageInfo:
    """Description of a single page within a segment."""

    index: int
    """Zero-based page index (identical in XCP and A2L)."""

    init_segment: int
    """XCP init-segment flag (1 = this page is the reference/FLASH image).
    Not available from A2L; defaults to ``0`` when built from A2L data only."""

    properties: PageAccessProperties
    """Access property flags for this page."""


@dataclass(slots=True)
class SegmentInfo:
    """Unified segment descriptor combining A2L and live XCP information."""

    index: int
    """Segment index as reported by XCP / defined in A2L IF_DATA."""

    address: int
    """Base address of the segment — the canonical match key between A2L and XCP."""

    length: int
    """Byte length of the segment (``size`` in A2L, ``length`` in XCP)."""

    address_extension: int
    """XCP address extension byte (not represented in A2L; defaults to ``0``)."""

    compression_method: int
    """Compression method code (A2L IF_DATA SEGMENT[2], XCP compressionMethod)."""

    encryption_method: int
    """Encryption method code (A2L IF_DATA SEGMENT[3], XCP encryptionMethod)."""

    max_pages: int
    """Maximum number of pages (A2L IF_DATA SEGMENT[1], XCP maxPages)."""

    max_mapping: int
    """Maximum mapping count (A2L IF_DATA SEGMENT[4], XCP maxMapping)."""

    pages: list[PageInfo]
    """Ordered list of page descriptors."""

    name: str = ""
    """Human-readable name from A2L ``MEMORY_SEGMENT``; not available via XCP."""

    long_identifier: str = ""
    """Long description from A2L ``MEMORY_SEGMENT``; not available via XCP."""


@dataclass(slots=True)
class PagingGeometry:
    """Complete, unified paging geometry for the connected ECU."""

    max_segments: int
    """Total number of segments (XCP ``maxSegments``)."""

    freeze_supported: bool
    """Whether the XCP slave supports the FREEZE command (from XCP ``pagProperties``)."""

    segments: list[SegmentInfo] = field(default_factory=list)
    """Segment descriptors, ordered by segment index."""


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def paging_geometry_from_xcp(pag_info: dict[str, Any]) -> PagingGeometry:
    """Build a :class:`PagingGeometry` from the raw ``pag_info`` dict returned by pyxcp.

    Parameters
    ----------
    pag_info:
        Dict as returned by ``master.getPagInfo()``.

    Returns
    -------
    PagingGeometry:
        Geometry populated exclusively from live XCP data.
    """
    segments: list[SegmentInfo] = []

    for seg in pag_info.get("segments", []):
        pages: list[PageInfo] = []
        for pg in seg.get("pages", []):
            p = pg["properties"]
            prop = PageAccessProperties(
                ecu_access_with_xcp=bool(p["ecuAccessWithXcp"]),
                ecu_access_without_xcp=bool(p["ecuAccessWithoutXcp"]),
                xcp_read_access_with_ecu=bool(p["xcpReadAccessWithEcu"]),
                xcp_read_access_without_ecu=bool(p["xcpReadAccessWithoutEcu"]),
                xcp_write_access_with_ecu=bool(p["xcpWriteAccessWithEcu"]),
                xcp_write_access_without_ecu=bool(p["xcpWriteAccessWithoutEcu"]),
            )
            pages.append(
                PageInfo(
                    index=int(pg["index"]),
                    init_segment=int(pg.get("initSegment", 0)),
                    properties=prop,
                )
            )

        segments.append(
            SegmentInfo(
                index=int(seg["index"]),
                address=int(seg["address"]),
                length=int(seg["length"]),
                address_extension=int(seg.get("addressExtension", 0)),
                compression_method=int(seg.get("compressionMethod", 0)),
                encryption_method=int(seg.get("encryptionMethod", 0)),
                max_pages=int(seg.get("maxPages", 0)),
                max_mapping=int(seg.get("maxMapping", 0)),
                pages=pages,
            )
        )

    pag_props = pag_info.get("pagProperties", {})
    return PagingGeometry(
        max_segments=int(pag_info.get("maxSegments", len(segments))),
        freeze_supported=bool(pag_props.get("freezeSupported", False)),
        segments=segments,
    )


def _extract_xcp_segment_data(if_data_parsed: list[Any]) -> list[Any] | None:
    """Extract the ``SEGMENT`` payload list from A2L ``IF_DATA XCP`` parsed content.

    The typical layout after parsing is::

        [{'XCP': [{'SEGMENT': [idx, max_pages, comp, enc, max_mapping, {detail}]}]}]

    Parameters
    ----------
    if_data_parsed:
        The ``if_data_parsed`` list from an A2L ``IfData`` object.

    Returns
    -------
    list | None:
        The raw SEGMENT list, or ``None`` if not found.
    """
    for item in if_data_parsed:
        xcp_entries = item.get("XCP")
        if not xcp_entries:
            continue
        for entry in xcp_entries:
            seg_data = entry.get("SEGMENT")
            if seg_data is not None:
                return seg_data  # type: ignore[return-value]
    return None


def paging_geometry_from_a2l(memory_segments: list[Any]) -> PagingGeometry:
    """Build a :class:`PagingGeometry` from A2L ``MemorySegment`` objects.

    Parameters
    ----------
    memory_segments:
        List of ``MemorySegment`` model objects as returned by
        ``mod_par.memorySegments``.

    Returns
    -------
    PagingGeometry:
        Geometry populated from A2L data.  ``freeze_supported`` defaults to
        ``False`` because the A2L does not carry this information.
    """
    segments: list[SegmentInfo] = []

    for ms in memory_segments:
        if_data = ms.if_data
        parsed: list[Any] = getattr(if_data, "if_data_parsed", None) or []
        seg_data = _extract_xcp_segment_data(parsed)

        if seg_data is None:
            # No XCP IF_DATA block found — build a minimal entry from A2L base info.
            logger.debug(
                "MEMORY_SEGMENT %r: no XCP IF_DATA found; building minimal SegmentInfo.",
                ms.name,
            )
            segments.append(
                SegmentInfo(
                    index=len(segments),
                    address=int(ms.address),
                    length=int(ms.size),
                    address_extension=0,
                    compression_method=0,
                    encryption_method=0,
                    max_pages=0,
                    max_mapping=0,
                    pages=[],
                    name=str(ms.name),
                    long_identifier=str(ms.longIdentifier or ""),
                )
            )
            continue

        # seg_data: [index, max_pages, comp_method, enc_method, max_mapping, {detail}]
        seg_index = int(seg_data[0])
        max_pages = int(seg_data[1])
        comp_method = int(seg_data[2])
        enc_method = int(seg_data[3])
        max_mapping = int(seg_data[4])
        detail: dict[str, Any] = seg_data[5] if len(seg_data) > 5 and isinstance(seg_data[5], dict) else {}

        pages: list[PageInfo] = []
        for pg in detail.get("PAGE", []):
            # PAGE entry: [page_index, ecu_access_kw, xcp_read_kw, xcp_write_kw]
            pg_index = int(pg[0])
            ecu_kw: str = str(pg[1])
            read_kw: str = str(pg[2])
            write_kw: str = str(pg[3])

            ecu_with, ecu_without = _map_ecu_access(ecu_kw)
            read_with, read_without = _map_xcp_read_access(read_kw)
            write_with, write_without = _map_xcp_write_access(write_kw)

            prop = PageAccessProperties(
                ecu_access_with_xcp=ecu_with,
                ecu_access_without_xcp=ecu_without,
                xcp_read_access_with_ecu=read_with,
                xcp_read_access_without_ecu=read_without,
                xcp_write_access_with_ecu=write_with,
                xcp_write_access_without_ecu=write_without,
            )
            pages.append(PageInfo(index=pg_index, init_segment=0, properties=prop))

        segments.append(
            SegmentInfo(
                index=seg_index,
                address=int(ms.address),
                length=int(ms.size),
                address_extension=0,
                compression_method=comp_method,
                encryption_method=enc_method,
                max_pages=max_pages,
                max_mapping=max_mapping,
                pages=pages,
                name=str(ms.name),
                long_identifier=str(ms.longIdentifier or ""),
            )
        )

    return PagingGeometry(
        max_segments=len(segments),
        freeze_supported=False,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Compare helpers (XCP always wins, differences are warnings)
# ---------------------------------------------------------------------------


def _compare_page_properties(
    seg_index: int,
    pg_index: int,
    xcp_prop: PageAccessProperties,
    a2l_prop: PageAccessProperties,
) -> None:
    """Log any field-level differences between XCP and A2L page properties."""
    checks: list[tuple[str, str]] = [
        ("ecu_access_with_xcp", "ecuAccessWithXcp"),
        ("ecu_access_without_xcp", "ecuAccessWithoutXcp"),
        ("xcp_read_access_with_ecu", "xcpReadAccessWithEcu"),
        ("xcp_read_access_without_ecu", "xcpReadAccessWithoutEcu"),
        ("xcp_write_access_with_ecu", "xcpWriteAccessWithEcu"),
        ("xcp_write_access_without_ecu", "xcpWriteAccessWithoutEcu"),
    ]
    for attr, display_name in checks:
        xcp_val = getattr(xcp_prop, attr)
        a2l_val = getattr(a2l_prop, attr)
        if xcp_val != a2l_val:
            logger.warning(
                "Segment %d / Page %d: property %r differs — XCP=%s, A2L=%s; XCP takes precedence.",
                seg_index,
                pg_index,
                display_name,
                xcp_val,
                a2l_val,
            )


def _compare_segment_scalars(xcp_seg: SegmentInfo, a2l_seg: SegmentInfo) -> None:
    """Log scalar-field differences between a matched XCP/A2L segment pair."""
    checks: list[tuple[str, str]] = [
        ("length", "length/size"),
        ("compression_method", "compressionMethod"),
        ("encryption_method", "encryptionMethod"),
        ("max_pages", "maxPages"),
        ("max_mapping", "maxMapping"),
        ("address_extension", "addressExtension"),
    ]
    for attr, display_name in checks:
        xcp_val = getattr(xcp_seg, attr)
        a2l_val = getattr(a2l_seg, attr)
        if xcp_val != a2l_val:
            logger.warning(
                "Segment idx=%d (addr=0x%08X) field %r differs — XCP=%s, A2L=%s; XCP takes precedence.",
                xcp_seg.index,
                xcp_seg.address,
                display_name,
                xcp_val,
                a2l_val,
            )


def _compare_segment_pages(xcp_seg: SegmentInfo, a2l_seg: SegmentInfo) -> None:
    """Log page-level differences between a matched XCP/A2L segment pair."""
    a2l_pages: dict[int, PageInfo] = {p.index: p for p in a2l_seg.pages}

    for xcp_page in xcp_seg.pages:
        a2l_page = a2l_pages.get(xcp_page.index)
        if a2l_page is None:
            logger.warning(
                "Segment idx=%d %r: page %d present in XCP but absent in A2L.",
                xcp_seg.index,
                xcp_seg.name,
                xcp_page.index,
            )
            continue
        _compare_page_properties(xcp_seg.index, xcp_page.index, xcp_page.properties, a2l_page.properties)

    xcp_page_indices: set[int] = {p.index for p in xcp_seg.pages}
    for a2l_page in a2l_seg.pages:
        if a2l_page.index not in xcp_page_indices:
            logger.warning(
                "Segment idx=%d %r: page %d present in A2L but absent in XCP.",
                xcp_seg.index,
                xcp_seg.name,
                a2l_page.index,
            )


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_paging_geometry(
    xcp: PagingGeometry,
    a2l: PagingGeometry,
) -> PagingGeometry:
    """Merge XCP and A2L paging geometry into a single authoritative :class:`PagingGeometry`.

    XCP is authoritative for **all** numeric and boolean fields it provides.
    A2L supplements with ``name`` and ``long_identifier`` which are not
    available via XCP.  All discrepancies are reported as ``WARNING`` log
    messages before the XCP value is applied.

    Segments are matched by **address** (the canonical key that both sources
    agree on).

    Parameters
    ----------
    xcp:
        Geometry built from live ``master.getPagInfo()`` data.
    a2l:
        Geometry built from the parsed A2L ``MEMORY_SEGMENT`` / ``IF_DATA`` blocks.

    Returns
    -------
    PagingGeometry:
        Merged geometry where XCP values take precedence and A2L enriches
        name/long_identifier fields.
    """
    if xcp.max_segments != a2l.max_segments:
        logger.warning(
            "maxSegments differs — XCP=%d, A2L=%d; XCP value (%d) takes precedence.",
            xcp.max_segments,
            a2l.max_segments,
            xcp.max_segments,
        )

    # Match A2L segments to XCP segments by base address.
    a2l_by_address: dict[int, SegmentInfo] = {s.address: s for s in a2l.segments}
    a2l_matched: set[int] = set()
    merged_segments: list[SegmentInfo] = []

    for xcp_seg in xcp.segments:
        a2l_seg = a2l_by_address.get(xcp_seg.address)
        if a2l_seg is None:
            logger.warning(
                "Segment idx=%d (addr=0x%08X) exists in XCP but not in A2L; using XCP data as-is.",
                xcp_seg.index,
                xcp_seg.address,
            )
            merged_segments.append(xcp_seg)
            continue

        a2l_matched.add(xcp_seg.address)

        # Log all discrepancies (XCP wins in every case).
        _compare_segment_scalars(xcp_seg, a2l_seg)
        _compare_segment_pages(xcp_seg, a2l_seg)

        # Build merged segment: XCP data + A2L name/long_identifier enrichment.
        merged_seg = SegmentInfo(
            index=xcp_seg.index,
            address=xcp_seg.address,
            length=xcp_seg.length,
            address_extension=xcp_seg.address_extension,
            compression_method=xcp_seg.compression_method,
            encryption_method=xcp_seg.encryption_method,
            max_pages=xcp_seg.max_pages,
            max_mapping=xcp_seg.max_mapping,
            pages=xcp_seg.pages,   # incl. initSegment flags not present in A2L
            name=a2l_seg.name,
            long_identifier=a2l_seg.long_identifier,
        )
        merged_segments.append(merged_seg)

    # Report A2L segments that had no XCP counterpart.
    for a2l_seg in a2l.segments:
        if a2l_seg.address not in a2l_matched:
            logger.warning(
                "Segment %r (addr=0x%08X) exists in A2L but not in XCP; segment is ignored.",
                a2l_seg.name,
                a2l_seg.address,
            )

    return PagingGeometry(
        max_segments=xcp.max_segments,
        freeze_supported=xcp.freeze_supported,
        segments=merged_segments,
    )

