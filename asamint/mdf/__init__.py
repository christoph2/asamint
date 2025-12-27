#!/usr/bin/env python

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import time
from collections.abc import Iterable
from typing import Any, Dict, List, Optional

import numpy as np
from asammdf import MDF, Signal
from lxml.etree import Element, tostring  # nosec
from pya2l.api import inspect
from pya2l.api.inspect import asam_type_size

from asamint.asam import AsamMC, get_data_type
from asamint.utils.xml import create_elem


class Datasource:
    """Measurement values could be located... well we don't know, so some
    sort of policy mechanism is required.
    """


class MDFCreator(AsamMC):
    """
    Create and save MDF (ASAM MDF 4.x) files from live ECU measurements or
    pre-collected arrays, integrating with pya2l (A2L meta) and pyxcp (XCP access).

    Typical usage with pyxcp and pya2l:
    - Provide measurement names via experiment_config["MEASUREMENTS"], or call
      add_measurements([...]).
    - Optionally acquire samples via a pyxcp.Master using acquire_via_pyxcp().
    - Finally, write an MDF file with save_measurements().
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
        self._mdf_obj = MDF(version=self.config.general.mdf_version)
        hd_comment = self.hd_comment()
        self._mdf_obj.md_data = hd_comment
        self.mdf_version = self.config.general.mdf_version
        # selected pya2l measurement objects
        self.measurement_variables: list[Any] = []
        # Try to auto-select measurements from config
        try:
            self._resolve_measurements_from_config()
        except Exception as e:
            # Non-fatal, user can add measurements later via add_measurements()
            self.logger.debug(
                f"MDFCreator: could not resolve measurements from config: {e}"
            )

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
                    create_elem(
                        elem_constants, "const", text=str(value), attrib={"name": name}
                    )
            cps = create_elem(elem_root, "common_properties")
            create_elem(
                cps,
                "e",
                attrib={"name": "author"},
                text=self.config.general.author,
            )
            create_elem(
                cps,
                "e",
                attrib={"name": "department"},
                text=self.config.general.department,
            )
            create_elem(
                cps,
                "e",
                attrib={"name": "project"},
                text=self.config.general.project,
            )
            create_elem(
                cps,
                "e",
                attrib={"name": "subject"},
                text=self.experiment_config.get("SUBJECT"),
            )
            return tostring(elem_root, encoding="UTF-8", pretty_print=True)

    def add_measurements(self, names: Iterable[str]) -> None:
        """Add measurement items by name using pya2l inspect.Measurement.

        Unknown names will be logged and ignored.
        """
        for name in names:
            try:
                meas = inspect.Measurement.get(self.session, name)
                if meas is not None:
                    self.measurement_variables.append(meas)
            except Exception as e:
                self.logger.warning(f"Unknown measurement '{name}': {e}")

    def _resolve_measurements_from_config(self) -> None:
        """Resolve measurements from experiment_config (MEASUREMENTS only for now)."""
        names = self.experiment_config.get("MEASUREMENTS") or []
        if names:
            self.add_measurements(names)

    def save_measurements(
        self, mdf_filename: str | None = None, data: dict[str, Any] | None = None
    ) -> None:
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
            samples = np.array(
                samples, copy=False
            )  # Make sure array-like data is of type `ndarray`.

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

    def ccblock(self, compuMethod) -> str | None:
        """Construct CCBLOCK

        Parameters
        ----------
        compuMethod

        Returns
        -------
        dict: Suitable as MDF CCBLOCK or None (in case of `NO_COMPU_METHOD`).
        """
        conversion: dict[str, object] | None = None
        try:
            # Handle missing/no conversion uniformly
            if compuMethod is None:
                return None

            cm_type = getattr(compuMethod, "conversionType", None)
            if not cm_type or cm_type in ("IDENTICAL", "NO_COMPU_METHOD"):
                return None

            if cm_type == "FORM":
                # Only forward formula to MDF. Inverse formula is not part of MDF CCBLOCK
                formula = None
                try:
                    formula = compuMethod.formula.get("formula")
                except Exception:
                    formula = None
                if formula is not None:
                    conversion = {"formula": formula}

            elif cm_type == "LINEAR":
                a = getattr(compuMethod, "coeffs_linear", {}).get("a", 0.0)
                b = getattr(compuMethod, "coeffs_linear", {}).get("b", 0.0)
                conversion = {"a": a, "b": b}

            elif cm_type == "RAT_FUNC":
                coeffs = getattr(compuMethod, "coeffs", {})
                conversion = {
                    "P1": coeffs.get("a", 0.0),
                    "P2": coeffs.get("b", 0.0),
                    "P3": coeffs.get("c", 0.0),
                    "P4": coeffs.get("d", 0.0),
                    "P5": coeffs.get("e", 0.0),
                    "P6": coeffs.get("f", 0.0),
                }

            elif cm_type in ("TAB_INTP", "TAB_NOINTP"):
                tab = getattr(compuMethod, "tab", {})
                in_values = list(tab.get("in_values", []))
                out_values = list(tab.get("out_values", []))
                default_value = tab.get("default_value")
                interpolation = tab.get("interpolation")
                conversion = {f"raw_{i}": v for i, v in enumerate(in_values)}
                conversion.update({f"phys_{i}": v for i, v in enumerate(out_values)})
                if default_value is not None:
                    conversion.update(default=default_value)
                if interpolation is not None:
                    conversion.update(interpolation=interpolation)

            elif cm_type == "TAB_VERB":
                tv = getattr(compuMethod, "tab_verb", {})
                text_values = tv.text_values
                default_value = tv.default_value

                if isinstance(tv, inspect.CompuTabVerbRanges):
                    lower_values = tv.lower_values
                    upper_values = tv.upper_values
                    conversion = {f"lower_{i}": v for i, v in enumerate(lower_values)}
                    conversion.update(
                        {f"upper_{i}": v for i, v in enumerate(upper_values)}
                    )
                    conversion.update(
                        {f"text_{i}": v for i, v in enumerate(text_values)}
                    )
                    # MDF requires bytes for default text value
                    if default_value:
                        try:
                            conversion.update(
                                default=bytes(default_value, encoding="utf-8")
                            )
                        except Exception:
                            conversion.update(default=b"")
                else:  # must be CompuTabVerb instance.
                    in_values = tv.in_values
                    conversion = {f"val_{i}": v for i, v in enumerate(in_values)}
                    conversion.update(
                        {f"text_{i}": v for i, v in enumerate(text_values)}
                    )
                    if default_value is not None:
                        conversion.update(default=default_value)

            else:
                # Unknown/rare conversion type — log once and proceed without conversion
                try:
                    self.logger.warning(
                        f"Unsupported COMPU_METHOD type '{cm_type}' for MDF CCBLOCK; writing raw values."
                    )
                except Exception:
                    pass
                conversion = None
        except (
            Exception
        ) as e:  # defensive: never fail MDF writing due to conversion map
            try:
                self.logger.warning(
                    f"Failed to construct CCBLOCK for {getattr(compuMethod, 'name', compuMethod)}: {e}"
                )
            except Exception:
                pass
            conversion = None
        return conversion
