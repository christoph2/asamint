#!/usr/bin/env python
# -*- coding: utf-8 -*-


from pprint import pprint

import lxml
from lxml.etree import (Element, ElementTree, DTD, SubElement, XMLSchema, parse, tounicode)
from lxml import etree
from pya2l import DB
import pya2l.model as model
from pya2l.api.inspect import ModCommon, _dissect_conversion

from asamint.utils import create_elem

DOCTYPE = 'DOCTYPE MSRSW PUBLIC "-//ASAM//DTD MSR SOFTWARE DTD:V3.0.0:LAI:IAI:XML:MSRSW.DTD//EN"'

"""
The parsers accept a number of setup options as keyword arguments. The above example is easily extended to
clean up namespaces during parsing:
>>> parser = etree.XMLParser(ns_clean=True)
>>> tree = etree.parse(StringIO(xml), parser)
>>> etree.tostring(tree.getroot())
"""

MDX_DTD = "mdx_v1_0_0.sl.dtd"

MDX_EXTENSION = "_mdx.xml"


def standard_dekoration(tree, short_name, long_name = None, category = None):
    create_elem(tree, "SHORT-NAME", short_name)
    if long_name:
        create_elem(tree, "LONG-NAME", long_name)
    if category:
        create_elem(tree, "CATEGORY", category)

def matching_dcis(tree):
    dcis = create_elem(tree, "MATCHING-DCIS")
    dci = create_elem(dcis, "MATCHING-DCI")
    create_elem(dci, "LABEL", "Meta Data Exchange Format for Software Module Sharing")
    create_elem(dci, "SHORT-LABEL", "MDX")
    create_elem(dci, "URL", "http://www.mdx-dci-checkrules.com")

