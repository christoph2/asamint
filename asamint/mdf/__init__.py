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
        self,
        mdf_filename: str | None = None,
        data: dict[str, Any] | None = None,
        *,
        strict: bool = False,
        strict_no_trim: bool = False,
        strict_no_synth: bool = False,
    ) -> None:
        """
        Save collected measurements into an MDF4 file.

        This function supports multi-rate acquisition by creating separate MDF
        Channel Groups per distinct timebase. It will:
        - Detect available timestamp arrays in the provided data dict
          (keys like 'TIMESTAMPS', 'timestamp0', 'timestamp1', case-insensitive).
        - Group signals by their sample counts and assign a matching timestamp
          array. If no exact match exists but a higher-rate timestamp length is
          an integer multiple, it will stride-select timestamps (e.g., ts[::k]).
        - Append one channel group per assigned timestamp set.
        """
        if not data:
            return

        # 1) Collect all candidate timestamp arrays from data
        # Normalize keys for case-insensitive match and prefer event-specific keys
        ts_candidates: dict[str, np.ndarray] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            kl = k.lower()
            if kl == "timestamps" or kl.startswith("timestamp"):
                try:
                    arr = np.asarray(v)
                    if arr.ndim == 1 and arr.size > 0:
                        ts_candidates[k] = arr
                except Exception:
                    pass

        # If no dedicated timestamp arrays found, we will synthesize later per group

        # 2) Build list of measurements present in data
        available_meas = [m for m in self.measurement_variables if m.name in data]
        if not available_meas:
            self.logger.warning("No matching measurement data present for MDF save.")
            return

        # Partition measurements by sample length
        groups_by_len: dict[int, list] = {}
        for m in available_meas:
            arr = np.asarray(data[m.name])
            groups_by_len.setdefault(int(arr.shape[0]), []).append(m)

        # Sort timestamp candidates by preference: event-specific before generic, then by length desc
        def _ts_priority(item: tuple[str, np.ndarray]) -> tuple[int, int]:
            name, arr = item
            lname = name.lower()
            # Prefer names like timestamp0/timestamp1 over generic 'timestamps'/'timestamp'
            is_event = (
                1
                if (
                    lname.startswith("timestamp")
                    and lname != "timestamp"
                    and lname != "timestamps"
                )
                else 0
            )
            return (is_event, int(arr.shape[0]))

        ts_items = sorted(
            ((k, v) for k, v in ts_candidates.items()),
            key=_ts_priority,
            reverse=True,
        )

        # 3) For each measurement-length group, choose or synthesize proper timestamps
        group_counter = 0
        for sample_len, meas_list in groups_by_len.items():
            # Pick best matching timestamp array
            chosen_ts: Optional[np.ndarray] = None
            chosen_src: Optional[str] = None
            for name, ts in ts_items:
                ts_len = int(ts.shape[0])
                if ts_len == sample_len:
                    chosen_ts = ts
                    chosen_src = name
                    break
            if chosen_ts is None:
                # Try downsample by integer stride from a higher-rate ts (with tolerance)
                for name, ts in ts_items:
                    ts_len = int(ts.shape[0])
                    if ts_len > sample_len:
                        # compute step as rounded ratio and allow small tail trimming if needed
                        ratio = ts_len / float(sample_len)
                        step = int(round(ratio)) if ratio > 0 else 0
                        if step <= 0:
                            continue
                        target = step * sample_len
                        if target <= ts_len and abs(ts_len - target) <= max(
                            1, int(0.01 * ts_len)
                        ):
                            ts_use = ts[:target]
                            try:
                                chosen_ts = ts_use[::step]
                                trimmed = "(trim)" if target != ts_len else ""
                                chosen_src = f"{name}[::${step}]{trimmed}"
                                # extra safety: ensure lengths now match
                                if int(chosen_ts.shape[0]) == sample_len:
                                    if (strict or strict_no_trim) and trimmed:
                                        raise ValueError(
                                            f"Strict mode: trimming timestamps not allowed for group len={sample_len} from source '{name}'"
                                        )
                                    break
                                else:
                                    # reset if mismatch and continue searching
                                    chosen_ts = None
                                    chosen_src = None
                            except Exception:
                                chosen_ts = None
                                chosen_src = None
            if chosen_ts is None:
                # Synthesize linear timestamps 0..N-1 as float
                if strict or strict_no_synth:
                    raise ValueError(
                        f"Strict mode: no compatible timestamps for sample_len={sample_len}; refusing to synthesize."
                    )
                self.logger.warning(
                    f"No compatible timestamps found for sample_len={sample_len}; synthesizing simple indices."
                )
                chosen_ts = np.arange(sample_len, dtype=float)
                chosen_src = "synthetic"

            # Estimate timebase (median dt) when possible
            timebase_s: Optional[float] = None
            try:
                if chosen_ts.shape[0] > 1:
                    dt = np.diff(chosen_ts.astype(float))
                    if dt.size:
                        # Interpret event-specific timestamps (timestamp*) as nanoseconds
                        # Normalize tb to seconds for metadata display
                        is_event_ts = False
                        if isinstance(chosen_src, str):
                            lsrc = chosen_src.lower()
                            # strip any stride annotation like [::10](trim)
                            base = lsrc.split("[")[0]
                            if base.startswith("timestamp") and base not in (
                                "timestamp",
                                "timestamps",
                            ):
                                is_event_ts = True
                        median_dt = float(np.median(dt))
                        timebase_s = median_dt / 1e9 if is_event_ts else median_dt
            except Exception:
                timebase_s = None

            group_id = group_counter
            group_counter += 1

            # 4) Build Signal objects for this group and append as a separate channel group
            signals: list[Signal] = []
            for measurement in meas_list:
                self.logger.info(
                    f"Adding SIGNAL: '{measurement.name}' (len={sample_len}) with timestamps='{chosen_src}'."
                )
                kws: dict[str, Any] = {}
                comment = measurement.longIdentifier
                compuMethod = measurement.compuMethod
                conversion_map = self.ccblock(compuMethod)
                unit = compuMethod.unit if compuMethod != "NO_COMPU_METHOD" else None

                samples = np.array(data.get(measurement.name), copy=False)

                # Step #1: bit fiddling.
                bitMask = measurement.bitMask
                if bitMask is not None:
                    samples &= bitMask
                bitOperation = measurement.bitOperation
                if bitOperation and bitOperation.get("amount", 0) != 0:
                    amount = bitOperation["amount"]
                    if bitOperation.get("direction") == "L":
                        samples <<= amount
                    else:
                        samples >>= amount

                # Step #2: apply COMPU_METHODs.
                samples = self.calculate_physical_values(samples, compuMethod)

                if getattr(compuMethod, "conversionType", None) == "TAB_VERB":
                    kws["encoding"] = "utf-8"
                    samples = samples.astype(bytes)

                # Align lengths defensively (should already match)
                if samples.shape[0] != chosen_ts.shape[0]:
                    if strict:
                        raise ValueError(
                            f"Strict mode: length mismatch for '{measurement.name}' samples({samples.shape[0]}) vs ts({chosen_ts.shape[0]})."
                        )
                    n = min(samples.shape[0], chosen_ts.shape[0])
                    self.logger.warning(
                        f"Length mismatch for '{measurement.name}' samples({samples.shape[0]}) vs ts({chosen_ts.shape[0]}). Trimming to {n}."
                    )
                    samples = samples[:n]
                    ts_use = chosen_ts[:n]
                else:
                    ts_use = chosen_ts

                # Enrich signal comment with timebase metadata (non-breaking)
                tb_str = (
                    f" tb≈{timebase_s:.6g}s"
                    if isinstance(timebase_s, (float, int))
                    else ""
                )
                # Add (ns) hint to src if source is event-specific timestamp*
                annotated_src = chosen_src
                try:
                    if isinstance(chosen_src, str):
                        base_src = chosen_src.lower().split("[")[0]
                        if base_src.startswith("timestamp") and base_src not in (
                            "timestamp",
                            "timestamps",
                        ):
                            if "(ns)" not in chosen_src:
                                annotated_src = f"{chosen_src}(ns)"
                except Exception:
                    annotated_src = chosen_src
                src_str = f" src={annotated_src}" if annotated_src is not None else ""
                grp_str = f" grp={group_id}"
                comment_enriched = (
                    comment or ""
                ) + f" [{tb_str}{src_str}{grp_str}]".replace("  ", " ").strip()

                signal = Signal(
                    samples=samples,
                    timestamps=ts_use,
                    name=measurement.name,
                    unit=unit or "",
                    conversion=conversion_map,
                    comment=comment_enriched,
                    **kws,
                )
                signals.append(signal)

            # New MDF Channel Group per timebase
            self._mdf_obj.append(signals)

        # 5) Save MDF
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
