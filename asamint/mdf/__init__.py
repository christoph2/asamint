#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
__author__ = 'Christoph Schueler'

import logging

from asamint.utils import create_elem

import asammdf
from asammdf import MDF, Signal
from pya2l import DB
import pya2l.model as model
from pya2l.api.inspect import Measurement, ModPar

from lxml.etree import (Comment, Element, ElementTree, DTD, SubElement, XMLSchema, parse, tostring)

"""
Channel name (cn)           Acquisition name (gn)   Source name (cs,gs)

MCD-2 MC CHARACTERISTIC /   SOURCE / EVENT name     PROJECT name
MEASUREMENT /
AXIS_PTS name
"""

class MDFCreator:
    """
    """

    def __init__(self, session_obj, mdf_obj, mdf_filename = None, header_comment = "comment"):
        self._session_obj = session_obj
        self._mdf_obj = mdf_obj
        self._mdf_filename = mdf_filename

        self._mod_par = ModPar(self._session_obj)
        systemConstants = self._mod_par.systemConstants

        hd_comment = self.hd_comment(header_comment, "local PC reference timer", systemConstants)
        print(header_comment)

    def hd_comment(self, comment, time_source = "local PC reference timer", sys_constants = None, units = None):
        """
        Parameters
        ----------
        """
        elem_root = Element("HDcomment")
        elem_comment = create_elem(elem_text_root, "TX", comment)   # Required element.
        if time_source:
            elem_time_source = create_elem(elem_root, "time_source", time_source)
        if sys_constants:
            elem_constants = create_elem(elem_root, "constants")
            for name, value in sys_constants:
                print("{} ==> {}".format(name, value))
                create_elem(elem_root, "elem_constants", text = str(value), attrib = {"name": name})
        return tostring(elem_root, encoding = "UTF-8", pretty_print = True)

        """
        MDF4 by using the generic <e> tag on top level of
        <common_properties>
            with the following values for the name attribute: "author", "department", "project" and "subject".
        """
        #const
##
##        <constants>
##            <const name="PI">3.14159265</const>
##            <const name="DED2RAD">PI/180</const>
##            <const name="sin_45">sin(45*DEG2RAD)</const>
##        </constants>
##

        """
        <ho:UNIT-SPEC>
            <ho:PHYSICAL-DIMENSIONS>
                <ho:PHYSICAL-DIMENSION ID="siBase_m">
                    <ho:SHORT-NAME>length</ho:SHORT-NAME>
                    <ho:LONG-NAME xml:lang="de">Länge</ho:LONG-NAME>
                    <ho:LONG-NAME xml:lang="en">length</ho:LONG-NAME>
                    <ho:DESC xml:lang="en">base quantity: length</ho:DESC>
                    <ho:LENGTH-EXP>1</ho:LENGTH-EXP>
                </ho:PHYSICAL-DIMENSION>
            </ho:PHYSICAL-DIMENSIONS>
            <ho:UNITGROUPS>
                <ho:UNITGROUP>
                <ho:SHORT-NAME>Metric</ho:SHORT-NAME>
                <ho:CATEGORY>COUNTRY</ho:CATEGORY>
                <ho:UNIT-REFS>
                    <ho:UNIT-REF ID-REF="siBase_m"/>
                </ho:UNIT-REFS>
                </ho:UNITGROUP>
            </ho:UNITGROUPS>
            <ho:UNITS>
                <ho:UNIT ID="unitSiBase_meter">
                    <ho:SHORT-NAME>meter</ho:SHORT-NAME>
                    <ho:LONG-NAME xml:lang="de">Meter</ho:LONG-NAME>
                    <ho:LONG-NAME xml:lang="en">meter</ho:LONG-NAME>
                    <ho:DESC xml:lang="en">named SI unit for base quantity</ho:DESC>
                    <ho:DISPLAY-NAME>m</ho:DISPLAY-NAME>
                    <ho:PHYSICAL-DIMENSION-REF ID-REF="siBase_m"/>
                </ho:UNIT>
            </ho:UNITS>
        </ho:UNIT-SPEC>
        """


