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


from lxml.etree import (Comment, Element, tostring)
from sqlalchemy import func, or_

from asammdf import (MDF, Signal)
import pya2l.model as model
from pya2l.api.inspect import (Measurement, ModPar, CompuMethod)

from asamint.asam import AsamBaseType
from asamint.utils import (create_elem)


class MDFCreator(AsamBaseType):
    """
    Parameters
    ----------

    """

    PROJECT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "MDF_VERSION":              (str,    False,   "4.10"),
    }

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "TIME_SOURCE":              (str,    False,  "local PC reference timer"),
        "MEASUREMENTS":             (list,   False,  []),
        "FUNCTIONS":                (list,   False,  []),
        "GROUPS":                   (list,   False,  []),
    }

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self._mdf_obj = MDF(version = self.project_config.get("MDF_VERSION" ))
        self._mod_par = ModPar(self.session)
        hd_comment = self.hd_comment()
        print(dir(self._mdf_obj))


    @property
    def measurements(self):
        """
        """
        query = self.query(model.Measurement)
        query = query.filter(or_(func.regexp(model.Measurement.name, m) for m in self.experiment_config.get("MEASUREMENTS")))
        for meas in query.all():
            yield meas

    def hd_comment(self):
        """
        """
        mdf_ver_major = int(self._mdf_obj.version.split(".")[0])
        if mdf_ver_major < 4:
            pass
        else:
            elem_root = Element("HDcomment")
            create_elem(elem_root, "TX", self.experiment_config.get("DESCRIPTION"))
            time_source = self.experiment_config.get("TIME_SOURCE")
            if time_source:
                create_elem(elem_root, "time_source", time_source)
            sys_constants = self._mod_par.systemConstants
            if sys_constants:
                elem_constants = create_elem(elem_root, "constants")
                for name, value in sys_constants.items():
                    create_elem(elem_constants, "const", text = str(value), attrib = {"name": name})
            cps = create_elem(elem_root, "common_properties")
            create_elem(cps, "e", attrib = {"name": "author"}, text = self.project_config.get("AUTHOR"))
            create_elem(cps, "e", attrib = {"name": "department"}, text = self.project_config.get("DEPARTMENT"))
            create_elem(cps, "e", attrib = {"name": "project"}, text = self.project_config.get("PROJECT"))
            create_elem(cps, "e", attrib = {"name": "subject"}, text = self.experiment_config.get("SUBJECT"))
            return tostring(elem_root, encoding = "UTF-8", pretty_print = True)

    def save_measurements(self, mdf_filename: str = None, data: dict = None):
        """
        Parameters
        ----------


        """
        if not data:
            return
        timestamps = data.get("TIMESTAMPS")
        signals = []
        for measurement in self.measurements:
            if not measurement.name in data:
                continue    # Could be logged.
            print(measurement.name)
            cm_name = measurement.conversion
            comment = measurement.longIdentifier
            data_type = measurement.datatype
            conversion_map, cm = self.conversion(cm_name)
            unit = cm.unit if cm else None
            signal = Signal(
                samples = data.get(measurement.name), timestamps = timestamps, name = measurement.name,
                unit = unit, conversion = conversion_map, comment = comment
            )
            signals.append(signal)
        self._mdf_obj.append(signals)
        self._mdf_obj.save(dst = mdf_filename, overwrite = True)

    def conversion(self, cm_name: str) -> str:
        """
        Parameters
        ----------
        cm_name: str

        Returns
        -------
        dict: Suitable as MDF CCBLOCK.
        CompuMethod object or None:
        """
        conversion = None
        if cm_name == "NO_COMPU_METHOD":
            conversion = None
            cm = None
        else:
            cm =  CompuMethod(self.session, cm_name)
            cm_type = cm.conversionType
            if cm_type == "IDENTICAL":
                conversion = None
            elif cm_type == "FORM":
                formula_inv = cm.formula["formula_inv"]
                conversion = {
                    "formula": cm.formula["formula"]
                }
            elif cm_type == "LINEAR":
                conversion = {
                    "a": cm.coeffs_linear["a"],
                    "b": cm.coeffs_linear["b"],
                }
            elif cm_type == "RAT_FUNC":
                conversion = {
                    "P1": cm.coeffs["a"],
                    "P2": cm.coeffs["b"],
                    "P3": cm.coeffs["c"],
                    "P4": cm.coeffs["d"],
                    "P5": cm.coeffs["e"],
                    "P6": cm.coeffs["f"],
                }
            elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
                interpolation = cm.tab["interpolation"]
                default_value = cm.tab["default_value"]
                in_values = cm.tab["in_values"]
                out_values = cm.tab["out_values"]
                conversion = {"raw_{}".format(i): in_values[i] for i in range(len(in_values))}
                conversion.update({"phys_{}".format(i): out_values[i] for i in range(len(out_values))})
                conversion.update(default = default_value)
                conversion.update(interpolation = interpolation)
            elif cm_type == "TAB_VERB":
                default_value = cm.tab_verb["default_value"]
                text_values = cm.tab_verb["text_values"]
                if cm.tab_verb["ranges"]:
                    lower_values = cm.tab_verb["lower_values"]
                    upper_values = cm.tab_verb["upper_values"]
                    conversion = {"lower_{}".format(i): lower_values[i] for i in range(len(lower_values))}
                    conversion.update({"upper_{}".format(i): upper_values[i] for i in range(len(upper_values))})
                    conversion.update({"text_{}".format(i): text_values[i] for i in range(len(text_values))})
                    conversion.update(default = bytes(default_value, encoding = "utf-8") if default_value else b'')
                else:
                    in_values = cm.tab_verb["in_values"]
                    conversion = {"val_{}".format(i): in_values[i] for i in range(len(in_values))}
                    conversion.update({"text_{}".format(i): text_values[i] for i in range(len(text_values))})
                    conversion.update(default = default_value)
        return conversion, cm
