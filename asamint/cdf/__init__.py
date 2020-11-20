#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020 by Christoph Schueler <cpu12.gems.googlemail.com>

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

from itertools import groupby
from operator import attrgetter
from pprint import pprint

import lxml
from lxml.etree import (Comment, Element, ElementTree, DTD, SubElement, XMLSchema, parse, tounicode)
from lxml import etree

from pya2l import DB
import pya2l.model as model
from pya2l.api.inspect import ModCommon, CompuMethod, Characteristic, AxisPts
from pya2l.functions import CompuMethod, fix_axis_par, fix_axis_par_dist, axis_rescale

from asamint.asam import TYPE_SIZES, ByteOrder, get_section_reader
from asamint.utils import (
    get_dtd, create_elem, make_2darray, SINGLE_BITS, cond_create_directories, ffs
)
import asamint.msrsw as msrsw

from objutils import load

DOCTYPE = '''<!DOCTYPE MSRSW PUBLIC "-//ASAM//DTD CALIBRATION DATA FORMAT:V2.0.0:LAI:IAI:XML:CDF200.XSD//EN" "cdf_v2.0.0.sl.dtd">'''

CDF_EXTENSION = "cdfx"

CDF_DTD = get_dtd("cdf_v2.0.0.sl")


class CDFCreator(msrsw.Creator):
    """
    """

    def on_init(self, *args, **kws):
        self._image = args[0]
        self.mod_common = ModCommon.get(self.session)
        self.byte_order = self.mod_common.byteOrder
        cond_create_directories()
        self.cs_collections()
        self.instances()
        with open("CDF20demo.{}".format(CDF_EXTENSION), "wb") as of:
            of.write(etree.tostring(self.root, encoding = "UTF-8", pretty_print = True, xml_declaration = True, doctype = DOCTYPE))

    @property
    def image(self):
        return self._image

    def _toplevel_boilerplate(self):
        root = Element("MSRSW")
        create_elem(root, "CATEGORY", "CDF20")
        sw_systems = create_elem(root, "SW-SYSTEMS")
        sw_system = create_elem(sw_systems, "SW-SYSTEM")
        self.common_elements(sw_system, "FOO", "FOO do_er")
        self.sub_trees["SW-SYSTEM"] = sw_system

        instance_spec = create_elem(sw_system, "SW-INSTANCE-SPEC")
        instance_tree = create_elem(instance_spec, "SW-INSTANCE-TREE")
        self.sub_trees["SW-INSTANCE-TREE"] = instance_tree
        create_elem(instance_tree, "SHORT-NAME", text = "ETAS\CalDemo_V2a\CalDemo_V2\CalDemo_V2_1") # i.e. A2L name.
        create_elem(instance_tree, "CATEGORY", text = "NO_VCD") # or VCD, variant-coding f.parameters.
        return root

    def cs_collection(self, name, category, tree):
        collection = create_elem(tree, "SW-CS-COLLECTION")
        create_elem(collection, "CATEGORY", text = category)
        create_elem(collection, "SW-COLLECTION-REF", text = name)

    def cs_collections(self):
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        collections = create_elem(instance_tree, "SW-CS-COLLECTIONS")
        functions = self.query(model.Function).all()
        functions = [f for f in functions if f.def_characteristic and f.def_characteristic.identifier != []]
        for f in functions:
            self.cs_collection(f.name, "FEATURE", collections)
        groups = self.query(model.Group).all()
        for g in groups:
            self.cs_collection(g.groupName, "COLLECTION", collections)

    def instances(self):
        result = []
        print("=" * 79)
        print("AXIS_PTSs")
        print("=" * 79)
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            print(ax.name, hex(ax.address), ax.record_layout_components.sizeof, mem_size)

        print("=" * 79)
        print("CHARACTERISTICs")
        print("=" * 79)

        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()