class Creator:

    def __init__(self, session_obj):
        self.session_obj = session_obj
        self.sub_trees = {}
        self.root = self._toplevel_boilerplate()
        self.tree = ElementTree(self.root)
        """
        <!ELEMENT SW-DATA-DICTIONARY-SPEC
        (
              UNIT-SPEC? ,
              SW-VARIABLES? ,
              SW-CALPRMS? ,
              SW-SYSTEMCONSTS? ,
              SW-CLASS-INSTANCES? ,
              COMPU-METHODS? ,
              SW-ADDR-METHODS? ,
              SW-RECORD-LAYOUTS? ,
              SW-CODE-SYNTAXES? ,
              BASE-TYPES? ,
              DATA-CONSTRS? ,
              SW-AXIS-TYPES? ,
              SW-SERVICES? ,
              SW-CLASSES?
        )
        """
        self._sw_variables(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._compu_methods(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._datatypes(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])


    @property
    def query(self):
        return self.session_obj.query

    def _toplevel_boilerplate(self):
        root = Element("MSRSW")
        create_elem(root, "CATEGORY", "MDX")
        sw_systems = create_elem(root, "SW-SYSTEMS")
        sw_system = create_elem(sw_systems, "SW-SYSTEM")
        standard_dekoration(sw_system, "FOO", "FOO do_er")
        self.sub_trees["SW-SYSTEM"] = sw_system
        data_dict = create_elem(sw_system, "SW-DATA-DICTIONARY-SPEC")
        self.sub_trees["SW-DATA-DICTIONARY-SPEC"] = data_dict
        matching_dcis(root)
        return root

    def _sw_variables(self, tree):
        variables = create_elem(tree, "SW-VARIABLES")
        measurements = self.query(model.Measurement).all()
        for meas in measurements:
            variable = create_elem(variables, "SW-VARIABLE", attrib = {"ID": meas.name})
            create_elem(variable, "SHORT-NAME", meas.name)
            create_elem(variable, "LONG-NAME", meas.longIdentifier)

            print(meas)

    def _datatypes(self, tree):
        dtypes = (
            ('UBYTE', 1, False, True, "2C", "BYTE"),
            ('SBYTE', 1, True, True, "2C", "BYTE"),
            ('UWORD', 2, False, True, "2C", "WORD"),
            ('SWORD', 2, True, True, "2C", "WORD"),
            ('ULONG', 4, False, True, "2C", "DORD"),
            ('SLONG', 4, True, True, "2C", "DWORD"),
            ('A_UINT64', 8, False, True, "2C", "QWORD"),
            ('A_INT64', 8, True, True, "2C", "QWORD"),
            ('FLOAT32_IEEE', 4, True, True, "IEEE754", "FLOAT32"),
            ('FLOAT64_IEEE', 8, True, True, "IEEE754", "FLOAT64"),
        )
        mc = ModCommon(self.session_obj)
        byteOrder = mc.byteOrder
        alignments = mc.alignment
        if byteOrder in ("MSB_FIRST", "LITTLE_ENDIAN"):
            byteOrder = "MOST-SIGNIFICANT-BYTE-FIRST"
        else:
            byteOrder = "MOST-SIGNIFICANT-BYTE-LAST"
        base_types = create_elem(tree, "BASE-TYPES")
        for dtype in dtypes:
            align = alignments.get(dtype[5])
            self._datatype(base_types, dtype, byteOrder, align)

    def _datatype(self, tree, dtype, byteOrder, alignment):
        name, length, signed, fixed, enc, _ = dtype
        base_type = create_elem(tree, "BASE-TYPE", attrib = {"ID": name})
        create_elem(base_type, "SHORT-NAME", name)
        create_elem(base_type, "CATEGORY", "FIXED_LENGTH" if fixed else "VARIABLE_LENGTH")
        create_elem(base_type, "BASE-TYPE-SIZE", str(length))
        if enc:
            create_elem(base_type, "BASE-TYPE-ENCODING", enc)
        if alignment:
            create_elem(base_type, "MEM-ALIGNMENT", str(alignment))
        create_elem(base_type, "BYTE-ORDER", attrib = {"TYPE": byteOrder})

    def _compu_methods(self, tree):
        cm_tree = create_elem(tree, "COMPU-METHODS")
        for conversion in [x[0] for x in self.session_obj.query(model.CompuMethod.name).all()]:
            cm = _dissect_conversion(self.session_obj, conversion)
            self._compu_method(cm_tree, conversion, cm)

    def _compu_method(self, tree, name, compu_method):
        cm_type = compu_method["type"]
        cm_longIdentifier = compu_method["longIdentifier"]
        cm_unit = compu_method["unit"]
        cm = create_elem(tree, "COMPU-METHOD", attrib = {"ID": name})
        create_elem(cm, "SHORT-NAME", name)
        if cm_longIdentifier:
            create_elem(cm, "LONG-NAME", cm_longIdentifier)
        create_elem(cm, "CATEGORY", cm_type.replace("_", "-"))
        if cm_unit:
            create_elem(cm, "UNIT-REF", cm_unit)
        cpti = create_elem(cm, "COMPU-PHYS-TO-INTERNAL")
        scales = create_elem(cpti, "COMPU-SCALES")
        if cm_type == "IDENTICAL":
            scale = create_elem(scales, "COMPU-SCALE")
            crc = create_elem(scale, "COMPU-RATIONAL-COEFFS")
            cnum = create_elem(crc, "COMPU-NUMERATOR")
            create_elem(cnum, "V", "0")
            create_elem(cnum, "V", "1")
            cden = create_elem(crc, "COMPU-DENOMINATOR")
            create_elem(cden, "V", "1")
            create_elem(cden, "V", "0")
        elif cm_type == "FORM":
            pass
        elif cm_type == "LINEAR":
            scale = create_elem(scales, "COMPU-SCALE")
            crc = create_elem(scale, "COMPU-RATIONAL-COEFFS")
            cnum = create_elem(crc, "COMPU-NUMERATOR")
            create_elem(cnum, "V", str(compu_method['b']))
            create_elem(cnum, "V", str(compu_method['a']))
            cden = create_elem(crc, "COMPU-DENOMINATOR")
            create_elem(cden, "V", "1")
            create_elem(cden, "V", "0")
        elif cm_type == "RAT_FUNC":
            scale = create_elem(scales, "COMPU-SCALE")
            crc = create_elem(scale, "COMPU-RATIONAL-COEFFS")
            cnum = create_elem(crc, "COMPU-NUMERATOR")
            for key in ['c', 'b', 'a']:
                val = str(compu_method[key])
                create_elem(cnum, "V", val)
            cden = create_elem(crc, "COMPU-DENOMINATOR")
            for key in ['f', 'e', 'd']:
                val = str(compu_method[key])
                create_elem(cden, "V", val)
        elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
            in_values = compu_method["in_values"]
            out_values = compu_method["out_values"]
            for in_value, out_value in zip(in_values, out_values):
                scale = create_elem(scales, "COMPU-SCALE")
                create_elem(scale, "LOWER-LIMIT", text = str(in_value), attrib = {"INTERVAL-TYPE": "CLOSED"})
                create_elem(scale, "UPPER-LIMIT", text = str(in_value), attrib = {"INTERVAL-TYPE": "CLOSED"})
                compu_const = create_elem(scale, "COMPU-CONST")
                create_elem(compu_const, "V", text = str(out_value))
            if compu_method["default_value"]:
                default = create_elem(cpti, "COMPU-DEFAULT-VALUE")
                create_elem(default , "V", text = str(compu_method["default_value"]))
        elif cm_type == "TAB_VERB":
            if compu_method["ranges"]:
                lower_values = compu_method["lower_values"]
                upper_values = compu_method["upper_values"]
                text_values = compu_method["text_values"]
                for lower_value, upper_value, text_value in zip(lower_values, upper_values, text_values):
                    scale = create_elem(scales, "COMPU-SCALE")
                    create_elem(scale, "LOWER-LIMIT", text = str(lower_value), attrib = {"INTERVAL-TYPE": "CLOSED"})
                    create_elem(scale, "UPPER-LIMIT", text = str(upper_value), attrib = {"INTERVAL-TYPE": "CLOSED"})
                    compu_const = create_elem(scale, "COMPU-CONST")
                    create_elem(compu_const, "VT", text = text_value)
            else:
                in_values = compu_method["in_values"]
                text_values = compu_method["text_values"]
                for in_value, text_value in zip(in_values, text_values):
                    scale = create_elem(scales, "COMPU-SCALE")
                    create_elem(scale, "LOWER-LIMIT", text = str(in_value), attrib = {"INTERVAL-TYPE": "CLOSED"})
                    create_elem(scale, "UPPER-LIMIT", text = str(in_value), attrib = {"INTERVAL-TYPE": "CLOSED"})
                    compu_const = create_elem(scale, "COMPU-CONST")
                    create_elem(compu_const, "VT", text = text_value)
            if compu_method["default_value"]:
                default = create_elem(cpti, "COMPU-DEFAULT-VALUE")
                create_elem(default , "VT", text = compu_method["default_value"])

FNAME = "../ASAP2_Demo_V161.a2ldb"
#FNAME = "../XCPSim.a2ldb"

db = DB()
session = db.open_existing(FNAME)

cr = Creator(session)

units = cr.query(model.CompuMethod.unit.distinct()).all()
# Module.Unit?
# REF_UNIT.unit
# PHYS_UNIT

print("*** UNITS", units)

with open("ASAP2_Demo_V161_mdx.xml", "wb") as of:
    of.write(etree.tostring(cr.tree, pretty_print = True, xml_declaration = True, doctype = DOCTYPE))

##print(etree.tostring(cr.tree, pretty_print = True, xml_declaration = True, doctype = DOCTYPE))

dtd = DTD(MDX_DTD)

if not dtd.validate(cr.root):
    pprint(dtd.error_log)

def recursive_dict(element):
    return element.tag, dict(map(recursive_dict, element)) or element.text
