#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2024 by Christoph Schueler <cpu12.gems.googlemail.com>

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


import pya2l.model as model
from lxml import etree  # nosec
from pya2l.api.inspect import Characteristic, CompuMethod, Measurement, ModCommon

import asamint.msrsw as msrsw
from asamint.asam import AsamBaseType
from asamint.utils import replace_non_c_char, sha1_digest
from asamint.utils.xml import create_elem


def matching_dcis(tree):
    dcis = create_elem(tree, "MATCHING-DCIS")
    dci = create_elem(dcis, "MATCHING-DCI")
    create_elem(dci, "LABEL", "Meta Data Exchange Format for Software Module Sharing")
    create_elem(dci, "SHORT-LABEL", "MDX")
    create_elem(dci, "URL", "http://www.mdx-dci-checkrules.com")


class MDXCreator(msrsw.MSRMixIn, AsamBaseType):
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

    DOCTYPE = '<!DOCTYPE MSRSW PUBLIC "-//MSR//DTD MSR SOFTWARE DTD:V2.2.0:MSRSW.DTD//EN">'
    # <!DOCTYPE MSRSW PUBLIC"-//ASAM//DTD MSR SOFTWARE DTD:V3.0.0:LAI:IAI:XML:MSRSW300.XSD//EN" "MSRSW_v3.0.0.DTD">
    DTD = "mdx_v1_0_0.sl.dtd"
    EXTENSION = "_mdx.xml"

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self.root = self._toplevel_boilerplate()
        self.tree = etree.ElementTree(self.root)
        self._units(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._sw_variables(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._sw_calparms(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._compu_methods(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._datatypes(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])
        self._data_constrs(self.sub_trees["SW-DATA-DICTIONARY-SPEC"])

        with open(f"CDF20demo{self.EXTENSION}", "wb") as of:
            of.write(
                etree.tostring(
                    self.root,
                    encoding="UTF-8",
                    pretty_print=True,
                    xml_declaration=True,
                    doctype=self.DOCTYPE,
                )
            )

    def _toplevel_boilerplate(self):
        root = self.msrsw_header("MDX", "MDX")
        sw_system = self.sub_trees["SW-SYSTEM"]
        data_dict = create_elem(sw_system, "SW-DATA-DICTIONARY-SPEC")
        self.sub_trees["SW-DATA-DICTIONARY-SPEC"] = data_dict
        matching_dcis(root)
        return root

    def _units(self, tree):
        """
        SHORT-NAME ,
        LONG-NAME? ,
        CATEGORY? ,
        DISPLAY-NAME? ,
        FACTOR-SI-TO-UNIT? ,
        OFFSET-SI-TO-UNIT? ,
        PHYSICAL-DIMENSION-REF?
        """
        cm_units = self.query(model.CompuMethod.unit.distinct()).all()
        self.cm_units = {u[0]: format(f"{replace_non_c_char(u[0])}_{sha1_digest(u[0])}") for u in cm_units if u[0]}
        unit_spec = create_elem(tree, "UNIT-SPEC")
        units = create_elem(unit_spec, "UNITS")
        for k, v in self.cm_units.items():
            unit = create_elem(units, "UNIT", attrib={"ID": v})
            create_elem(unit, "SHORT-NAME", text=replace_non_c_char(k.strip()))
            create_elem(unit, "DISPLAY-NAME", text=k.strip())

    def _sw_variables(self, tree):
        self.data_constrs = []
        variables = create_elem(tree, "SW-VARIABLES")
        # data_constrs = []
        measurements = self.query(model.Measurement.name).all()
        for meas_name in measurements:
            meas_name = meas_name[0]
            meas = Measurement.get(self.session, meas_name)
            # print(meas)
            compu_method = meas.compuMethod
            constr_name = f"CONSTR_{meas.name}"
            arraySize = (meas.arraySize,) if meas.arraySize else None
            matrixDim = (meas.matrixDim["x"], meas.matrixDim["y"], meas.matrixDim["z"]) if meas.matrixDim else None
            is_array = arraySize or matrixDim
            datatype = meas.datatype
            is_ascii = datatype == "ASCII"
            category = "VALUE_ARRAY" if is_array else "ASCII" if is_ascii else "VALUE"
            variable = create_elem(variables, "SW-VARIABLE", attrib={"ID": meas_name})
            self.common_elements(
                variable,
                short_name=meas_name,
                long_name=meas.longIdentifier,
                category=category,
            )
            if is_array:
                if matrixDim:
                    dim = (m for m in matrixDim if m > 1)
                    # dim = matrixDim
                elif arraySize:
                    dim = arraySize
                self.output_1darray(variable, "SW-ARRAYSIZE", dim)

            data_def_props = create_elem(variable, "SW-DATA-DEF-PROPS")
            # <SW-ADDR-METHOD-REF>externalRam</SW-ADDR-METHOD-REF>
            create_elem(data_def_props, "BASE-TYPE-REF", text=datatype)
            create_elem(
                data_def_props,
                "SW-CALIBRATION-ACCESS",
                text="READ-ONLY" if not meas.readWrite else "READ-WRITE",
            )
            if is_ascii:
                text_props = create_elem(data_def_props, "SW-TEXT-PROPS")
                size = arraySize[0] if arraySize else matrixDim[0] if matrixDim else 0
                create_elem(text_props, "SW-MAX-TEXT-SIZE", text=str(size))
            else:
                create_elem(data_def_props, "COMPU-METHOD-REF", text=compu_method.name)
            # <SW-CODE-SYNTAX-REF>Var</SW-CODE-SYNTAX-REF>
            create_elem(data_def_props, "DATA-CONSTR-REF", text=constr_name)
            create_elem(data_def_props, "SW-IMPL-POLICY", text="MEASUREMENT-POINT")
            # <UNIT-REF>rotates_per_minute</UNIT-REF>
            if compu_method.conversionType != "NO_COMPU_METHOD":
                internal_values = compu_method.conversionType in (
                    "COMPU_VTAB",
                    "COMPU_VTAB_RANGE",
                )
            else:
                internal_values = False
            data_constr = etree.Element("DATA-CONSTR")
            self.common_elements(data_constr, short_name=constr_name, category="RANGE")
            rules = create_elem(data_constr, "DATA-CONSTR-RULES")
            rule = create_elem(rules, "DATA-CONSTR-RULE")
            if internal_values:
                node = create_elem(rule, "INTERNAL-CONSTRS")
            else:
                node = create_elem(rule, "PHYS-CONSTRS")
            create_elem(
                node,
                "LOWER-LIMIT",
                attrib={"INTERVAL-TYPE": "CLOSED"},
                text=str(meas.lowerLimit),
            )
            create_elem(
                node,
                "UPPER-LIMIT",
                attrib={"INTERVAL-TYPE": "CLOSED"},
                text=str(meas.upperLimit),
            )
            self.data_constrs.append(data_constr)

    def _sw_calparms(self, tree):
        self.data_constrs = []
        cal_parms = create_elem(tree, "SW-CALPRMS")
        # data_constrs = []
        characteristics = self.query(model.Characteristic.name).all()
        for ch_name in characteristics:
            ch_name = ch_name[0]
            chx = Characteristic.get(self.session, ch_name)
            # print(chx)
            compu_method = chx.compuMethod
            # constr_name = "CONSTR_{}".format(chx.name)
            matrixDim = (chx.matrixDim["x"], chx.matrixDim["y"], chx.matrixDim["z"]) if chx.matrixDim else None
            datatype = chx.fnc_asam_dtype
            is_dependent = True if chx.dependentCharacteristic else False
            is_ascii = chx.type == "ASCII"
            is_block = chx.type == "VAL_BLK"
            if is_block:
                if matrixDim:
                    dim = (m for m in matrixDim if m and m > 1)
            category = "VALUE_ARRAY" if is_block else ("DEPENDENT_VALUE" if is_dependent else "ASCII" if is_ascii else "VALUE")
            cal_parm = create_elem(cal_parms, "SW-CALPRM", attrib={"ID": ch_name})
            self.common_elements(
                cal_parm,
                short_name=ch_name,
                long_name=chx.longIdentifier,
                category=category,
            )
            if is_block:
                self.output_1darray(cal_parm, "SW-ARRAYSIZE", dim)
            data_def_props = create_elem(cal_parm, "SW-DATA-DEF-PROPS")
            # <SW-ADDR-METHOD-REF>Rom</SW-ADDR-METHOD-REF>
            create_elem(data_def_props, "BASE-TYPE-REF", text=datatype)
            create_elem(
                data_def_props,
                "SW-CALIBRATION-ACCESS",
                text="READ-ONLY" if chx.readOnly else "READ-WRITE",
            )
            if is_ascii:
                text_props = create_elem(data_def_props, "SW-TEXT-PROPS")
                size = chx.number if chx.number is not None else matrixDim[0] if matrixDim else 0
                create_elem(text_props, "SW-MAX-TEXT-SIZE", text=str(size))
            else:
                create_elem(data_def_props, "COMPU-METHOD-REF", text=compu_method.name)
            if is_dependent:
                data_dependency = create_elem(data_def_props, "SW-DATA-DEPENDENCY")
                create_elem(
                    data_dependency,
                    "SW-DATA-DEPENDENCY-FORMULA",
                    text=chx.dependentCharacteristic,
                )

            """
            <SW-CALPRM>
                <SHORT-NAME>MyCalprmVALUE</SHORT-NAME>
                <CATEGORY>VALUE</CATEGORY>
                <SW-DATA-DEF-PROPS>
                    <SW-ADDR-METHOD-REF>Rom</SW-ADDR-METHOD-REF>
                    <BASE-TYPE-REF>A_INT8</BASE-TYPE-REF>
                    <SW-CALIBRATION-ACCESS>READ-WRITE</SW-CALIBRATION-ACCESS>
                    <SW-CODE-SYNTAX-REF>Cal</SW-CODE-SYNTAX-REF>
                    <COMPU-METHOD-REF>MyCompuRatFunc</COMPU-METHOD-REF>

                    <DATA-CONSTR-REF>MyConstraintPhysical</DATA-CONSTR-REF>
                    <SW-RECORD-LAYOUT-REF>Cal</SW-RECORD-LAYOUT-REF>
                    <UNIT-REF>rotates_per_minute</UNIT-REF>
                </SW-DATA-DEF-PROPS>
            </SW-CALPRM>
            """

    def _datatypes(self, tree):
        dtypes = (
            ("UBYTE", 1, False, True, "2C", "BYTE"),
            ("SBYTE", 1, True, True, "2C", "BYTE"),
            ("UWORD", 2, False, True, "2C", "WORD"),
            ("SWORD", 2, True, True, "2C", "WORD"),
            ("ULONG", 4, False, True, "2C", "DORD"),
            ("SLONG", 4, True, True, "2C", "DWORD"),
            ("A_UINT64", 8, False, True, "2C", "QWORD"),
            ("A_INT64", 8, True, True, "2C", "QWORD"),
            ("FLOAT32_IEEE", 4, True, True, "IEEE754", "FLOAT32"),
            ("FLOAT64_IEEE", 8, True, True, "IEEE754", "FLOAT64"),
        )
        mc = ModCommon.get(self.session)
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

    def _data_constrs(self, tree):
        constrs = create_elem(tree, "DATA-CONSTRS")
        constrs.extend(self.data_constrs)

    def _datatype(self, tree, dtype, byteOrder, alignment):
        name, length, signed, fixed, enc, _ = dtype
        base_type = create_elem(tree, "BASE-TYPE", attrib={"ID": name})
        self.common_elements(
            base_type,
            short_name=name,
            category="FIXED_LENGTH" if fixed else "VARIABLE_LENGTH",
        )
        create_elem(base_type, "BASE-TYPE-SIZE", str(length))
        if enc:
            create_elem(base_type, "BASE-TYPE-ENCODING", enc)
        if alignment:
            create_elem(base_type, "MEM-ALIGNMENT", str(alignment))
        create_elem(base_type, "BYTE-ORDER", attrib={"TYPE": byteOrder})

    def _compu_methods(self, tree):
        cm_tree = create_elem(tree, "COMPU-METHODS")
        for conversion in [x[0] for x in self.session.query(model.CompuMethod.name).all()]:
            cm = CompuMethod.get(self.session, conversion)
            self._compu_method(cm_tree, conversion, cm)

    def _compu_method(self, tree, name, compu_method):
        cm_type = compu_method.conversionType
        cm_longIdentifier = compu_method.longIdentifier
        cm_unit = compu_method.unit
        cm = create_elem(tree, "COMPU-METHOD", attrib={"ID": name})
        self.common_elements(
            cm,
            short_name=name,
            long_name=cm_longIdentifier,
            category=cm_type.replace("_", "-"),
        )
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
            create_elem(cnum, "V", str(compu_method.coeffs_linear["b"]))
            create_elem(cnum, "V", str(compu_method.coeffs_linear["a"]))
            cden = create_elem(crc, "COMPU-DENOMINATOR")
            create_elem(cden, "V", "1")
            create_elem(cden, "V", "0")
        elif cm_type == "RAT_FUNC":
            scale = create_elem(scales, "COMPU-SCALE")
            crc = create_elem(scale, "COMPU-RATIONAL-COEFFS")
            cnum = create_elem(crc, "COMPU-NUMERATOR")
            for key in ["c", "b", "a"]:
                val = str(compu_method.coeffs[key])
                create_elem(cnum, "V", val)
            cden = create_elem(crc, "COMPU-DENOMINATOR")
            for key in ["f", "e", "d"]:
                val = str(compu_method.coeffs[key])
                create_elem(cden, "V", val)
        elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
            in_values = compu_method.tab["in_values"]
            out_values = compu_method.tab["out_values"]
            for in_value, out_value in zip(in_values, out_values):
                scale = create_elem(scales, "COMPU-SCALE")
                create_elem(
                    scale,
                    "LOWER-LIMIT",
                    text=str(in_value),
                    attrib={"INTERVAL-TYPE": "CLOSED"},
                )
                create_elem(
                    scale,
                    "UPPER-LIMIT",
                    text=str(in_value),
                    attrib={"INTERVAL-TYPE": "CLOSED"},
                )
                compu_const = create_elem(scale, "COMPU-CONST")
                create_elem(compu_const, "V", text=str(out_value))
            if compu_method.tab["default_value"]:
                default = create_elem(cpti, "COMPU-DEFAULT-VALUE")
                create_elem(default, "V", text=str(compu_method.tab["default_value"]))
        elif cm_type == "TAB_VERB":
            if compu_method.tab_verb["ranges"]:
                lower_values = compu_method.tab_verb["lower_values"]
                upper_values = compu_method.tab_verb["upper_values"]
                text_values = compu_method.tab_verb["text_values"]
                for lower_value, upper_value, text_value in zip(lower_values, upper_values, text_values):
                    scale = create_elem(scales, "COMPU-SCALE")
                    create_elem(
                        scale,
                        "LOWER-LIMIT",
                        text=str(lower_value),
                        attrib={"INTERVAL-TYPE": "CLOSED"},
                    )
                    create_elem(
                        scale,
                        "UPPER-LIMIT",
                        text=str(upper_value),
                        attrib={"INTERVAL-TYPE": "CLOSED"},
                    )
                    compu_const = create_elem(scale, "COMPU-CONST")
                    create_elem(compu_const, "VT", text=text_value)
            else:
                in_values = compu_method.tab_verb["in_values"]
                text_values = compu_method.tab_verb["text_values"]
                for in_value, text_value in zip(in_values, text_values):
                    scale = create_elem(scales, "COMPU-SCALE")
                    create_elem(
                        scale,
                        "LOWER-LIMIT",
                        text=str(in_value),
                        attrib={"INTERVAL-TYPE": "CLOSED"},
                    )
                    create_elem(
                        scale,
                        "UPPER-LIMIT",
                        text=str(in_value),
                        attrib={"INTERVAL-TYPE": "CLOSED"},
                    )
                    compu_const = create_elem(scale, "COMPU-CONST")
                    create_elem(compu_const, "VT", text=text_value)
            if compu_method.tab_verb["default_value"]:
                default = create_elem(cpti, "COMPU-DEFAULT-VALUE")
                create_elem(default, "VT", text=compu_method.tab_verb["default_value"])
