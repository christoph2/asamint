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

from operator import attrgetter
from pprint import pprint

import lxml
from lxml.etree import (Comment, Element, ElementTree, DTD, SubElement, XMLSchema, parse, tounicode)
from lxml import etree

from pya2l import DB
import pya2l.model as model
from pya2l.api.inspect import ModCommon, _dissect_conversion, Characteristic
from pya2l.functions import CompuMethod, fix_axis_par, fix_axis_par_dist, axis_rescale

from asamint.asam import get_dtd, MCObject, TYPE_SIZES, make_continuous_blocks, ByteOrder, get_section_reader
from asamint.utils import create_elem, make_2darray, SINGLE_BITS
import asamint.msrsw as msrsw

from objutils import load

DOCTYPE = '''<!DOCTYPE MSRSW PUBLIC "-//ASAM//DTD CALIBRATION DATA FORMAT:V2.0.0:LAI:IAI:XML:CDF200.XSD//EN" "cdf_v2.0.0.sl.dtd">'''

CDF_EXTENSION = ".cdfx"

CDF_DTD = get_dtd("cdf_v2.0.0.sl")

HEX = load("ihex", open("CDF20Demo.hex", "rb"))


class Creator(msrsw.Creator):
    """
    """

    def on_init(self):
        self.mod_common = ModCommon(self.session_obj)
        self.byte_order = self.mod_common.byteOrder
        self.cs_collections()
        self.instances()

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
        create_elem(instance_tree, "CATEGORY", text = "VCD") # or NO_VCD -- variant-coding f.parameters.
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
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        result = []
        for c in characteristics:
            chx = Characteristic(self.session_obj, c.name)
            datatype = chx.deposit.fncValues['datatype']

            np_dtype = chx.np_dtype
            np_shape = chx.np_shape
            np_order = chx.np_order
            type_size = TYPE_SIZES[datatype]
            if chx.byteOrder is None:
                chx.byteOrder = "MSB_LAST"
            byte_order = ByteOrder.LITTE_ENDIAN if chx.byteOrder in ("MSB_LAST", "LITTLE_ENDIAN") else ByteOrder.BIG_ENDIAN
            reader = get_section_reader(datatype, byte_order)
            cm_obj = self.query(model.CompuMethod).filter(model.CompuMethod.name == chx._conversionRef).first()
            cm = CompuMethod(self.session_obj, cm_obj)
            unit = chx.physUnit
            print("CHAR:", chx.name, chx.type, chx.np_dtype, chx.np_shape, chx.np_order, chx.deposit.components, cm_obj.conversionType)
            if chx.type == "VALUE":
                value = HEX.read_numeric(chx.address, reader, bit_mask = chx.bitMask)
                conv_value = cm.int_to_physical(value)
                print("VALUE:", chx.name, chx.type, hex(chx.address), chx.deposit.fncValues['datatype'], hex(chx.bitMask), value, conv_value)
                result.append(MCObject(chx.name, chx.address, type_size))

                if chx.dependentCharacteristic is not None:
                    category = "DEPENDENT_VALUE"
                else:
                    category = "VALUE"
                self.instance_scalar(chx.name, chx.longIdentifier, conv_value, unit = unit, category = category)
                if conv_value in SINGLE_BITS:
                    print("\t***BOOL", conv_value)
            elif chx.type == "ASCII":
                length = chx.matrixDim["x"]
                value = HEX.read_string(chx.address, length = length)
                print("*ASCII: '''{}'''".format(value), len(value))
                result.append(MCObject(chx.name, chx.address, length))
                self.instance_scalar(chx.name, chx.longIdentifier, value, category = "ASCII", unit = unit)
            elif chx.type == "VAL_BLK":
                x, y, z = chx.matrixDim['x'], chx.matrixDim['y'], chx.matrixDim['z']
                length = x * y *z
                np_arr = HEX.read_ndarray(addr = chx.address, length = length, dtype = reader, shape = chx.np_shape, order = chx.np_order, bit_mask = chx.bitMask)
                pprint(cm.int_to_physical(np_arr))
                result.append(MCObject(chx.name, chx.address, length))
                self.value_array(
                    name = chx.name, descr = chx.longIdentifier, value = cm.int_to_physical(np_arr), unit = unit
                )
            elif chx.type == "CURVE":
                if chx.name == "CDF20.curve.KL_xRESs8_wS16":
                    pass
                    #print(chx)
                # CDF20.curve.KL_xU8_wU8 CURVE
                for idx, axis in enumerate(chx.axisDescriptions):
                    #axisPtsRef
                    #print("*** AXIS #{} {}".format(idx, axis))
                    if axis.attribute == "FIX_AXIS":
                        """
                        fixAxisPar      = None;
                        fixAxisParDist  = {'numberapo': 6, 'offset': 1, 'distance': 1};
                        fixAxisParList  = [];
                        """

                        """
                        The keywords FIX_AXIS_PAR, FIX_AXIS_PAR_DIST, DEPOSIT and FIX_AXIS_PAR_LIST are mutually exclusive,
                        i.e. at most one of these keywords is allowed to be used at the same AXIS_DESCR record.
                        """
                        if axis.fixAxisParDist:
                            par_dist = axis.fixAxisParDist
                            raw_axis_values = fix_axis_par_dist(par_dist['offset'], par_dist['distance'], par_dist['numberapo'])

                            axis_cm_obj = self.query(model.CompuMethod).filter(model.CompuMethod.name == axis._conversionRef).first()
                            axis_cm = CompuMethod(self.session_obj, axis_cm_obj)
                            axis_values = axis_cm.int_to_physical(raw_axis_values)

                            print("\tAXIS_VALUES:", raw_axis_values, axis_values, axis._conversionRef, axis.compuMethod)
                        elif axis.fixAxisParList:
                            raw_axis_values =axis.fixAxisParList

                            axis_cm_obj = self.query(model.CompuMethod).filter(model.CompuMethod.name == axis._conversionRef).first()
                            axis_cm = CompuMethod(self.session_obj, axis_cm_obj)
                            axis_values = axis_cm.int_to_physical(raw_axis_values)

                        elif axis.fixAxisPar:
                            par = axis.fixAxisPar
                            raw_axis_values = fix_axis_par(par['offset'], par['shift'], par['numberapo'])

                            axis_cm_obj = self.query(model.CompuMethod).filter(model.CompuMethod.name == axis._conversionRef).first()
                            axis_cm = CompuMethod(self.session_obj, axis_cm_obj)
                            axis_values = axis_cm.int_to_physical(raw_axis_values)

                            print("\tAXIS_VALUES [SHIFT]:", raw_axis_values, axis_values, axis._conversionRef, axis.compuMethod)

                        else:
                            pass
                    elif axis.attribute == "STD_AXIS":
                        print("\t*RES_AXIS")
                        #print("*** STD-AXIS #{} {}".format(idx, axis))
                    elif axis.attribute == "RES_AXIS":
                        print("\t*RES_AXIS")
                        #print("*** RES-AXIS #{} {}".format(idx, axis.axisPtsRef.depositAttr.components))
                    elif axis.attribute == "COM_AXIS":
                        components = axis.axisPtsRef.depositAttr.components
                        print("*** COM-AXIS #{} {}".format(idx, axis.axisPtsRef))   # .depositAttr.components

                        print("\tCOMPO:", chx.deposit.components, components)
                        #address = axis.address
                        maxAxisPoints = axis.maxAxisPoints
                        #reader = get_section_reader(datatype, byte_order)

                        #np_arr = HEX.read_ndarray(addr = address, length = length, dtype = reader, shape = chx.np_shape, order = chx.np_order, bit_mask = chx.bitMask)
                    else:
                        print("\t*NOW?")    # FIX_AXIS,STD_AXIS, RES_AXIS, COM_AXIS, CURVE_AXIS,
            #
        make_continuous_blocks(result)

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
        cont = self.value_container(name, descr, value, category, unit, feature_ref)
        values = create_elem(cont, "SW-VALUES-PHYS")

        if isinstance(value, str) and value:
            create_elem(values, "VT", text = str(value))
        else:
            create_elem(values, "V", text = str(value))

    def value_array(self, name, descr, value, unit = "", feature_ref = None):
        cont = self.value_container(name, descr, value, "VAL_BLK", unit, feature_ref)
        self.output_1darray(cont, "SW-ARRAYSIZE", reversed(value.shape))
        values_cont = create_elem(cont, "SW-VALUES-PHYS")
        values = make_2darray(value)

        for idx in range(values.shape[0]):
            row = values[idx: idx + 1].reshape(values.shape[1])
            vg = create_elem(values_cont, "VG")
            self.output_1darray(vg, None, row)

    def value_container(self, name, descr, value, category = "VALUE", unit = "", feature_ref = None):
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
        cont = create_elem(variant, "SW-VALUE-CONT")
        if unit:
            create_elem(cont, "UNIT-DISPLAY-NAME", text = unit)
        return cont

    def instance_value_block(self, name, descr, value):
        """
        """

    def create_record_layout(self):
        """
        """

#FNAME = "../ASAP2_Demo_V161.a2ldb"
#FNAME = "../XCPSim.a2ldb"
FNAME = "CDF20demo"

db = DB()
session = db.open_existing(FNAME)

#session = db.import_a2l("CDF20demo.a2l")


cr = Creator(session)

with open("ASAP2_Demo_V161.cdfx", "wb") as of:
    of.write(etree.tostring(cr.tree, encoding = "ISO-8859-1", pretty_print = True, xml_declaration = True, doctype = DOCTYPE))

#print(etree.tostring(cr.tree, pretty_print = True, xml_declaration = True, doctype = DOCTYPE))

dtd = DTD(CDF_DTD)

if not dtd.validate(cr.root):
    pprint(dtd.error_log)

def recursive_dict(element):
    return element.tag, dict(map(recursive_dict, element)) or element.text
