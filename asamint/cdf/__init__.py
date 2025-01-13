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

import numpy as np
import pya2l.model as model
from lxml import etree  # nosec

import asamint.msrsw as msrsw
from asamint.calibration import CalibrationData
from asamint.utils import add_suffix_to_path
from asamint.utils.xml import create_elem, xml_comment


class CDFCreator(msrsw.MSRMixIn, CalibrationData):
    """ """

    DOCTYPE = (
        """<!DOCTYPE MSRSW PUBLIC "-//ASAM//DTD CALIBRATION DATA FORMAT:V2.0.0:LAI:IAI:XML:CDF200.XSD//EN" "cdf_v2.0.0.sl.dtd">"""
    )
    # DTD = get_dtd("cdf_v2.0.0.sl")    # TODO: check!!!
    EXTENSION = ".cdfx"

    def on_init(self, project_config, experiment_config, *args, **kws):
        super().on_init(project_config, experiment_config, *args, **kws)

    def save(self):
        self.root = self._toplevel_boilerplate()
        self.tree = etree.ElementTree(self.root)
        self.cs_collections()
        self.instances()
        self.write_tree("CDF20demo")

    def _toplevel_boilerplate(self):
        print(f"A2L: {self.a2l_file}")
        root = self.msrsw_header("CDF20", "CDF")
        sw_system = self.sub_trees["SW-SYSTEM"]
        instance_spec = create_elem(sw_system, "SW-INSTANCE-SPEC")
        instance_tree = create_elem(instance_spec, "SW-INSTANCE-TREE")
        self.sub_trees["SW-INSTANCE-TREE"] = instance_tree
        create_elem(instance_tree, "SHORT-NAME", text="STD")
        create_elem(instance_tree, "CATEGORY", text="NO_VCD")  # or VCD, variant-coding f.parameters.
        instance_tree_origin = create_elem(instance_tree, "SW-INSTANCE-TREE-ORIGIN")
        create_elem(
            instance_tree_origin,
            "SYMBOLIC-FILE",
            add_suffix_to_path(self.a2l_file, ".a2l"),
        )
        data_file_name = self.image.file_name
        if data_file_name:
            create_elem(instance_tree_origin, "DATA-FILE", data_file_name)
        return root

    def cs_collection(self, name: str, category: str, tree, is_group: bool):
        collection = create_elem(tree, "SW-CS-COLLECTION")
        create_elem(collection, "CATEGORY", text=category)
        if is_group:
            create_elem(collection, "SW-COLLECTION-REF", text=name)
        else:
            create_elem(collection, "SW-FEATURE-REF", text=name)

    def cs_collections(self):
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        collections = create_elem(instance_tree, "SW-CS-COLLECTIONS")
        functions = self.query(model.Function).all()
        functions = [f for f in functions if f.def_characteristic and f.def_characteristic.identifier != []]
        for f in functions:
            self.cs_collection(f.name, "FEATURE", collections, False)
        groups = self.query(model.Group).all()
        for g in groups:
            self.cs_collection(g.groupName, "COLLECTION", collections, True)

    def instances(self):
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
            self.output_1darray(value_cont, "SW-VALUES-PHYS", inst.converted_values)
        xml_comment(instance_tree, "    VALUEs    ")
        for key, inst in self._parameters["VALUE"].items():
            self.instance_scalar(
                name=key,
                descr=inst.comment,
                value=inst.converted_value,
                unit=inst.unit,
                displayIdentifier=inst.displayIdentifier,
                category=inst.category,
            )
        xml_comment(instance_tree, "    ASCIIs    ")
        for key, inst in self._parameters["ASCII"].items():
            self.instance_scalar(
                name=key,
                descr=inst.comment,
                value=inst.value,
                category="ASCII",
                unit=None,
                displayIdentifier=inst.displayIdentifier,
            )
        xml_comment(instance_tree, "    VAL_BLKs  ")
        for key, inst in self._parameters["VAL_BLK"].items():
            self.value_blk(
                name=key,
                descr=inst.comment,
                values=inst.converted_values,
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

    def dump_array(self, attribute):
        for key, inst in self._parameters[attribute].items():
            axis_conts = self.curve_and_map_header(
                name=inst.name,
                descr=inst.comment,
                category=attribute,
                fnc_values=inst.converted_values,
                fnc_unit=inst.fnc_unit,
                displayIdentifier=inst.displayIdentifier,
                feature_ref=None,
            )
            for axis in inst.axes:
                category = axis.category
                if category == "STD_AXIS":
                    self.add_axis(axis_conts, axis.converted_values, "STD_AXIS", axis.unit)
                elif category == "FIX_AXIS":
                    self.add_axis(axis_conts, axis.converted_values, "FIX_AXIS", axis.unit)
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
                    create_elem(axis_cont, "SW-INSTANCE-REF", text=axis.curve_axis_ref)

    def instance_scalar(
        self,
        name,
        descr,
        value,
        category,
        unit="",
        displayIdentifier=None,
        feature_ref=None,
    ):
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

    def add_axis(self, axis_conts, axis_values, category, unit=""):
        axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
        create_elem(axis_cont, "CATEGORY", text=category)
        if unit:
            create_elem(axis_cont, "UNIT-DISPLAY-NAME", text=unit)
        self.output_1darray(axis_cont, "SW-VALUES-PHYS", axis_values)

    def instance_container(
        self,
        name,
        descr,
        category="VALUE",
        unit="",
        displayIdentifier=None,
        feature_ref=None,
    ):
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
        name,
        descr,
        category,
        fnc_values,
        fnc_unit="",
        displayIdentifier=None,
        feature_ref=None,
    ):
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
            print(f"obj {fnc_values} is not `numpy`.")
        self.output_value_array(fnc_values, vph)
        return axis_conts

    def output_value_array(self, values, value_group):
        """ """
        if values.ndim == 1:
            self.output_1darray(value_group, None, values)
        else:
            for elem in values:
                self.output_value_array(elem, create_elem(value_group, "VG"))

    def value_blk(self, name, descr, values, unit="", displayIdentifier=None, feature_ref=None):
        """ """
        cont = self.no_axis_container(
            name=name,
            descr=descr,
            category="VAL_BLK",
            unit=unit,
            displayIdentifier=displayIdentifier,
            feature_ref=feature_ref,
        )
        self.output_1darray(cont, "SW-ARRAYSIZE", reversed(values.shape))
        values_cont = create_elem(cont, "SW-VALUES-PHYS")
        self.output_value_array(values, values_cont)

    def sw_instance(self, name, descr, category, displayIdentifier=None, feature_ref=None):
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

    def no_axis_container(self, name, descr, category, unit="", displayIdentifier=None, feature_ref=None):
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
