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

import csv
import json
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from collections.abc import Iterable

from pya2l import model
from pyxcp.daq_stim import DaqList, DaqRecorder, DaqToCsv  # type: ignore
from pyxcp.master import Master  # type: ignore

from asamint.config import get_application
from asamint.hdf5 import HDF5Creator
from asamint.mdf import MDFCreator

PYXCP_TYPES = {
    "UBYTE": "U8",
    "SBYTE": "I8",
    "UWORD": "U16",
    "SWORD": "I16",
    "ULONG": "U32",
    "SLONG": "I32",
    "A_UINT64": "U64",
    "A_INT64": "I64",
    "FLOAT16_IEEE": "F16",
    "FLOAT32_IEEE": "F32",
    "FLOAT64_IEEE": "F64",
}


def group_measurements(
    session, group_name: str, exclude: Optional[Union[list[str], set[str]]] = None
) -> list[tuple[str, int, int, str]]:
    result = []
    if exclude:
        exclude = set(exclude)
    else:
        exclude = set()
    res = session.query(model.Group).filter(model.Group.groupName == group_name).first()
    for meas_name in res.ref_measurement.identifier:
        if meas_name in exclude:
            continue
        meas = (
            session.query(model.Measurement)
            .filter(model.Measurement.name == meas_name)
            .first()
        )
        result.append(
            (
                meas_name,
                meas.ecu_address.address,
                (
                    meas.ecu_address_extension.extension
                    if meas.ecu_address_extension
                    else 0
                ),
                PYXCP_TYPES[meas.datatype],
            )
        )
    return result


