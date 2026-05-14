#!/usr/bin/env python
"""ASAM CDF20 (Calibration Data Format) import/export and in-memory access.

This module provides:

* :func:`export_cdf` / :func:`import_cdf` – high-level CDF I/O entry-points.
* :class:`DB` – lightweight reader for CDF HDF5 payload produced by the
  importer, supporting the context-manager protocol.
* :class:`CDFCreator` – exporter that builds an ASAM CDF20 XML (``.cdfx``)
  from loaded calibration parameters.
"""

from __future__ import annotations

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

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any

import h5py
import numpy as np
import xarray as xr
from lxml import etree  # nosec

from asamint import msrsw
from asamint.adapters.a2l import model
from asamint.asam import AsamMC
from asamint.calibration import CalibrationData
from asamint.calibration.db import CalibrationDB
from asamint.calibration.msrsw_db import MSRSWDatabase
from asamint.cdf.exporter.cdf_exporter import CDFExporter
from asamint.cdf.importer.cdf_importer import CDFImporter
from asamint.core.deprecation import DeprecatedAlias, deprecated_dir, deprecated_getattr
from asamint.core.exceptions import AdapterError
from asamint.core.logging import configure_logging
from asamint.utils import add_suffix_to_path
from asamint.utils.xml import create_elem, xml_comment

from .importer import DBImporter

__all__ = ["DB", "CDFCreator", "DBImporter", "CdfIOResult", "export_cdf", "import_cdf"]

_DEPRECATED_ALIASES: dict[str, DeprecatedAlias] = {}


def __getattr__(name: str) -> object:
    return deprecated_getattr(name, _DEPRECATED_ALIASES, globals(), __name__)


def __dir__() -> list[str]:
    return deprecated_dir(_DEPRECATED_ALIASES, globals())


# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CdfIOResult:
    """Result of a CDF import or export operation."""

    output_path: Path
    db_path: Path


# ---------------------------------------------------------------------------
# High-level I/O functions
# ---------------------------------------------------------------------------


def export_cdf(
    *,
    db_path: str | Path,
    output_path: str | Path,
    h5_db_path: str | Path | None = None,
    variant_coding: bool = False,
    validate_dtd: bool = False,
    logger: logging.Logger | None = None,
) -> CdfIOResult:
    """Export calibration parameters from an MSRSW database to ASAM CDF20 XML.

    Args:
        db_path: Path to the MSRSW database (``.msrswdb``).
        output_path: Destination path for the CDF XML file.
        h5_db_path: Optional CalibrationDB HDF5 file for supplementary data.
        variant_coding: Include variant-coding parameters.
        validate_dtd: Validate the output against the CDF DTD.
        logger: Optional logger; one is created if not provided.

    Returns:
        :class:`CdfIOResult` with the written output and database paths.

    Raises:
        AdapterError: If the export fails.
    """
    log: logging.Logger = logger or configure_logging(__name__)
    db_file = Path(db_path)
    output = Path(output_path)
    h5_db: CalibrationDB | None = (
        CalibrationDB(str(h5_db_path), mode="r", logger=log) if h5_db_path else None
    )
    db = MSRSWDatabase(db_file)
    try:
        exporter = CDFExporter(
            db=db,
            h5_db=h5_db,
            variant_coding=variant_coding,
            logger=log,
        )
        success = exporter.export(output, validate_dtd=validate_dtd)
        if not success:
            raise AdapterError(f"CDF export failed for {output}")
        return CdfIOResult(output_path=output, db_path=db_file)
    finally:
        db.close()
        if h5_db is not None:
            h5_db.close()


def import_cdf(
    *,
    xml_path: str | Path,
    db_path: str | Path,
    logger: logging.Logger | None = None,
) -> CdfIOResult:
    """Import calibration parameters from a CDF20 XML file into an MSRSW database.

    Args:
        xml_path: Path to the CDF XML file.
        db_path: Destination path for the MSRSW database (``.msrswdb``).
        logger: Optional logger; one is created if not provided.

    Returns:
        :class:`CdfIOResult` with the XML and database paths.

    Raises:
        AdapterError: If the import fails.
    """
    log: logging.Logger = logger or configure_logging(__name__)
    importer = CDFImporter(logger=log)
    xml = Path(xml_path)
    db_file = Path(db_path)
    success = importer.import_file(xml, db_file)
    if not success:
        raise AdapterError(f"CDF import failed for {xml}")
    return CdfIOResult(output_path=xml, db_path=db_file)