#        cxx = groupby(characteristics, lambda x: x.type)
#        for group_name, items in cxx:
#            print(group_name, items)

        for c in characteristics:
            chx = Characteristic.get(self.session, c.name)

            print("\t", chx.type)
            print(chx.name, hex(chx.address), chx.record_layout_components.sizeof)
            compuMethod = chx.compuMethod
            datatype = chx.deposit.fncValues['datatype']
            fnc_asam_dtype = chx.fnc_asam_dtype
            fnc_np_dtype = chx.fnc_np_dtype
            fnc_np_shape = chx.fnc_np_shape
            fnc_np_order = chx.fnc_np_order
            fnc_element_size = chx.fnc_element_size
            if chx.byteOrder is None:
                chx.byteOrder = "MSB_LAST"
            byte_order = ByteOrder.LITTE_ENDIAN if chx.byteOrder in ("MSB_LAST", "LITTLE_ENDIAN") else ByteOrder.BIG_ENDIAN
            reader = get_section_reader(datatype, byte_order)
            if chx._conversionRef != "NO_COMPU_METHOD":
                #cm_obj = self.query(model.CompuMethod).filter(model.CompuMethod.name == chx._conversionRef).first()
                cm = CompuMethod(self.session, compuMethod)
            unit = chx.physUnit
            dim = chx.dim
            mem_size = chx.total_allocated_memory
            if chx.type == "VALUE":
                if chx.bitMask:
                    value = self.image.read_numeric(chx.address, reader, bit_mask = chx.bitMask)
                    value >>= ffs(chx.bitMask) # "Built-in" right-shift to get rid of trailing zeros (s. ASAM 2-MC spec).
                    is_bool = True if chx.bitMask in SINGLE_BITS else False
                else:
                    value = self.image.read_numeric(chx.address, reader)
                    is_bool = False
                conv_value = cm.int_to_physical(value)
                if chx.dependentCharacteristic is not None:
                    category = "DEPENDENT_VALUE"
                else:
                    category = "BOOLEAN" if is_bool else "VALUE"
                if is_bool and isinstance(conv_value, (int, float)):
                    conv_value = "true" if bool(conv_value) else "false"
                else:
                    category = "VALUE"  # Enums are regualar VALUEs
                self.instance_scalar(chx.name, chx.longIdentifier, conv_value, unit = unit, category = category)
            elif chx.type == "ASCII":
                if chx.matrixDim:
                    length = chx.matrixDim["x"]
                else:
                    length = chx.number
                value = self.image.read_string(chx.address, length = length)
                self.instance_scalar(chx.name, chx.longIdentifier, value, category = "ASCII", unit = unit)
            elif chx.type == "VAL_BLK":
                length = chx.fnc_allocated_memory
                np_arr = self.image.read_ndarray(
                    addr = chx.address,
                    length = length,
                    dtype = reader,
                    shape = chx.fnc_np_shape,
                    order = chx.fnc_np_order,
                    bit_mask = chx.bitMask
                )
                self.value_blk(
                    name = chx.name,
                    descr = chx.longIdentifier,
                    values = cm.int_to_physical(np_arr),
                    unit = unit,
                )
            elif chx.type == "CURVE":
                axis_descr = chx.axisDescriptions[0]
                maxAxisPoints = axis_descr.maxAxisPoints
                axis_pts_cm = axis_descr.compuMethod
                if axis_descr.attribute == "FIX_AXIS":
                    if axis_descr.fixAxisParDist:
                        par_dist = axis_descr.fixAxisParDist
                        raw_axis_values = fix_axis_par_dist(par_dist['offset'], par_dist['distance'], par_dist['numberapo'])
                    elif axis_descr.fixAxisParList:
                        raw_axis_values = axis.fixAxisParList
                    elif axis_descr.fixAxisPar:
                        par = axis_descr.fixAxisPar
                        raw_axis_values = fix_axis_par(par['offset'], par['shift'], par['numberapo'])
                    axis_cm = CompuMethod(self.session, axis_pts_cm)
                    axis_values = axis_cm.int_to_physical(raw_axis_values)
                    self.fix_axis_curve(
                        chx.name, chx.longIdentifier, axis_values, [], axis_unit = axis_descr.compuMethod.unit
                    )
                    #print("*** FIX-AXIS", hex(chx.address), chx.record_layout_components, chx.record_layout_components.axes_names, mem_size)
                elif axis_descr.attribute == "STD_AXIS":
                    #print("*** STD-AXIS", chx.name, axis_descr, chx.record_layout_components, mem_size)
                    pass
                elif axis_descr.attribute == "RES_AXIS":
                    #print("*** RES-AXIS {}".format(axis_descr.axisPtsRef.depositAttr))
                    pass
                elif axis_descr.attribute == "COM_AXIS":
                    #print("*** COM-AXIS {}".format(axis_descr.axisPtsRef.depositAttr))   #
                    pass
                elif axis_descr.attribute == "CURVE_AXIS":
                    #print("*** CURVE-AXIS {}".format(axis_descr.axisPtsRef))   # .depositAttr.components
                    pass
        pass


    def int_to_physical(self, cm_name, raw_values):
        """
        """
        cm_obj = self.query(model.CompuMethod).filter(model.CompuMethod.name == cm_name).first()
        cm = CompuMethod(self.session, cm_obj)
        values = axis_cm.int_to_physical(raw_values)
        return values

    def instance_scalar(self, name, descr, value, category = "VALUE", unit = "", feature_ref = None):
        """
        VALUE
        DEPENDENT_VALUE
        BOOLEAN
        ASCII
        VAL_BLK

        CURVE
        MAP
        COM_AXIS
        CURVE_AXIS
        RES_AXIS
        VALUE_ARRAY
        CURVE_ARRAY
        MAP_ARRAY
        STRUCTURE_ARRAY

        STRUCTURE
        UNION
        """
        cont = self.no_axis_container(name, descr, category, unit, feature_ref)
        values = create_elem(cont, "SW-VALUES-PHYS")

        if isinstance(value, str) and value:
            create_elem(values, "VT", text = str(value))
        else:
            create_elem(values, "V", text = str(value))

    def add_axis(self, axis_conts, axis_values, category, unit = ""):
        axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
        create_elem(axis_cont, "CATEGORY", text = category)
        if unit:
            create_elem(axis_cont, "UNIT-DISPLAY-NAME", text = unit)
        self.output_1darray(axis_cont, "SW-VALUES-PHYS", axis_values)

    def fix_axis_curve(self, name, descr, x_axis_values, func_values, axis_unit = "", values_unit = "", feature_ref = None):
        value_cont, axis_conts = self.axis_container(name, descr, "CURVE", axis_unit, feature_ref)

        self.add_axis(axis_conts, x_axis_values, "FIX_AXIS", axis_unit)

        #self.output_1darray(value_cont, "SW-ARRAYSIZE", reversed(func_values.shape))
        #values_phys = create_elem(value_cont, "SW-VALUES-PHYS")
        #values = make_2darray(func_values)
        #for idx in range(values.shape[0]):
        #    row = values[idx: idx + 1].reshape(values.shape[1])
        #    vg = create_elem(values_phys, "VG")
        #    self.output_1darray(vg, None, row)

    def output_value_array(self, values, value_group):
        """
        """
        if values.ndim == 1:
            self.output_1darray(value_group, None, values)
        else:
            for elem in values:
                self.output_value_array(elem, create_elem(value_group, "VG"))

    def value_blk(self, name, descr, values, unit = "", feature_ref = None):
        """
        """
        cont = self.no_axis_container(name, descr, "VAL_BLK", unit, feature_ref)
        self.output_1darray(cont, "SW-ARRAYSIZE", reversed(values.shape))
        values_cont = create_elem(cont, "SW-VALUES-PHYS")
        self.output_value_array(values, values_cont)

    def sw_instance(self, name, descr, category = "VALUE", feature_ref = None):
        instance_tree = self.sub_trees["SW-INSTANCE-TREE"]
        instance = create_elem(instance_tree, "SW-INSTANCE")
        create_elem(instance, "SHORT-NAME", text = name)
        if descr:
            create_elem(instance, "LONG-NAME", text = descr)
        create_elem(instance, "CATEGORY", text = category)
        if feature_ref:
            create_elem(instance, "SW-FEATURE-REF", text = feature_ref)
        variants = create_elem(instance, "SW-INSTANCE-PROPS-VARIANTS")
        variant = create_elem(variants, "SW-INSTANCE-PROPS-VARIANT")
        return variant

    def no_axis_container(self, name, descr, category = "VALUE", unit = "", feature_ref = None):
        variant = self.sw_instance(name, descr, category = category, feature_ref = None)
        value_cont = create_elem(variant, "SW-VALUE-CONT")
        if unit:
            create_elem(value_cont, "UNIT-DISPLAY-NAME", text = unit)
        return value_cont

    def axis_container(self, name, descr, category = "VALUE", unit = "", feature_ref = None):
        variant = self.sw_instance(name, descr, category = category, feature_ref = None)
        value_cont = create_elem(variant, "SW-VALUE-CONT")
        if unit:
            create_elem(value_cont, "UNIT-DISPLAY-NAME", text = unit)
        axis_conts = create_elem(variant, "SW-AXIS-CONTS")
        return value_cont, axis_conts
