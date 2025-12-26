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

import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Dict, List, Optional

import h5py
import numpy as np
import xarray as xr
from lxml import etree  # nosec
from pya2l import model

from asamint import msrsw
from asamint.calibration import CalibrationData
from asamint.calibration.msrsw_db import MSRSWDatabase
from asamint.utils import add_suffix_to_path
from asamint.utils.xml import create_elem, xml_comment

from .importer import DBImporter

__all__ = ["DB", "CDFCreator", "DBImporter"]


# sns.set_theme("notebook")

sys.setrecursionlimit(2000)


class DB:
    """Lightweight reader for CDF HDF5 payload produced by the importer.

    Opens the companion .h5 store next to the .msrswdb and allows loading
    parameters into xarray.DataArray structures.
    """

    def __init__(self, file_name: str) -> None:
        self.opened = False
        db_name = Path(file_name).with_suffix(".msrswdb")
        # self.logger = logger
        # self.logger.info(f"Creating database {str(db_name)!r}.")
        self.db = MSRSWDatabase(db_name, debug=False)
        self.session = self.db.session
        self.storage = h5py.File(
            db_name.with_suffix(".h5"), mode="r", libver="latest", locking="best-effort"
        )
        self.opened = True
        self.guid = uuid.uuid4()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if self.opened:
            self.storage.close()
            self.db.close()
            self.opened = False

    def load(self, name: str) -> xr.DataArray:
        # self.session.query(model.ShortName).filter(model.ShortName.content == name)
        # inst = self.session.query(model.SwInstance).join(model.ShortName).filter(model.ShortName.content == name).first()
        # category = inst.category.content

        ds = self.storage[f"/{name}"]
        ds_attrs = dict(ds.attrs.items())
        category = ds_attrs["category"]
        attrs = {
            "name": name,
            "display_identifier": ds_attrs.get("display_identifier") or "",
            "category": category,
            "comment": ds_attrs.get("comment") or "",
        }
        values = ds["phys"][()]
        if category in (
            "VALUE",
            "DEPENDENT_VALUE",
            "BOOLEAN",
            "ASCII",
            "TEXT",
        ) or category in ("VAL_BLK", "COM_AXIS"):
            arr = xr.DataArray(values, attrs=attrs)
        else:
            axes = ds["axes"]
            # axes_attrs = dict(axes.attrs.items())
            dims = []
            coords = {}
            shape = []
            for idx in range(len(axes)):
                ax = axes[str(idx)]
                ax_attrs = dict(ax.attrs.items())
                ax_items = dict(ax.items())
                ax_name = ax_attrs["name"]
                dims.append(ax_name)
                category = ax_attrs["category"]
                if category == "COM_AXIS":
                    ref_axis = ax_items["reference"]
                    # raw = np.array(ref_axis["raw"])
                    phys = np.array(ref_axis["phys"])
                else:
                    if category not in ("FIX_AXIS", "STD_AXIS"):
                        raise TypeError(f"{category} axis")
                    phys = np.array(ax_items["phys"])
                coords[ax_name] = phys
                shape.append(phys.size)
            if values.shape == (0,):  # TODO: fix while saving!?
                values = np.zeros(tuple(shape))
            arr = xr.DataArray(values, dims=dims, coords=coords, attrs=attrs)
        return arr