# ---------------------------------------------------------------------------
# Lightweight HDF5 reader
# ---------------------------------------------------------------------------


class DB:
    """Lightweight reader for CDF HDF5 payload produced by the importer.

    Opens the companion ``.h5`` store next to the ``.msrswdb`` and allows
    loading parameters into :class:`xarray.DataArray` structures.

    Supports the context-manager protocol::

        with DB("my_project") as db:
            arr = db.load("MyParameter")
    """

    def __init__(self, file_name: str | Path) -> None:
        self.opened: bool = False
        db_name = Path(file_name).with_suffix(".msrswdb")
        self.db = MSRSWDatabase(db_name, debug=False)
        self.session = self.db.session
        self.storage: h5py.File = h5py.File(
            db_name.with_suffix(".h5"),
            mode="r",
            libver="latest",
            locking="best-effort",
        )
        self.opened = True
        self.guid: uuid.UUID = uuid.uuid4()

    # -- Context-manager protocol ------------------------------------------

    def __enter__(self) -> DB:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        """Close the HDF5 storage and MSRSW database connections."""
        if getattr(self, "opened", False):
            self.storage.close()
            self.db.close()
            self.opened = False

    # -- Internal helpers --------------------------------------------------

    @staticmethod
    def _normalize_array_values(
        values: np.ndarray,
        shape: tuple[int, ...] | list[int],
    ) -> np.ndarray:
        """Reshape or zero-fill *values* to match *shape*.

        Args:
            values: Raw value array from the HDF5 store.
            shape: Expected target shape.

        Returns:
            Array with exactly *shape* dimensions.
        """
        target_shape = tuple(shape)
        if values.shape == (0,) or values.size == 0:
            return np.zeros(target_shape, dtype=values.dtype)
        if values.shape == target_shape:
            return values
        if values.size == np.prod(shape):
            return values.reshape(target_shape)
        return values

    @staticmethod
    def _load_axes(
        axes_group: h5py.Group,
    ) -> tuple[list[str], dict[str, np.ndarray], list[int]]:
        """Extract axis metadata from an HDF5 axes group.

        Args:
            axes_group: HDF5 group containing numbered axis sub-groups.

        Returns:
            Tuple of ``(dims, coords, shape)`` ready for
            :class:`xarray.DataArray` construction.

        Raises:
            TypeError: If an unsupported axis category is encountered.
        """
        dims: list[str] = []
        coords: dict[str, np.ndarray] = {}
        shape: list[int] = []
        for idx in range(len(axes_group)):
            ax = axes_group[str(idx)]
            ax_attrs = dict(ax.attrs.items())
            ax_items = dict(ax.items())
            ax_name: str = ax_attrs["name"]
            dims.append(ax_name)
            category: str = ax_attrs["category"]
            match category:
                case "COM_AXIS" | "RES_AXIS":
                    ref_axis = ax_items["reference"]
                    phys = np.array(ref_axis["phys"])
                case "CURVE_AXIS":
                    if "reference" in ax_items:
                        phys = np.array(ax_items["reference"]["phys"])
                    elif "phys" in ax_items:
                        phys = np.array(ax_items["phys"])
                    else:
                        raise KeyError(
                            f"CURVE_AXIS {ax_name!r} has neither 'reference' nor 'phys'"
                        )
                case "FIX_AXIS" | "STD_AXIS":
                    phys = np.array(ax_items["phys"])
                case _:
                    raise TypeError(f"Unsupported axis category: {category!r}")
            coords[ax_name] = phys
            shape.append(phys.size)
        return dims, coords, shape

    # -- Public API --------------------------------------------------------

    def load(self, name: str) -> xr.DataArray:
        """Load a calibration parameter as an :class:`xarray.DataArray`.

        The returned array carries axes/coordinates for multi-dimensional
        parameters (CURVE, MAP, etc.) and metadata attributes (category,
        display_identifier, comment).

        Args:
            name: Short-name of the calibration parameter.

        Returns:
            DataArray with values, coordinates (if applicable), and metadata.
        """
        ds = self.storage[f"/{name}"]
        ds_attrs = dict(ds.attrs.items())
        category: str = ds_attrs["category"]
        attrs: dict[str, str] = {
            "name": name,
            "display_identifier": ds_attrs.get("display_identifier") or "",
            "category": category,
            "comment": ds_attrs.get("comment") or "",
        }
        values: np.ndarray = ds["phys"][()]
        if category in ("VALUE", "DEPENDENT_VALUE", "BOOLEAN", "ASCII", "TEXT", "VAL_BLK", "COM_AXIS", "AXIS_PTS"):
            return xr.DataArray(values, attrs=attrs)

        dims, coords, shape = self._load_axes(ds["axes"])
        values = self._normalize_array_values(np.asarray(values), shape)
        return xr.DataArray(values, dims=dims, coords=coords, attrs=attrs)


