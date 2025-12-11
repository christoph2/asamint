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


from __future__ import annotations

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
        self.measurements: list[Any] = []
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
                self.measurements.append(meas)
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

    def _numpy_dtype_for_asam(self, datatype: str, bo: Any) -> np.dtype:
        endian = "<" if bo == 0 else ">"
        # Map to numpy dtype codes
        match datatype:
            case "UBYTE":
                return np.dtype("u1")
            case "SBYTE":
                return np.dtype("i1")
            case "UWORD":
                return np.dtype(endian + "u2")
            case "SWORD":
                return np.dtype(endian + "i2")
            case "ULONG":
                return np.dtype(endian + "u4")
            case "SLONG":
                return np.dtype(endian + "i4")
            case "A_UINT64":
                return np.dtype(endian + "u8")
            case "A_INT64":
                return np.dtype(endian + "i8")
            case "FLOAT32_IEEE":
                return np.dtype(endian + "f4")
            case "FLOAT64_IEEE":
                return np.dtype(endian + "f8")
            case _:
                # Fallback: treat as 32-bit unsigned
                return np.dtype(endian + "u4")

    def acquire_via_pyxcp(
        self,
        master: Any,
        duration_s: float | None = None,
        samples: int | None = None,
        period_s: float = 0.01,
    ) -> dict[str, Any]:
        """Acquire measurement samples via a pyxcp Master by periodic polling.

        This is a simple polling-based acquisition for compatibility. For
        higher performance consider using DAQ/ODT configuration in pyxcp.

        Returns a dict compatible with save_measurements():
        {"TIMESTAMPS": np.ndarray, <meas_name>: np.ndarray, ...}
        """
        if not self.measurements:
            raise ValueError(
                "No measurements selected - call add_measurements() or set MEASUREMENTS in config."
            )

        if (duration_s is None) == (samples is None):
            raise ValueError("Provide either duration_s or samples, but not both")

        # Build per-measurement access info
        meas_info: list[dict[str, Any]] = []
        for m in self.measurements:
            try:
                dtype = self._numpy_dtype_for_asam(m.dataType, self.byte_order(m))
                nbytes = int(asam_type_size(m.dataType))
                addr = m.address
                info = {
                    "name": m.name,
                    "dtype": dtype,
                    "nbytes": nbytes,
                    "address": addr,
                    "bitMask": m.bitMask,
                    "bitOperation": m.bitOperation,
                    "compuMethod": m.compuMethod,
                }
                meas_info.append(info)
            except Exception as e:
                self.logger.error(
                    f"Cannot prepare measurement '{getattr(m, 'name', '?')}': {e}"
                )

        # Determine number of samples
        if samples is None:
            samples = max(1, int(round(duration_s / period_s)))  # type: ignore[arg-type]

        # Buffers
        buffers: dict[str, list[Any]] = {mi["name"]: [] for mi in meas_info}
        ts: list[float] = []

        t0 = time.perf_counter()
        for k in range(samples):
            t_now = time.perf_counter() - t0
            ts.append(t_now)
            for mi in meas_info:
                try:
                    data = master.upload(mi["address"], mi["nbytes"])  # returns bytes
                    val = np.frombuffer(data, dtype=mi["dtype"], count=1)[0]
                    # Apply bit operations
                    if mi["bitMask"] is not None:
                        val = val & mi["bitMask"]
                    bo = mi["bitOperation"]
                    if bo and bo.get("amount"):
                        amount = bo["amount"]
                        if bo.get("direction") == "L":
                            val = val << amount
                        else:
                            val = val >> amount
                    buffers[mi["name"]].append(val)
                except Exception as e:
                    self.logger.error(f"pyxcp upload failed for {mi['name']}: {e}")
                    buffers[mi["name"]].append(np.nan)
            # Sleep remaining time in period
            t_elapsed = time.perf_counter() - t0
            t_target = (k + 1) * period_s
            delay = t_target - t_elapsed
            if delay > 0:
                time.sleep(delay)

        # Post-process to physical values using pya2l compuMethods
        result: dict[str, Any] = {"TIMESTAMPS": np.asarray(ts)}
        for m in self.measurements:
            raw_vals = np.asarray(buffers[m.name])
            phys_vals = self.calculate_physical_values(raw_vals, m.compuMethod)
            result[m.name] = phys_vals
        return result

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
                conversion.update(
                    {f"phys_{i}": out_values[i] for i in range(len(out_values))}
                )
                conversion.update(default=default_value)
                conversion.update(interpolation=interpolation)
            elif cm_type == "TAB_VERB":
                default_value = compuMethod.tab_verb["default_value"]
                text_values = compuMethod.tab_verb["text_values"]
                if compuMethod.tab_verb["ranges"]:
                    lower_values = compuMethod.tab_verb["lower_values"]
                    upper_values = compuMethod.tab_verb["upper_values"]
                    conversion = {
                        f"lower_{i}": lower_values[i] for i in range(len(lower_values))
                    }
                    conversion.update(
                        {
                            f"upper_{i}": upper_values[i]
                            for i in range(len(upper_values))
                        }
                    )
                    conversion.update(
                        {f"text_{i}": text_values[i] for i in range(len(text_values))}
                    )
                    conversion.update(
                        default=(
                            bytes(default_value, encoding="utf-8")
                            if default_value
                            else b""
                        )
                    )
                else:
                    in_values = compuMethod.tab_verb["in_values"]
                    conversion = {
                        f"val_{i}": in_values[i] for i in range(len(in_values))
                    }
                    conversion.update(
                        {f"text_{i}": text_values[i] for i in range(len(text_values))}
                    )
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