def resolve_measurements_by_names(
    session,
    names: Iterable[str],
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> list[tuple[str, int, int, str]]:
    """
    Resolve a list of A2L measurement names to pyXCP DAQ measurement tuples.

    Returns list of tuples: (name, address, extension, type_str)
    Unknown names are skipped.
    """
    result: list[tuple[str, int, int, str]] = []
    if exclude:
        exclude = set(exclude)
    else:
        exclude = set()
    for meas_name in names:
        if meas_name in exclude:
            continue
        meas = (
            session.query(model.Measurement)
            .filter(model.Measurement.name == meas_name)
            .first()
        )
        if not meas:
            # skip unknown
            continue
        # Some A2L may not define address extension
        ext = meas.ecu_address_extension.extension if meas.ecu_address_extension else 0
        dtype = PYXCP_TYPES.get(meas.datatype)
        if not dtype:
            # Fallback for unlisted types (treat like U32)
            dtype = "U32"
        result.append((meas_name, meas.ecu_address.address, ext, dtype))
    return result


def names_from_group(
    session,
    group_name: str,
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> list[str]:
    """
    Return measurement names contained in a given A2L Group.

    Unknown/missing group returns an empty list.
    """
    names: list[str] = []
    try:
        if exclude:
            exclude_set = set(exclude)
        else:
            exclude_set = set()
        res = (
            session.query(model.Group)
            .filter(model.Group.groupName == group_name)
            .first()
        )
        if not res:
            return names
        for meas_name in res.ref_measurement.identifier:
            if meas_name in exclude_set:
                continue
            names.append(meas_name)
    except Exception:
        # be permissive; return what we have
        pass
    return names


def daq_list_from_names(
    session,
    list_name: str,
    event_num: int,
    stim: bool,
    enable_timestamps: bool,
    names: Iterable[str],
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> DaqList:
    """Create a DaqList from explicit measurement names.

    The address, extension, and type are looked up from the A2L database.
    Unknown names are ignored.
    """
    meas = resolve_measurements_by_names(session, names, exclude)
    return DaqList(
        name=list_name,
        event_num=event_num,
        stim=stim,
        enable_timestamps=enable_timestamps,
        measurements=meas,
    )


def daq_list_from_group(
    session,
    list_name: str,
    event_num: int,
    stim: bool,
    enable_timestamps: bool,
    group_name: str,
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> DaqList:
    """
        DaqList(
        name="pwm_stuff",
        event_num=2,
        stim=False,
        enable_timestamps=True,
        measurements=[
            ("channel1", 0x1BD004, 0, "F32"),
            ("period", 0x001C0028, 0, "F32"),
            ("channel2", 0x1BD008, 0, "F32"),
            ("PWMFiltered", 0x1BDDE2, 0, "U8"),
            ("PWM", 0x1BDDDF, 0, "U8"),
            ("Triangle", 0x1BDDDE, 0, "I8"),
        ],
        priority=0,
        prescaler=1,
    ),
    """
    grp_measurements = group_measurements(session, group_name, exclude)
    return DaqList(
        name=list_name,
        event_num=event_num,
        stim=stim,
        enable_timestamps=enable_timestamps,
        measurements=grp_measurements,
    )


def build_daq_lists(
    session,
    groups: list[dict[str, Any]],
) -> list[DaqList]:
    """
    Build multiple DaqList objects from a group specification.

    Each group dict supports two modes:
      - Explicit names: {"name": str, "event_num": int, "variables": [str,...], "stim": bool=False, "enable_timestamps": bool=True}
      - A2L Group:      {"name": str, "event_num": int, "group_name": str, "stim": bool=False, "enable_timestamps": bool=True}

    Returns a list of DaqList ready to be passed to pyXCP for allocation.
    """
    result: list[DaqList] = []
    for g in groups:
        list_name = g.get("name")
        if not list_name:
            raise ValueError("Group spec requires 'name'.")
        event_num = g.get("event_num")
        if event_num is None:
            raise ValueError(f"Group '{list_name}' requires 'event_num'.")
        stim = bool(g.get("stim", False))
        enable_ts = bool(g.get("enable_timestamps", True))

        if "variables" in g and g["variables"]:
            dl = daq_list_from_names(
                session,
                list_name=list_name,
                event_num=event_num,
                stim=stim,
                enable_timestamps=enable_ts,
                names=g["variables"],
                exclude=g.get("exclude"),
            )
        elif "group_name" in g and g["group_name"]:
            dl = daq_list_from_group(
                session,
                list_name=list_name,
                event_num=event_num,
                stim=stim,
                enable_timestamps=enable_ts,
                group_name=g["group_name"],
                exclude=g.get("exclude"),
            )
        else:
            raise ValueError(
                f"Group '{list_name}' must define either 'variables' or 'group_name'."
            )
        result.append(dl)
    return result


# -------------------------------
# High-level acquisition (MVP)
# -------------------------------

def acquire_via_daq_stream(
    master: "Master",
    daq_lists: list[DaqList],
    duration: Optional[float] = None,
    samples: Optional[int] = None,
    enable_timestamps: bool = True,
) -> dict[str, Any]:
    """
    Acquire data using pyXCP DAQ with in-process callbacks.

    Returns a dict compatible with MDFCreator.save_measurements():
    {
        "TIMESTAMPS": np.ndarray[float]  # seconds (generic timeline for readability),
        "timestamp{i}": np.ndarray[int64]  # per‑event timelines in nanoseconds,
        <signal>: np.ndarray,
        ...
    }
    """
    import time as _time

    import numpy as np

    if (duration is None) == (samples is None):
        raise ValueError("Provide either duration or samples (exclusively).")

    # Flatten measurement names from DAQ lists for mapping
    meas_names: list[str] = []
    for dl in daq_lists:
        for m in dl.measurements:
            name = m[0]
            if name not in meas_names:
                meas_names.append(name)

    buffers: dict[str, list[Any]] = {n: [] for n in meas_names}
    # Generic seconds timeline (for readability / CSV primary column)
    timestamps_sec: list[float] = []

    # Build a stable index per DAQ list to name per‑event timestamp arrays as timestamp0, timestamp1, ...
    event_to_idx: dict[int, int] = {}
    for idx, dl in enumerate(daq_lists):
        # Multiple DAQ lists could theoretically map to the same event number; last one wins deterministically
        try:
            event_to_idx[int(dl.event_num)] = idx
        except Exception:
            # fallback: still assign index by order if event_num not available
            event_to_idx[idx] = idx

    # Per‑event timestamp buffers in nanoseconds
    ts_ns_by_idx: dict[int, list[int]] = {i: [] for i in range(len(daq_lists))}

    t0 = _time.perf_counter()

    # Define record callback
    def on_record(event_num: int, record_ts: Optional[float], payload: dict[str, Any]):
        # payload expected as {name: value, ...}
        if enable_timestamps:
            # Generic seconds timeline
            if record_ts is not None and record_ts > 1e6:
                # Heuristic: treat large values as already in nanoseconds
                ts_sec = float(record_ts) / 1e9
            else:
                # record_ts may be seconds or None; if None, synthesize via perf_counter
                ts_sec = (
                    float(record_ts)
                    if record_ts is not None
                    else _time.perf_counter() - t0
                )
            timestamps_sec.append(ts_sec)

            # Per‑event nanoseconds timeline
            idx = event_to_idx.get(int(event_num), 0)
            if record_ts is None:
                ts_ns = int((_time.perf_counter() - t0) * 1e9)
            else:
                # If it looks like seconds (small), convert to ns; if large, assume already ns
                ts_ns = int(record_ts * 1e9) if record_ts < 1e6 else int(record_ts)
            ts_ns_by_idx[idx].append(ts_ns)

        for k, v in payload.items():
            if k in buffers:
                buffers[k].append(v)

    # Setup DAQ
    # The master is assumed connected/unlocked by caller; we keep a conservative sequence
    master.cond_unlock("DAQ")
    di = master.daq
    di.setup(daq_lists)
    # Try to register callback; fall back if not supported
    registered = False
    if hasattr(di, "register_record_callback"):
        try:
            di.register_record_callback(on_record)  # type: ignore[attr-defined]
            registered = True
        except Exception:
            registered = False

    if not registered:
        # If streaming callbacks not supported, raise so caller can fall back
        raise RuntimeError("pyXCP DAQ streaming callbacks not available in this build")

    di.start()
    try:
        if samples is not None:
            # Busy-wait until we collected at least `samples` entries (based on timestamp count)
            # Note: multiple signals per record; timestamps length is a proxy for record count
            while len(timestamps_sec) < samples:
                _time.sleep(0.001)
        elif duration is not None:
            _time.sleep(max(0.0, float(duration)))
    finally:
