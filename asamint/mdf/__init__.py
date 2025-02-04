#!/usr/bin/env python

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2024 by Christoph Schueler <cpu12.gems.googlemail.com>

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
__author__ = "Christoph Schueler"


import numpy as np
from asammdf import MDF, Signal
from lxml.etree import Element, tostring  # nosec
from pya2l.api import inspect

from asamint.asam import AsamBaseType
from asamint.utils.xml import create_elem


class Datasource:
    """Measurement values could be located... well we don't know, so some
    sort of policy mechanism is required.
    """


class MDFCreator(AsamBaseType):
    """
    Parameters
    ----------

    """

    PROJECT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "MDF_VERSION": (str, False, "4.20"),
    }

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "TIME_SOURCE": (str, False, "local PC reference timer"),
        "MEASUREMENTS": (list, False, []),
        "FUNCTIONS": (list, False, []),
        "GROUPS": (list, False, []),
    }

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self._mdf_obj = MDF(version=self.project_config.get("MDF_VERSION"))
        hd_comment = self.hd_comment()
        self._mdf_obj.md_data = hd_comment
        self.mdf_version = self.config.general.mdf_version

    def hd_comment(self):
        """ """
        mdf_ver_major = int(self._mdf_obj.version.split(".")[0])
        if mdf_ver_major < 4:
            pass
        else:
            elem_root = Element("HDcomment")
            create_elem(elem_root, "TX", self.experiment_config.get("DESCRIPTION"))
            time_source = self.experiment_config.get("TIME_SOURCE")
            if time_source:
                create_elem(elem_root, "time_source", time_source)
            sys_constants = self.mod_par.systemConstants
            if sys_constants:
                elem_constants = create_elem(elem_root, "constants")
                for name, value in sys_constants.items():
                    create_elem(elem_constants, "const", text=str(value), attrib={"name": name})
            cps = create_elem(elem_root, "common_properties")
            create_elem(
                cps,
                "e",
                attrib={"name": "author"},
                text=self.project_config.get("AUTHOR"),
            )
            create_elem(
                cps,
                "e",
                attrib={"name": "department"},
                text=self.project_config.get("DEPARTMENT"),
            )
            create_elem(
                cps,
                "e",
                attrib={"name": "project"},
                text=self.project_config.get("PROJECT"),
            )
            create_elem(
                cps,
                "e",
                attrib={"name": "subject"},
                text=self.experiment_config.get("SUBJECT"),
            )
            return tostring(elem_root, encoding="UTF-8", pretty_print=True)

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
            # matrixDim = measurement.matrixDim  # TODO: Measurements are not necessarily scalars!
            if measurement.name not in data:
                self.logger.warn(f"NO data for measurement '{measurement.name}'.")
                continue
            self.logger.info(f"Adding SIGNAL: '{measurement.name}'.")

            comment = measurement.longIdentifier
            # data_type = measurement.datatype
            compuMethod = measurement.compuMethod
            conversion_map = self.ccblock(compuMethod)
            unit = compuMethod.unit if compuMethod != "NO_COMPU_METHOD" else None
            samples = data.get(measurement.name)
            samples = np.array(samples, copy=False)  # Make sure array-like data is of type `ndarray`.

            # Step #1: bit fiddling.
            bitMask = measurement.bitMask
            if bitMask is not None:
                samples &= bitMask
            bitOperation = measurement.bitOperation
            if bitOperation and bitOperation["amount"] != 0:
                amount = bitOperation["amount"]
                if bitOperation["direction"] == "L":
                    samples <<= amount
                else:
                    samples >>= amount
            # TODO: consider sign-extension!

            # Step #2: apply COMPU_METHODs.
            samples = self.calculate_physical_values(samples, compuMethod)

            signal = Signal(
                samples=samples,
                timestamps=timestamps,
                name=measurement.name,
                unit=unit,
                conversion=conversion_map,
                comment=comment,
            )
            signals.append(signal)
        self._mdf_obj.append(signals)
        self._mdf_obj.save(dst=mdf_filename, overwrite=True)

    def ccblock(self, compuMethod) -> str:
        """Construct CCBLOCK

        Parameters
        ----------
        compuMethod

        Returns
        -------
        dict: Suitable as MDF CCBLOCK or None (in case of `NO_COMPU_METHOD`).
        """
        conversion = None
        if compuMethod == "NO_COMPU_METHOD":
            conversion = None
        else:
            cm_type = compuMethod.conversionType
            if cm_type == "IDENTICAL":
                conversion = None
            elif cm_type == "FORM":
                # formula_inv = compuMethod.formula["formula_inv"]
                conversion = {"formula": compuMethod.formula["formula"]}
            elif cm_type == "LINEAR":
                conversion = {
                    "a": compuMethod.coeffs_linear["a"],
                    "b": compuMethod.coeffs_linear["b"],
                }
            elif cm_type == "RAT_FUNC":
                conversion = {
                    "P1": compuMethod.coeffs["a"],
                    "P2": compuMethod.coeffs["b"],
                    "P3": compuMethod.coeffs["c"],
                    "P4": compuMethod.coeffs["d"],
                    "P5": compuMethod.coeffs["e"],
                    "P6": compuMethod.coeffs["f"],
                }
            elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
                interpolation = compuMethod.tab["interpolation"]
                default_value = compuMethod.tab["default_value"]
                in_values = compuMethod.tab["in_values"]
                out_values = compuMethod.tab["out_values"]
                conversion = {f"raw_{i}": in_values[i] for i in range(len(in_values))}
                conversion.update({f"phys_{i}": out_values[i] for i in range(len(out_values))})
                conversion.update(default=default_value)
                conversion.update(interpolation=interpolation)
            elif cm_type == "TAB_VERB":
                default_value = compuMethod.tab_verb["default_value"]
                text_values = compuMethod.tab_verb["text_values"]
                if compuMethod.tab_verb["ranges"]:
                    lower_values = compuMethod.tab_verb["lower_values"]
                    upper_values = compuMethod.tab_verb["upper_values"]
                    conversion = {f"lower_{i}": lower_values[i] for i in range(len(lower_values))}
                    conversion.update({f"upper_{i}": upper_values[i] for i in range(len(upper_values))})
                    conversion.update({f"text_{i}": text_values[i] for i in range(len(text_values))})
                    conversion.update(default=(bytes(default_value, encoding="utf-8") if default_value else b""))
                else:
                    in_values = compuMethod.tab_verb["in_values"]
                    conversion = {f"val_{i}": in_values[i] for i in range(len(in_values))}
                    conversion.update({f"text_{i}": text_values[i] for i in range(len(text_values))})
                    conversion.update(default=default_value)
        return conversion

    def calculate_physical_values(self, internal_values, cm_object):
        """Calculate pyhsical value representation from raw, ECU-internal values.

        Parameters
        ----------
        internal_values: array-like

        cm_object: `CompuMethod` instance

        Returns
        -------
        array-like:
        """
        if cm_object is None:
            return internal_values
        else:
            if cm_object != "NO_COMPU_METHOD":
                name = cm_object.name
            else:
                name = "NO_COMPU_METHOD"
            calculator = inspect.CompuMethod(self.session, name)
            return calculator.int_to_physical(internal_values)