class CDFCreator(msrsw.MSRMixIn, CalibrationData):
    """Exporter that creates an ASAM CDF20 XML (.cdfx) from loaded calibration parameters.

    It relies on MSRMixIn for XML scaffolding and CalibrationData's loaded parameter
    dictionary. Methods here build the required CDF structure and write it via the
    mixin's XML utilities.
    """

    DOCTYPE: str = (
        """<!DOCTYPE MSRSW PUBLIC "-//ASAM//DTD CALIBRATION DATA FORMAT:V2.0.0:LAI:IAI:XML:CDF200.XSD//EN" "cdf_v2.0.0.sl.dtd">"""
    )
    # DTD = get_dtd("cdf_v2.0.0.sl")    # TODO: check!!!
    EXTENSION = ".cdfx"

    def __init__(self, parameters: Mapping[str, dict[str, Any]]) -> None:
        super().__init__()
        self._parameters = parameters

    def on_init(self, config: Any, *args: Any, **kws: Any) -> None:
        print("CDFCreator", config, *args, **kws)
        super().on_init(config, *args, **kws)

    def save(self) -> None:
        self.root = self._toplevel_boilerplate()
        self.tree = etree.ElementTree(self.root)
        self.cs_collections()
        self.instances()
        self.write_tree("CDF20demo")

    def _toplevel_boilerplate(self) -> Any:
        # print(f"A2L: {self.a2l_file}")
        root = self.msrsw_header("CDF20", "CDF")
        sw_system = self.sub_trees["SW-SYSTEM"]
        instance_spec = create_elem(sw_system, "SW-INSTANCE-SPEC")
        instance_tree = create_elem(instance_spec, "SW-INSTANCE-TREE")
        self.sub_trees["SW-INSTANCE-TREE"] = instance_tree
        create_elem(instance_tree, "SHORT-NAME", text="STD")
        create_elem(
            instance_tree, "CATEGORY", text="NO_VCD"
        )  # or VCD, variant-coding f.parameters.
        instance_tree_origin = create_elem(instance_tree, "SW-INSTANCE-TREE-ORIGIN")
        create_elem(
            instance_tree_origin,
            "SYMBOLIC-FILE",
            add_suffix_to_path(self.a2l_file, ".a2l"),
        )
        # data_file_name = self.image.file_name
        # if data_file_name:
        #    create_elem(instance_tree_origin, "DATA-FILE", data_file_name)
        return root

    def cs_collection(
        self, name: str, category: str, tree: Any, is_group: bool
    ) -> None:
        collection = create_elem(tree, "SW-CS-COLLECTION")
        create_elem(collection, "CATEGORY", text=category)
        if is_group:
            create_elem(collection, "SW-COLLECTION-REF", text=name)
        else:
            create_elem(collection, "SW-FEATURE-REF", text=name)

    def cs_collections(self) -> None:
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        collections = create_elem(instance_tree, "SW-CS-COLLECTIONS")
        functions = self.query(model.Function).all()
        functions = [
            f
            for f in functions
            if f.def_characteristic and f.def_characteristic.identifier != []
        ]
        for f in functions:
            self.cs_collection(f.name, "FEATURE", collections, False)
        groups = self.query(model.Group).all()
        for g in groups:
            self.cs_collection(g.groupName, "COLLECTION", collections, True)

    def instances(self) -> None:
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        xml_comment(instance_tree, "    AXIS_PTSs ")
        for key, inst in self._parameters["AXIS_PTS"].items():
            variant = self.sw_instance(
                name=inst.name,
                descr=inst.comment,
                category=inst.category,
                displayIdentifier=inst.displayIdentifier,
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
                displayIdentifier=inst.displayIdentifier,
                category=inst.category,
            )
        xml_comment(instance_tree, "    ASCIIs    ")
        for key, inst in self._parameters["ASCII"].items():
            self.instance_scalar(
                name=key,
                descr=inst.comment,
                value=inst.phys,
                category="ASCII",
                unit=None,
                displayIdentifier=inst.displayIdentifier,
            )
        xml_comment(instance_tree, "    VAL_BLKs  ")
        for key, inst in self._parameters["VAL_BLK"].items():
            self.value_blk(
                name=key,
                descr=inst.comment,
                values=inst.phys,
                displayIdentifier=inst.displayIdentifier,
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
        for key, inst in self._parameters[attribute].items():
            if list(inst.phys) == []:
                self.logger.warning(f"{attribute} {inst.name!r}: has no values.")
                continue
            axis_conts = self.curve_and_map_header(
                name=inst.name,
                descr=inst.comment,
                category=attribute,
                fnc_values=inst.phys,
                fnc_unit=inst.fnc_unit,
                displayIdentifier=inst.displayIdentifier,
                feature_ref=None,
            )
            for axis in inst.axes:
                category = axis.category
                if category == "STD_AXIS":
                    self.add_axis(axis_conts, axis.phys, "STD_AXIS", axis.unit)
                elif category == "FIX_AXIS":
                    self.add_axis(axis_conts, axis.phys, "FIX_AXIS", axis.unit)
                elif category == "COM_AXIS":
                    axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
                    create_elem(axis_cont, "CATEGORY", "COM_AXIS")
                    create_elem(axis_cont, "SW-INSTANCE-REF", text=axis.axis_pts_ref)
                elif category == "RES_AXIS":
                    axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
                    create_elem(axis_cont, "CATEGORY", "RES_AXIS")
                    create_elem(axis_cont, "SW-INSTANCE-REF", text=axis.axis_pts_ref)
                elif category == "CURVE_AXIS":
                    axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
                    create_elem(axis_cont, "CATEGORY", "CURVE_AXIS")
                    create_elem(axis_cont, "SW-INSTANCE-REF", text=axis.axis_pts_ref)

    def instance_scalar(
        self,
        name: str,
        descr: str | None,
        value: Any,
        category: str,
        unit: str | None = "",
        displayIdentifier: str | None = None,
        feature_ref: str | None = None,
    ) -> None:
        if category == "TEXT":
            is_text = True
            category = "VALUE"
        elif category in ("BOOLEAN", "ASCII"):
            is_text = True
        else:
            is_text = False
        cont = self.no_axis_container(
            name=name,
            descr=descr,
            category=category,
            unit=unit,
            displayIdentifier=displayIdentifier,
            feature_ref=feature_ref,
        )
        values = create_elem(cont, "SW-VALUES-PHYS")
        if is_text and value:
            create_elem(values, "VT", text=str(value))
        else:
            create_elem(values, "V", text=str(value))

    def add_axis(
        self, axis_conts: Any, axis_values: np.ndarray, category: str, unit: str = ""
    ) -> None:
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
        displayIdentifier: str | None = None,
        feature_ref: str | None = None,
    ) -> tuple[Any, Any]:
        variant = self.sw_instance(
            name,
            descr,
            category=category,
            displayIdentifier=displayIdentifier,
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
        displayIdentifier: str | None = None,
        feature_ref: str | None = None,
    ) -> Any:
        value_cont, axis_conts = self.instance_container(
            name,
            descr,
            category,
            fnc_unit,
            displayIdentifier=displayIdentifier,
            feature_ref=feature_ref,
        )
        vph = create_elem(value_cont, "SW-VALUES-PHYS")
        if not isinstance(fnc_values, np.ndarray):
            fnc_values = np.array(fnc_values)
        self.output_value_array(fnc_values, vph)
        return axis_conts

    def output_value_array(self, values: np.ndarray, value_group: Any) -> None:
        """Write an ndarray into nested VG/V elements according to CDF structure."""
        if values.ndim == 1:
            self.output_1darray(value_group, None, values)
        else:
            for elem in values:
                self.output_value_array(elem, create_elem(value_group, "VG"))

    def value_blk(
        self,
        name: str,
        descr: str | None,
        values: np.ndarray,
        unit: str = "",
        displayIdentifier: str | None = None,
        feature_ref: str | None = None,
    ) -> None:
        """Create VAL_BLK instance with array size and values."""
        cont = self.no_axis_container(
            name=name,
            descr=descr,
            category="VAL_BLK",
            unit=unit,
            displayIdentifier=displayIdentifier,
            feature_ref=feature_ref,
        )
        self.output_1darray(cont, "SW-ARRAYSIZE", values.shape)
        values_cont = create_elem(cont, "SW-VALUES-PHYS")
        self.output_value_array(values, values_cont)

    def sw_instance(
        self,
        name: str,
        descr: str | None,
        category: str,
        displayIdentifier: str | None = None,
        feature_ref: str | None = None,
    ) -> Any:
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        instance = create_elem(instance_tree, "SW-INSTANCE")
        create_elem(instance, "SHORT-NAME", text=name)
        if descr:
            create_elem(instance, "LONG-NAME", text=descr)
        if displayIdentifier:
            create_elem(instance, "DISPLAY-NAME", text=displayIdentifier)
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
        displayIdentifier: str | None = None,
        feature_ref: str | None = None,
    ) -> Any:
        variant = self.sw_instance(
            name,
            descr,
            category=category,
            displayIdentifier=displayIdentifier,
            feature_ref=feature_ref,
        )
        value_cont = create_elem(variant, "SW-VALUE-CONT")
        if unit:
            create_elem(value_cont, "UNIT-DISPLAY-NAME", text=unit)
        return value_cont