# ---------------------------------------------------------------------------
# CDF20 XML creator
# ---------------------------------------------------------------------------


class CDFCreator(msrsw.MSRMixIn, CalibrationData):
    """Exporter that creates an ASAM CDF20 XML (.cdfx) from loaded calibration parameters.

    It relies on :class:`~asamint.msrsw.MSRMixIn` for XML scaffolding and
    :class:`~asamint.calibration.CalibrationData`'s loaded parameter
    dictionary.  Methods here build the required CDF structure and write it
    via the mixin's XML utilities.
    """

    DOCTYPE: str = (
        '<!DOCTYPE MSRSW PUBLIC "-//ASAM//DTD CALIBRATION DATA FORMAT:V2.0.0'
        ':LAI:IAI:XML:CDF200.XSD//EN" "cdf_v2.0.0.sl.dtd">'
    )
    EXTENSION: str = ".cdfx"

    def __init__(
        self,
        parameters: Mapping[str, dict[str, Any]],
        asam_mc: AsamMC | None = None,
    ) -> None:
        # Cooperative MRO: initialises both MSRMixIn.sub_trees and
        # CalibrationData fields.
        super().__init__(asam_mc or AsamMC())
        self._parameters = parameters

    def on_init(self, config: Any, *args: Any, **kws: Any) -> None:
        """Lifecycle hook called during CalibrationData initialisation (no-op)."""

    @property
    def a2l_file(self) -> Path:
        """Path to the A2L description file."""
        return self.asam_mc.a2l_file

    def sub_dir(self, name: str) -> Path:
        """Return a named sub-directory from the AsamMC workspace."""
        return self.asam_mc.sub_dir(name)

    def generate_filename(self, extension: str | None, extra: str | None = None) -> str:
        """Generate an output filename using the AsamMC naming scheme."""
        return self.asam_mc.generate_filename(extension, extra)

    def save(self) -> None:
        """Build the complete CDF20 XML document and write it to disk."""
        self.root = self._toplevel_boilerplate()
        self.tree = etree.ElementTree(self.root)
        self.cs_collections()
        self.instances()
        self.write_tree("CDF20demo")

    # ------------------------------------------------------------------
    # Document structure
    # ------------------------------------------------------------------

    def _toplevel_boilerplate(self) -> etree._Element:
        """Build the top-level MSRSW → SW-INSTANCE-TREE skeleton."""
        root = self.msrsw_header("CDF20", "CDF")
        sw_system = self.sub_trees["SW-SYSTEM"]
        instance_spec = create_elem(sw_system, "SW-INSTANCE-SPEC")
        instance_tree = create_elem(instance_spec, "SW-INSTANCE-TREE")
        self.sub_trees["SW-INSTANCE-TREE"] = instance_tree
        create_elem(instance_tree, "SHORT-NAME", text="STD")
        create_elem(instance_tree, "CATEGORY", text="NO_VCD")
        instance_tree_origin = create_elem(instance_tree, "SW-INSTANCE-TREE-ORIGIN")
        create_elem(
            instance_tree_origin,
            "SYMBOLIC-FILE",
            add_suffix_to_path(str(self.a2l_file), ".a2l"),
        )
        return root

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def cs_collection(
        self,
        name: str,
        category: str,
        tree: etree._Element,
        is_group: bool,
    ) -> None:
        """Create a single SW-CS-COLLECTION element (feature or group reference).

        Args:
            name: Reference name.
            category: CDF category string.
            tree: Parent XML element.
            is_group: If ``True`` emit ``<SW-COLLECTION-REF>``, else
                ``<SW-FEATURE-REF>``.
        """
        collection = create_elem(tree, "SW-CS-COLLECTION")
        create_elem(collection, "CATEGORY", text=category)
        if is_group:
            create_elem(collection, "SW-COLLECTION-REF", text=name)
        else:
            create_elem(collection, "SW-FEATURE-REF", text=name)

    def cs_collections(self) -> None:
        """Populate SW-CS-COLLECTIONS with all A2L functions and groups."""
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        collections = create_elem(instance_tree, "SW-CS-COLLECTIONS")
        functions = self.query(model.Function).all()
        functions = [f for f in functions if f.def_characteristic and f.def_characteristic.identifier != []]
        for f in functions:
            self.cs_collection(f.name, "FEATURE", collections, False)
        groups = self.query(model.Group).all()
        for g in groups:
            self.cs_collection(g.groupName, "COLLECTION", collections, True)

    # ------------------------------------------------------------------
    # Instance generation
    # ------------------------------------------------------------------

    def instances(self) -> None:
        """Generate SW-INSTANCE elements for all calibration parameters."""
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        xml_comment(instance_tree, "    AXIS_PTSs ")
        for inst in self._parameters["AXIS_PTS"].values():
            variant = self.sw_instance(
                name=inst.name,
                descr=inst.comment,
                category=inst.category,
                display_identifier=inst.displayIdentifier,
                feature_ref=None,
            )
            value_cont = create_elem(variant, "SW-VALUE-CONT")
            if inst.unit:
                create_elem(value_cont, "UNIT-DISPLAY-NAME", text=inst.unit)
            self.output_1darray(value_cont, "SW-VALUES-PHYS", inst.phys)
        xml_comment(instance_tree, "    VALUEs    ")
        for key, inst in self._parameters["VALUE"].items():
            self.instance_scalar(
                name=key,
                descr=inst.comment,
                value=inst.phys,
                unit=inst.unit,
                display_identifier=inst.displayIdentifier,
                category=inst.category,
            )
        xml_comment(instance_tree, "    DEPENDENT_VALUEs ")
        for key, inst in self._parameters.get("DEPENDENT_VALUE", {}).items():
            self.instance_scalar(
                name=key,
                descr=inst.comment,
                value=inst.phys,
                unit=inst.unit,
                display_identifier=inst.displayIdentifier,
                category="DEPENDENT_VALUE",
            )
        xml_comment(instance_tree, "    ASCIIs    ")
        for key, inst in self._parameters["ASCII"].items():
            self.instance_scalar(
                name=key,
                descr=inst.comment,
                value=inst.phys,
                category="ASCII",
                unit=None,
                display_identifier=inst.displayIdentifier,
            )
        xml_comment(instance_tree, "    VAL_BLKs  ")
        for key, inst in self._parameters["VAL_BLK"].items():
            self.value_blk(
                name=key,
                descr=inst.comment,
                values=inst.phys,
                display_identifier=inst.displayIdentifier,
                unit=inst.unit,
            )
        xml_comment(instance_tree, "    CURVEs    ")
        self.dump_array("CURVE")
        xml_comment(instance_tree, "    MAPs      ")
        self.dump_array("MAP")
        xml_comment(instance_tree, "    CUBOIDs   ")
        self.dump_array("CUBOID")
        xml_comment(instance_tree, "    CUBE_4    ")
        self.dump_array("CUBE_4")
        xml_comment(instance_tree, "    CUBE_5    ")
        self.dump_array("CUBE_5")

    def dump_array(self, attribute: str) -> None:
        """Write all CURVE/MAP/CUBOID/CUBE_4/CUBE_5 instances for *attribute*.

        Args:
            attribute: Parameter category key (``"CURVE"``, ``"MAP"``, …).
        """
        for inst in self._parameters[attribute].values():
            if not list(inst.phys):
                self.logger.warning("%s %r: has no values.", attribute, inst.name)
                continue
            axis_conts = self.curve_and_map_header(
                name=inst.name,
                descr=inst.comment,
                category=attribute,
                fnc_values=inst.phys,
                fnc_unit=inst.fnc_unit,
                display_identifier=inst.displayIdentifier,
                feature_ref=None,
            )
            for axis in inst.axes:
                self._emit_axis(axis_conts, axis)

    def _emit_axis(self, axis_conts: etree._Element, axis: Any) -> None:
        """Emit a single axis container element based on axis category.

        Args:
            axis_conts: Parent ``<SW-AXIS-CONTS>`` element.
            axis: Axis data object carrying ``category``, ``phys``,
                ``unit``, and optionally ``axis_pts_ref``.
        """
        match axis.category:
            case "STD_AXIS" | "FIX_AXIS":
                self.add_axis(axis_conts, axis.phys, axis.category, axis.unit)
            case "COM_AXIS" | "RES_AXIS" | "CURVE_AXIS":
                axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
                create_elem(axis_cont, "CATEGORY", axis.category)
                create_elem(axis_cont, "SW-INSTANCE-REF", text=axis.axis_pts_ref)
            case _:
                self.logger.warning("Unknown axis category %r – skipped.", axis.category)

    # ------------------------------------------------------------------
    # Scalar / array instance helpers
    # ------------------------------------------------------------------

    def instance_scalar(
        self,
        name: str,
        descr: str | None,
        value: float | int | str,
        category: str,
        unit: str | None = "",
        display_identifier: str | None = None,
        feature_ref: str | None = None,
    ) -> None:
        """Create a scalar SW-INSTANCE (VALUE, ASCII, BOOLEAN, or TEXT).

        Args:
            name: Parameter short-name.
            descr: Optional long-name / description.
            value: Scalar value to serialise.
            category: CDF category (``"VALUE"``, ``"ASCII"``, ``"TEXT"``, …).
            unit: Unit display name.
            display_identifier: Optional display identifier.
            feature_ref: Optional feature reference.
        """
        match category:
            case "TEXT":
                is_text = True
                category = "VALUE"
            case "BOOLEAN" | "ASCII":
                is_text = True
            case _:
                is_text = False

        cont = self.no_axis_container(
            name=name,
            descr=descr,
            category=category,
            unit=unit or "",
            display_identifier=display_identifier,
            feature_ref=feature_ref,
        )
        values = create_elem(cont, "SW-VALUES-PHYS")
        if is_text and value:
            create_elem(values, "VT", text=str(value))
        else:
            create_elem(values, "V", text=str(value))

    def add_axis(
        self,
        axis_conts: etree._Element,
        axis_values: np.ndarray,
        category: str,
        unit: str = "",
    ) -> None:
        """Append an axis container with values and optional unit.

        Args:
            axis_conts: Parent ``<SW-AXIS-CONTS>`` element.
            axis_values: One-dimensional array of axis values.
            category: Axis category (``"STD_AXIS"`` or ``"FIX_AXIS"``).
            unit: Unit display name.
        """
        axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
        create_elem(axis_cont, "CATEGORY", text=category)
        if unit:
            create_elem(axis_cont, "UNIT-DISPLAY-NAME", text=unit)
        self.output_1darray(axis_cont, "SW-VALUES-PHYS", axis_values)

    def instance_container(
        self,
        name: str,
        descr: str | None,
        category: str = "VALUE",
        unit: str = "",
        display_identifier: str | None = None,
        feature_ref: str | None = None,
    ) -> tuple[etree._Element, etree._Element]:
        """Create a variant instance with value and axis containers.

        Args:
            name: Parameter short-name.
            descr: Optional description.
            category: CDF category.
            unit: Unit display name.
            display_identifier: Optional display identifier.
            feature_ref: Optional feature reference.

        Returns:
            Tuple of ``(value_cont, axis_conts)`` elements.
        """
        variant = self.sw_instance(
            name,
            descr,
            category=category,
            display_identifier=display_identifier,
            feature_ref=feature_ref,
        )
        value_cont = create_elem(variant, "SW-VALUE-CONT")
        if unit:
            create_elem(value_cont, "UNIT-DISPLAY-NAME", text=unit)
        axis_conts = create_elem(variant, "SW-AXIS-CONTS")
        return value_cont, axis_conts

    def curve_and_map_header(
        self,
        name: str,
        descr: str | None,
        category: str,
        fnc_values: np.ndarray,
        fnc_unit: str = "",
        display_identifier: str | None = None,
        feature_ref: str | None = None,
    ) -> etree._Element:
        """Build header structure for a CURVE or MAP and return the axis_conts element.

        Args:
            name: Parameter short-name.
            descr: Optional description.
            category: CDF category (``"CURVE"``, ``"MAP"``, …).
            fnc_values: Function values array.
            fnc_unit: Function unit display name.
            display_identifier: Optional display identifier.
            feature_ref: Optional feature reference.

        Returns:
            The ``<SW-AXIS-CONTS>`` element to which axes must be appended.
        """
        value_cont, axis_conts = self.instance_container(
            name,
            descr,
            category,
            fnc_unit,
            display_identifier=display_identifier,
            feature_ref=feature_ref,
        )
        vph = create_elem(value_cont, "SW-VALUES-PHYS")
        if not isinstance(fnc_values, np.ndarray):
            fnc_values = np.array(fnc_values)
        self.output_value_array(fnc_values, vph)
        return axis_conts

    def output_value_array(
        self,
        values: np.ndarray,
        value_group: etree._Element,
    ) -> None:
        """Write an ndarray into nested VG/V elements according to CDF structure.

        Uses an iterative stack instead of recursion to avoid
        ``RecursionError`` for deeply nested arrays.

        Args:
            values: N-dimensional array of values.
            value_group: Parent XML element.
        """
        stack: list[tuple[np.ndarray, etree._Element]] = [(values, value_group)]
        while stack:
            arr, parent = stack.pop()
            if arr.ndim == 1:
                self.output_1darray(parent, None, arr)
            else:
                for sub_arr in arr:
                    stack.append((sub_arr, create_elem(parent, "VG")))

    def value_blk(
        self,
        name: str,
        descr: str | None,
        values: np.ndarray,
        unit: str = "",
        display_identifier: str | None = None,
        feature_ref: str | None = None,
    ) -> None:
        """Create VAL_BLK instance with array size and values.

        Args:
            name: Parameter short-name.
            descr: Optional description.
            values: N-dimensional value array.
            unit: Unit display name.
            display_identifier: Optional display identifier.
            feature_ref: Optional feature reference.
        """
        cont = self.no_axis_container(
            name=name,
            descr=descr,
            category="VAL_BLK",
            unit=unit or "",
            display_identifier=display_identifier,
            feature_ref=feature_ref,
        )
        self.output_1darray(cont, "SW-ARRAYSIZE", values.shape[::-1])
        values_cont = create_elem(cont, "SW-VALUES-PHYS")
        self.output_value_array(values, values_cont)

    # ------------------------------------------------------------------
    # Low-level SW-INSTANCE builders
    # ------------------------------------------------------------------

    def sw_instance(
        self,
        name: str,
        descr: str | None,
        category: str,
        display_identifier: str | None = None,
        feature_ref: str | None = None,
    ) -> etree._Element:
        """Create a SW-INSTANCE element with metadata and a properties variant.

        Args:
            name: Parameter short-name.
            descr: Optional long-name / description.
            category: CDF category string.
            display_identifier: Optional display identifier.
            feature_ref: Optional feature reference.

        Returns:
            The ``<SW-INSTANCE-PROPS-VARIANT>`` element to fill with data.
        """
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        instance = create_elem(instance_tree, "SW-INSTANCE")
        create_elem(instance, "SHORT-NAME", text=name)
        if descr:
            create_elem(instance, "LONG-NAME", text=descr)
        if display_identifier:
            create_elem(instance, "DISPLAY-NAME", text=display_identifier)
        create_elem(instance, "CATEGORY", text=category)
        if feature_ref:
            create_elem(instance, "SW-FEATURE-REF", text=feature_ref)
        variants = create_elem(instance, "SW-INSTANCE-PROPS-VARIANTS")
        variant = create_elem(variants, "SW-INSTANCE-PROPS-VARIANT")
        return variant

    def no_axis_container(
        self,
        name: str,
        descr: str | None,
        category: str,
        unit: str = "",
        display_identifier: str | None = None,
        feature_ref: str | None = None,
    ) -> etree._Element:
        """Create a variant instance for a scalar parameter (no axis containers).

        Args:
            name: Parameter short-name.
            descr: Optional description.
            category: CDF category string.
            unit: Unit display name.
            display_identifier: Optional display identifier.
            feature_ref: Optional feature reference.

        Returns:
            The ``<SW-VALUE-CONT>`` element ready for value insertion.
        """
        variant = self.sw_instance(
            name,
            descr,
            category=category,
            display_identifier=display_identifier,
            feature_ref=feature_ref,
        )
        value_cont = create_elem(variant, "SW-VALUE-CONT")
        if unit:
            create_elem(value_cont, "UNIT-DISPLAY-NAME", text=unit)
        return value_cont
