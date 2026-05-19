#!/usr/bin/env python
"""ASAM MSR-SW XML mixin for building CDF/DCM/MDX XML documents.

Provides ``MSRMixIn``, a cooperative mixin that adds XML scaffolding methods
(header generation, 1-D array serialisation, SDG elements, DTD validation)
required by the various ASAM XML export formats (CDF20, DCM, …).
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

__author__ = """Christoph Schueler"""
__email__ = "cpu12.gems@googlemail.com"

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree  # nosec

if TYPE_CHECKING:
    import numpy as np

from asamint.adapters.a2l import model
from asamint.utils.xml import create_elem

__all__ = ["MSRMixIn"]


class MSRMixIn:
    """Cooperative mixin that provides ASAM MSR-SW XML generation helpers.

    Subclasses (e.g. ``CDFCreator``, ``MDXCreator``) must also inherit from
    a class that supplies ``logger``, ``query``, ``generate_filename`` and
    ``sub_dir`` (typically :class:`~asamint.calibration.CalibrationData`).
    """

    DOCTYPE: str | None = None
    DTD: str | None = None
    EXTENSION: str | None = None

    # Populated by subclass or __init__; declared here for type-checkers.
    sub_trees: dict[str, etree._Element]
    root: etree._Element
    logger: logging.Logger

    def __init__(self, *args: Any, **kws: Any) -> None:
        self.sub_trees: dict[str, etree._Element] = {}
        super().__init__(*args, **kws)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def write_tree(self, file_name: str | None = None) -> None:
        """Serialise the XML tree to disk.

        Args:
            file_name: **Deprecated** – ignored.  The filename is derived
                from :meth:`generate_filename` and :meth:`sub_dir`.
        """
        if file_name is not None:
            import warnings

            warnings.warn(
                "The 'file_name' parameter of write_tree() is ignored and will be removed in a future version.",
                DeprecationWarning,
                stacklevel=2,
            )
        resolved_name: str = self.generate_filename(self.EXTENSION)
        output_path: Path = self.sub_dir("parameters") / resolved_name
        self.logger.info("Saving tree to %s", output_path)
        xml_bytes = etree.tostring(
            self.root,
            encoding="UTF-8",
            pretty_print=True,
            xml_declaration=True,
            doctype=self.DOCTYPE,
        )
        output_path.write_bytes(xml_bytes)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> bool:
        """Validate the current XML tree against the configured DTD.

        Returns:
            ``True`` if valid, ``False`` otherwise.  Validation errors are
            written to the logger at *error* level.
        """
        if self.DTD is None:
            self.logger.warning("No DTD configured – skipping validation.")
            return True
        dtd = etree.DTD(self.DTD)
        if dtd.validate(self.root):
            return True
        for error in dtd.error_log.filter_from_errors():
            self.logger.error("DTD validation error: %s", error)
        return False

    # ------------------------------------------------------------------
    # Array / element helpers
    # ------------------------------------------------------------------

    def output_1darray(
        self,
        elem: etree._Element,
        name: str | None = None,
        values: np.ndarray | Sequence[Any] | None = None,
        numeric: bool = True,
    ) -> None:
        """Write a one-dimensional value array into the XML tree.

        Args:
            elem: Parent XML element.
            name: Optional child-element name wrapping the values.
            values: Array-like of values to write.
            numeric: If ``True`` use ``<V>`` tags, otherwise ``<VT>``.
        """
        if values is None:
            values = []
        cont: etree._Element = create_elem(elem, name) if name else elem
        tag: str = "V" if numeric else "VT"
        is_pair: bool = hasattr(values, "ndim") and values.ndim == 2
        if is_pair:
            for lhs, rhs in values:
                vg = create_elem(cont, "VG")
                create_elem(vg, tag, text=str(lhs))
                create_elem(vg, tag, text=str(rhs))
        else:
            for value in values:
                create_elem(cont, tag, text=str(value))

    def sdg(self, parent: etree._Element, name: str, *elements: tuple[str, str]) -> None:
        """Create a Special Data Group (SDG) element.

        Args:
            parent: Parent XML element.
            name: GID attribute value for the SDG.
            elements: Sequence of ``(tag, text)`` tuples; each becomes an
                ``<SD GID="tag">text</SD>`` child.
        """
        sdg_elem: etree._Element = create_elem(parent, "SDG", attrib={"GID": name})
        for tag, text in elements:
            create_elem(sdg_elem, "SD", text=text, attrib={"GID": tag})

    @staticmethod
    def common_elements(
        elem: etree._Element,
        short_name: str,
        long_name: str | None = None,
        category: str | None = None,
    ) -> None:
        """Append common MSRSW child elements (SHORT-NAME, LONG-NAME, CATEGORY).

        Args:
            elem: Parent XML element.
            short_name: Value for ``<SHORT-NAME>``.
            long_name: Optional value for ``<LONG-NAME>``.
            category: Optional value for ``<CATEGORY>``.
        """
        create_elem(elem, "SHORT-NAME", short_name)
        if long_name:
            create_elem(elem, "LONG-NAME", long_name)
        if category:
            create_elem(elem, "CATEGORY", category)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def msrsw_header(self, category: str, suffix: str) -> etree._Element:
        """Build the top-level ``<MSRSW>`` / ``<SW-SYSTEM>`` scaffold.

        Args:
            category: CDF category string (e.g. ``"CDF20"``).
            suffix: Suffix appended to the project short-name.

        Returns:
            Root ``<MSRSW>`` element.
        """
        proj = self.query(model.Project).first()
        project_name: str = proj.name
        project_comment: str = proj.longIdentifier

        root: etree._Element = etree.Element("MSRSW")
        create_elem(root, "SHORT-NAME", text=f"{project_name}_{suffix}")
        create_elem(root, "CATEGORY", category)
        sw_systems = create_elem(root, "SW-SYSTEMS")
        sw_system = create_elem(sw_systems, "SW-SYSTEM")
        self.common_elements(sw_system, project_name, project_comment)
        self.sub_trees["SW-SYSTEM"] = sw_system
        return root