def create_mdf(session_obj, mdf_obj, mdf_filename = None):
    """
    Parameters
    ----------
    """

    signals = []
    measurements = session_obj.query(model.Measurement).order_by(model.Measurement.name).all()
    for measurement in measurements:
        #print("\tMEAS", measurement)
        cm_name = measurement.conversion
        comment = measurement.longIdentifier
        unit = None
        data_type = measurement.datatype # Don't know how to set data types on Signals...
        conversion = None
        if cm_name == "NO_COMPU_METHOD":
            conversion = None
        else:
            cm = session_obj.query(model.CompuMethod).filter(model.CompuMethod.name ==  cm_name).first()
            cm_type = cm.conversionType
            unit = cm.unit
            if cm_type == "IDENTICAL":
                conversion = None
            elif cm_type == "FORM":
                formula_inv = cm.formula.formula_inv.g_x if cm.formula.formula_inv else None
                conversion = {
                    "formula": cm.formula.f_x
                }
            elif cm_type == "LINEAR":
                conversion = {
                    "a": cm.coeffs_linear.a,
                    "b": cm.coeffs_linear.b,
                }
            elif cm_type == "RAT_FUNC":
                conversion = {
                    "P1": cm.coeffs.a,
                    "P2": cm.coeffs.b,
                    "P3": cm.coeffs.c,
                    "P4": cm.coeffs.d,
                    "P5": cm.coeffs.e,
                    "P6": cm.coeffs.f,
                }
            elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
                interpolation = True if cm_type == "TAB_INTP" else False
                cvt = session_obj.query(model.CompuTab).filter(model.CompuTab.name == cm.compu_tab_ref.conversionTable).first()
                pairs = cvt.pairs
                num_values = len(pairs)
                default_value = cvt.default_value_numeric.display_value if cvt.default_value_numeric else None
                print("\tTAB_INTP", measurement.name, cvt.pairs, default_value)
                in_values = [x.inVal for x in pairs]
                out_values = [x.outVal for x in pairs]
                conversion = {"raw_{}".format(i): in_values[i] for i in range(num_values)}
                conversion.update({"phys_{}".format(i): out_values[i] for i in range(num_values)})
                conversion.update(default = default_value)
                conversion.update(interpolation = interpolation)
            elif cm_type == "TAB_VERB":
                cvt = session_obj.query(model.CompuVtab).filter(model.CompuVtab.name == cm.compu_tab_ref.conversionTable).first()
                if cvt:
                    pairs = cvt.pairs
                    num_values = len(pairs)
                    in_values = [x.inVal for x in pairs]
                    out_values = [x.outVal for x in pairs]
                    conversion = {"val_{}".format(i): in_values[i] for i in range(num_values)}
                    conversion.update({"text_{}".format(i): out_values[i] for i in range(num_values)})
                    conversion.update(default = cvt.default_value.display_string if cvt.default_value else None)
                else:
                    cvt = session_obj.query(model.CompuVtabRange).filter(model.CompuVtabRange.name == \
                            cm.compu_tab_ref.conversionTable).first()
                    if cvt:
                        triples = cvt.triples
                        num_values = len(triples)
                        lower_values = [x.inValMin for x in triples]
                        upper_values = [x.inValMax for x in triples]
                        text_values = [x.outVal for x in triples]
                        conversion = {"lower_{}".format(i): lower_values[i] for i in range(num_values)}
                        conversion.update({"upper_{}".format(i): upper_values[i] for i in range(num_values)})
                        conversion.update({"text_{}".format(i): text_values[i] for i in range(num_values)})
                        conversion.update(default = bytes(cvt.default_value.display_string, encoding = "utf-8") \
                                if cvt.default_value else b'')
                    else:
                        conversion = None
        #print(measurement.name, conversion)
        signal = Signal(samples = [0, 0, 0, 0], timestamps = [0, 0, 0, 0], name = measurement.name, unit = unit, conversion = conversion, comment = comment)
        signals.append(signal)
    mdf_obj.append(signals)
    mdf_obj.save(dst = mdf_filename, overwrite = True)
