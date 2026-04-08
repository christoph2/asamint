#!/usr/bin/env python
""" """

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


from typing import Any

from lxml import etree  # nosec

from asamint import msrsw
from asamint.adapters.a2l import (
    Characteristic,
    CompuMethod,
    Measurement,
    ModCommon,
    model,
)
from asamint.asam import AsamMC
from asamint.utils import replace_non_c_char, sha1_digest
from asamint.utils.xml import create_elem


def matching_dcis(tree) -> None:
    dcis = create_elem(tree, "MATCHING-DCIS")
    dci = create_elem(dcis, "MATCHING-DCI")
    create_elem(dci, "LABEL", "Meta Data Exchange Format for Software Module Sharing")
    create_elem(dci, "SHORT-LABEL", "MDX")
    create_elem(dci, "URL", "http://www.mdx-dci-checkrules.com")


class MDXCreator(msrsw.MSRMixIn, AsamMC):
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

    DOCTYPE = (
        '<!DOCTYPE MSRSW PUBLIC "-//MSR//DTD MSR SOFTWARE DTD:V2.2.0:MSRSW.DTD//EN">'
    )
    # <!DOCTYPE MSRSW PUBLIC"-//ASAM//DTD MSR SOFTWARE DTD:V3.0.0:LAI:IAI:XML:MSRSW300.XSD//EN" "MSRSW_v3.0.0.DTD">
    DTD = "mdx_v1_0_0.sl.dtd"
    EXTENSION = "_mdx.xml"

    @staticmethod
    def _matrix_dimensions(matrix_dim) -> tuple[Any, ...] | None:
        if matrix_dim is None:
            return None
        dimensions = (matrix_dim.x, matrix_dim.y, matrix_dim.z)
        return dimensions if any(dim is not None for dim in dimensions) else None

    @staticmethod
    def _coeff_value(coeffs, name) -> Any:
        if coeffs is None:
            return None
        if hasattr(coeffs, name):
            return getattr(coeffs, name)
        return coeffs[name]

    @staticmethod
    def _table_value(table, name) -> Any:
        if table is None:
            return None
        if hasattr(table, name):
            return getattr(table, name)
        if hasattr(table, "__getitem__"):
            return table[name]
        return None

    def on_init(self, config, *args, **kws) -> None:
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

    def _toplevel_boilerplate(self) -> etree._Element:
        root = self.msrsw_header("MDX", "MDX")
        sw_system = self.sub_trees["SW-SYSTEM"]
        data_dict = create_elem(sw_system, "SW-DATA-DICTIONARY-SPEC")
        self.sub_trees["SW-DATA-DICTIONARY-SPEC"] = data_dict
        matching_dcis(root)
        return root

    def _units(self, tree) -> None:
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
        self.cm_units = {
            u[0]: format(f"{replace_non_c_char(u[0])}_{sha1_digest(u[0])}")
            for u in cm_units
            if u[0]
        }
        unit_spec = create_elem(tree, "UNIT-SPEC")
        units = create_elem(unit_spec, "UNITS")
        for k, v in self.cm_units.items():
            unit = create_elem(units, "UNIT", attrib={"ID": v})
            create_elem(unit, "SHORT-NAME", text=replace_non_c_char(k.strip()))
            create_elem(unit, "DISPLAY-NAME", text=k.strip())

    def _sw_variables(self, tree) -> None:
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
            matrixDim = self._matrix_dimensions(meas.matrixDim)
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

    def _sw_calparms(self, tree) -> None:
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
            matrixDim = self._matrix_dimensions(chx.matrixDim)
            datatype = chx.fnc_asam_dtype
            is_dependent = True if chx.dependent_characteristic else False
            is_ascii = chx.type == "ASCII"
            is_block = chx.type == "VAL_BLK"
            if is_block:
                if matrixDim:
                    dim = (m for m in matrixDim if m and m > 1)
            category = (
                "VALUE_ARRAY"
                if is_block
                else (
                    "DEPENDENT_VALUE"
                    if is_dependent
                    else "ASCII" if is_ascii else "VALUE"
                )
            )
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
                size = (
                    chx.number
                    if chx.number is not None
                    else matrixDim[0] if matrixDim else 0
                )
                create_elem(text_props, "SW-MAX-TEXT-SIZE", text=str(size))
            else:
                create_elem(data_def_props, "COMPU-METHOD-REF", text=compu_method.name)
            if is_dependent:
                data_dependency = create_elem(data_def_props, "SW-DATA-DEPENDENCY")
                dependency_formula = getattr(
                    chx.dependent_characteristic,
                    "formula",
                    chx.dependent_characteristic,
                )
                create_elem(
                    data_dependency,
                    "SW-DATA-DEPENDENCY-FORMULA",
                    text=dependency_formula,
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

    def _datatypes(self, tree) -> None:
        dtypes = (
            ("UBYTE", 1, False, True, "2C", "BYTE"),
            ("SBYTE", 1, True, True, "2C", "BYTE"),
            ("UWORD", 2, False, True, "2C", "WORD"),
            ("SWORD", 2, True, True, "2C", "WORD"),
            ("ULONG", 4, False, True, "2C", "DWORD"),
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
            align = alignments.get(dtype[0])
            self._datatype(base_types, dtype, byteOrder, align)

    def _data_constrs(self, tree) -> None:
        constrs = create_elem(tree, "DATA-CONSTRS")
        constrs.extend(self.data_constrs)

    def _datatype(self, tree, dtype, byteOrder, alignment) -> None:
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

    def _compu_methods(self, tree) -> None:
        cm_tree = create_elem(tree, "COMPU-METHODS")
        for conversion in [
            x[0] for x in self.session.query(model.CompuMethod.name).all()
        ]:
            cm = CompuMethod.get(self.session, conversion)
            self._compu_method(cm_tree, conversion, cm)

    def _compu_method(self, tree, name, compu_method) -> None:
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
        simple_handlers = {
            "IDENTICAL": lambda: self._append_rational_scale(
                scales, ("0", "1"), ("1", "0")
            ),
            "FORM": lambda: None,
            "LINEAR": lambda: self._append_rational_scale(
                scales,
                (
                    self._coeff_value(compu_method.coeffs_linear, "b"),
                    self._coeff_value(compu_method.coeffs_linear, "a"),
                ),
                ("1", "0"),
            ),
            "RAT_FUNC": lambda: self._append_rational_scale(
                scales,
                (
                    self._coeff_value(compu_method.coeffs, key)
                    for key in ("c", "b", "a")
                ),
                (
                    self._coeff_value(compu_method.coeffs, key)
                    for key in ("f", "e", "d")
                ),
            ),
            "TAB_INTP": lambda: self._append_numeric_table_conversion(
                cpti, scales, compu_method
            ),
            "TAB_NOINTP": lambda: self._append_numeric_table_conversion(
                cpti, scales, compu_method
            ),
            "TAB_VERB": lambda: self._append_text_table_conversion(
                cpti, scales, compu_method
            ),
        }
        handler = simple_handlers.get(cm_type)
        if handler:
            handler()

    def _append_rational_scale(
        self, scales, numerator_values, denominator_values
    ) -> None:
        scale = create_elem(scales, "COMPU-SCALE")
        coeffs = create_elem(scale, "COMPU-RATIONAL-COEFFS")
        numerator = create_elem(coeffs, "COMPU-NUMERATOR")
        denominator = create_elem(coeffs, "COMPU-DENOMINATOR")
        for value in numerator_values:
            create_elem(numerator, "V", str(value))
        for value in denominator_values:
            create_elem(denominator, "V", str(value))

    @staticmethod
    def _append_limits(scale, lower_value, upper_value) -> None:
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

    def _append_table_values(
        self, scales, lower_values, upper_values, out_values, value_tag: str
    ) -> None:
        for lower_value, upper_value, out_value in zip(
            lower_values, upper_values, out_values
        ):
            scale = create_elem(scales, "COMPU-SCALE")
            self._append_limits(scale, lower_value, upper_value)
            compu_const = create_elem(scale, "COMPU-CONST")
            create_elem(compu_const, value_tag, text=str(out_value))

    @staticmethod
    def _append_default_value(parent, tag: str, value) -> None:
        if value:
            default = create_elem(parent, "COMPU-DEFAULT-VALUE")
            create_elem(default, tag, text=str(value))

    def _append_numeric_table_conversion(self, cpti, scales, compu_method) -> None:
        table = compu_method.tab
        in_values = self._table_value(table, "in_values")
        out_values = self._table_value(table, "out_values")
        default_value = self._table_value(table, "default_value")
        self._append_table_values(scales, in_values, in_values, out_values, "V")
        self._append_default_value(cpti, "V", default_value)

    def _append_text_table_conversion(self, cpti, scales, compu_method) -> None:
        table = compu_method.tab_verb
        ranges = getattr(compu_method, "tab_verb_ranges", None)
        if ranges is not None:
            lower_values = self._table_value(ranges, "lower_values")
            upper_values = self._table_value(ranges, "upper_values")
            text_values = self._table_value(ranges, "text_values")
            default_value = self._table_value(ranges, "default_value")
        else:
            lower_values = self._table_value(table, "in_values")
            upper_values = self._table_value(table, "in_values")
            text_values = self._table_value(table, "text_values")
            default_value = self._table_value(table, "default_value")
        self._append_table_values(scales, lower_values, upper_values, text_values, "VT")
        self._append_default_value(cpti, "VT", default_value)
