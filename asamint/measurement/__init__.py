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
from asamint.hdf5.policy import Hdf5OnlinePolicy
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


@dataclass
class RunResult:
    mdf_path: Optional[str]
    csv_path: Optional[str]
    hdf5_path: Optional[str]
    signals: dict[str, dict[str, Any]]
    # Optional summary of detected timebases (one entry per distinct timestamp source)
    # Each item: {"group_id": int, "timestamp_source": str, "timebase_s": float|None, "members": [signal names]}
    timebases: Optional[list[dict[str, Any]]] = None


def _auto_filename(prefix: str, ext: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    name = prefix or "asamint"
    return f"{name}_{ts}{ext}"


def _unique_names_from_groups(groups: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for g in groups:
        if g.get("variables"):
            for n in g["variables"]:
                if n not in seen:
                    seen.add(n)
                    names.append(n)
    return names


def _write_csv(
    csv_path: Path,
    data: dict[str, Any],
    units: dict[str, Optional[str]],
    project_meta: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, dict[str, Any]]] = None,
) -> None:
    # Prepare header with timestamp + signal names
    fieldnames = ["timestamp"] + [k for k in data.keys() if k != "TIMESTAMPS"]
    # Ensure stable order
    fieldnames = ["timestamp"] + sorted([k for k in data.keys() if k != "TIMESTAMPS"])
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        # Metadata header
        fh.write("# asamint measurement (converted physical values)\n")
        if project_meta:
            # Write project/experiment metadata preamble
            for key in (
                "author",
                "company",
                "department",
                "project",
                "shortname",
                "subject",
                "time_source",
            ):
                if key in project_meta and project_meta[key] not in (None, ""):
                    fh.write(f"# {key}: {project_meta[key]}\n")
        for sig, unit in units.items():
            if unit:
                fh.write(f"# {sig} [{unit}]\n")
            else:
                fh.write(f"# {sig}\n")
        # Per-signal timebase metadata (if available)
        if meta:
            fh.write(
                "# timebase metadata per signal: tb≈<seconds>, src=<timestamp key>, grp=<id>\n"
            )
            for sig in sorted(k for k in units.keys()):
                m = meta.get(sig, {})
                tb = m.get("timebase_s")
                src = m.get("timestamp_source")
                gid = m.get("group_id")
                if tb is None and src is None and gid is None:
                    continue
                tb_str = f"{tb:.6g}" if isinstance(tb, (int, float)) else ""
                src_str = str(src) if src is not None else ""
                gid_str = str(gid) if gid is not None else ""
                fh.write(
                    f"# timebase: {sig} tb≈{tb_str}s src={src_str} grp={gid_str}\n"
                )
        # blank line after headers for readability
        fh.write("#\n")
        writer = csv.writer(fh)
        writer.writerow(fieldnames)
        ts = data.get("TIMESTAMPS")
        if ts is None:
            # Synthesize simple 0..N-1 if no timestamps
            max_len = 0
            for k, v in data.items():
                if k == "TIMESTAMPS":
                    continue
                try:
                    max_len = max(max_len, len(v))
                except Exception:
                    pass
            ts = list(range(max_len))
        # Compose rows
        # Build aligned columns by index
        series_keys = [k for k in fieldnames if k != "timestamp"]
        for idx in range(len(ts)):
            row = [ts[idx]]
            for k in series_keys:
                arr = data.get(k)
                try:
                    row.append(arr[idx])
                except Exception:
                    row.append("")
            writer.writerow(row)


def _compute_timebase_metadata(
    data: dict[str, Any], signal_names: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Compute per-signal timebase mapping and summary from a data dict.

    Returns a dict mapping signal name to a metadata fragment with keys:
    - timestamp_source: str | None
    - timebase_s: float | None (median dt)
    - group_id: int (stable index per timestamp source)
    """
    import numpy as np

    # 1) Collect timestamp candidates
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

    # sort by preference: event-specific timestamp* first, then by length desc
    def _ts_priority(item):
        name, arr = item
        lname = name.lower()
        is_event = (
            1
            if (
                lname.startswith("timestamp")
                and lname not in ("timestamp", "timestamps")
            )
            else 0
        )
        return (is_event, int(arr.shape[0]))

    ts_items = sorted(ts_candidates.items(), key=_ts_priority, reverse=True)

    # 2) Map each signal to the best matching timestamp source
    result: dict[str, dict[str, Any]] = {}
    # assign group ids by the chosen_src string
    group_map: dict[str, int] = {}
    next_gid = 0

    for name in signal_names:
        samples = data.get(name)
        if samples is None:
            continue
        try:
            arr = np.asarray(samples)
        except Exception:
            continue
        n = int(arr.shape[0]) if arr.ndim >= 1 else 0
        chosen_src: Optional[str] = None
        chosen_ts: Optional[np.ndarray] = None
        # exact match first
        for src, ts in ts_items:
            if int(ts.shape[0]) == n:
                chosen_src = src
                chosen_ts = ts
                break
        if chosen_ts is None:
            # try stride from higher-rate with small tolerance and optional tail trim
            for src, ts in ts_items:
                ts_len = int(ts.shape[0])
                if ts_len > n and n > 0:
                    ratio = ts_len / float(n)
                    step = int(round(ratio)) if ratio > 0 else 0
                    if step <= 0:
                        continue
                    target = step * n
                    # allow small tail trimming up to 1% or at least 1 sample
                    if target <= ts_len and abs(ts_len - target) <= max(
                        1, int(0.01 * ts_len)
                    ):
                        ts_use = ts[:target]
                        try:
                            chosen_ts = ts_use[::step]
                            trimmed = "(trim)" if target != ts_len else ""
                            chosen_src = f"{src}[::${step}]{trimmed}"
                            if int(chosen_ts.shape[0]) == n:
                                break
                            else:
                                chosen_ts = None
                                chosen_src = None
                        except Exception:
                            chosen_ts = None
                            chosen_src = None
        # compute timebase
        tb: Optional[float] = None
        if chosen_ts is not None and chosen_ts.shape[0] > 1:
            try:
                dt = np.diff(chosen_ts.astype(float))
                if dt.size:
                    median_dt = float(np.median(dt))
                    # Treat event-specific timestamp* arrays as nanoseconds and convert to seconds
                    base_src = (chosen_src or "").lower().split("[")[0]
                    if base_src.startswith("timestamp") and base_src not in (
                        "timestamp",
                        "timestamps",
                    ):
                        tb = median_dt / 1e9
                        # annotate source as ns for clarity if not already annotated
                        if chosen_src and "(ns)" not in chosen_src:
                            chosen_src = f"{chosen_src}(ns)"
                    else:
                        tb = median_dt
            except Exception:
                tb = None
        # group id
        key = chosen_src or "synthetic"
        if key not in group_map:
            group_map[key] = next_gid
            next_gid += 1
        gid = group_map[key]
        result[name] = {
            "timestamp_source": chosen_src,
            "timebase_s": tb,
            "group_id": gid,
        }

    return result


def _write_hdf5(
    h5_path: Path,
    data: dict[str, Any],
    meta: dict[str, dict[str, Any]],
    project_meta: dict[str, Any],
) -> None:
    """
    Write converted values to HDF5 with per-signal datasets and metadata attributes.
    This uses h5py if available; otherwise a warning is emitted and the file is not written.
    """
    try:
        import h5py  # type: ignore
        import numpy as np  # ensure numpy available
    except Exception as e:  # pragma: no cover
        warnings.warn(
            f"HDF5 export requested but h5py is not available: {e}. Skipping HDF5 write.",
            RuntimeWarning,
        )
        return

    with h5py.File(str(h5_path), "w") as hf:
        # store a root-level attrs for project metadata
        for k, v in project_meta.items():
            try:
                hf.attrs[k] = v if v is not None else ""
            except Exception:
                # ensure attribute assignment doesn't break
                pass
        # timestamps dataset
        ts = data.get("TIMESTAMPS")
        if ts is not None:
            dset_ts = hf.create_dataset("timestamps", data=ts)
            dset_ts.attrs["description"] = "Relative timestamps in seconds"
        # per-signal datasets
        for name, values in data.items():
            if name == "TIMESTAMPS":
                continue
            dset = hf.create_dataset(name, data=values)
            m = meta.get(name, {})
            # attach useful attributes
            if m.get("units"):
                dset.attrs["units"] = m["units"]
            if m.get("compu_method"):
                dset.attrs["compu_method"] = m["compu_method"]
            if m.get("sample_count") is not None:
                dset.attrs["sample_count"] = int(m["sample_count"])  # type: ignore[arg-type]


def _parse_daq_csv(csv_file: Path) -> dict[str, Any]:
    """
    Parse a single CSV produced by pyXCP DaqToCsv.

    Returns a dict: {"TIMESTAMPS": np.ndarray | None, <signal>: np.ndarray, ...}
    """
    import numpy as np  # local import to avoid hard dep when not used

    columns: list[str] = []
    rows: list[list[str]] = []
    with csv_file.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for raw in reader:
            if not raw:
                continue
            if raw[0].startswith("#"):
                continue
            if not columns:
                columns = [c.strip() for c in raw]
                continue
            rows.append(raw)

    if not columns:
        return {}

    # candidate names for timestamp column
    ts_names = {"timestamp", "time", "TIMESTAMP", "TIME"}
    # normalize header
    norm = [c.strip() for c in columns]
    ts_idx = next((i for i, c in enumerate(norm) if c in ts_names), None)

    col_data: list[list[float]] = [[] for _ in norm]
    for r in rows:
        for i, v in enumerate(r):
            try:
                col_data[i].append(float(v))
            except Exception:
                # best-effort parse; skip non-numeric
                pass

    result: dict[str, Any] = {}
    if ts_idx is not None:
        result["TIMESTAMPS"] = np.asarray(col_data[ts_idx])
    for i, name in enumerate(norm):
        if ts_idx is not None and i == ts_idx:
            continue
        result[name] = np.asarray(col_data[i])
    return result


def _merge_daq_csv_results(files: Iterable[Path]) -> dict[str, Any]:
    """
    Merge multiple DaqToCsv CSV files into one data dict.
    Prefer the first file's timestamps if available; warn on length mismatches.
    """
    import numpy as np

    merged: dict[str, Any] = {}
    base_ts = None
    for f in files:
        try:
            part = _parse_daq_csv(f)
        except Exception as e:
            warnings.warn(f"Failed to parse DAQ CSV {f}: {e}")
            continue
        if not part:
            continue
        ts = part.get("TIMESTAMPS")
        if base_ts is None and ts is not None:
            base_ts = ts
            merged["TIMESTAMPS"] = ts
        for k, v in part.items():
            if k == "TIMESTAMPS":
                continue
            merged[k] = v
    # Ensure TIMESTAMPS present if any signals exist
    if "TIMESTAMPS" not in merged and merged:
        # Synthesize simple 0..N-1 based on the longest series
        max_len = max(
            (len(v) for k, v in merged.items() if k != "TIMESTAMPS"), default=0
        )
        merged["TIMESTAMPS"] = np.arange(max_len, dtype=float)
    return merged


# ---------------------------------
# DAQ streaming (A2) via callbacks
# ---------------------------------


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
        di.stop()
        if hasattr(di, "unregister_record_callback"):
            try:
                di.unregister_record_callback(on_record)  # type: ignore[attr-defined]
            except Exception:
                pass

    # Build result
    result: dict[str, Any] = {}
    if enable_timestamps and timestamps_sec:
        # Generic seconds timeline
        result["TIMESTAMPS"] = np.asarray(timestamps_sec, dtype=float)
        # Per‑event nanoseconds timelines
        for idx, buf in ts_ns_by_idx.items():
            if buf:
                result[f"timestamp{idx}"] = np.asarray(buf, dtype=np.int64)
    # Convert buffers to arrays; they can be ragged if some signals miss records
    for name, vals in buffers.items():
        try:
            result[name] = np.asarray(vals)
        except Exception:
            # fallback to object dtype
            result[name] = np.asarray(vals, dtype=object)
    return result


def run(
    groups: list[dict[str, Any]],
    duration: Optional[float] = None,
    samples: Optional[int] = None,
    period_s: Optional[float] = 0.01,
    mdf_out: Optional[str] = None,
    csv_out: Optional[str] = None,
    hdf5_out: Optional[str] = None,
    enable_timestamps: bool = True,  # reserved for DAQ path
    overwrite: bool = True,
    use_daq: bool = True,
    streaming: bool = False,
    strict_mdf: bool = False,
    strict_no_trim: bool = False,
    strict_no_synth: bool = False,
) -> RunResult:
    """
    High-level measurement runner (MVP, polling acquisition).

    Parameters
    - groups: list of dicts, each may include:
        {"name": str, "event_num": int, "variables": [str, ...]}  # explicit names
        or {"name": str, "event_num": int, "group_name": str}     # A2L group (not used in MVP resolve)
    - duration or samples: provide exactly one.
    - period_s: polling period for master.upload()
    - mdf_out/csv_out: optional output paths; if None, generated using shortname + timestamp.

    Returns RunResult with paths and per-signal metadata.
    """
    if (duration is None) == (samples is None):
        raise ValueError("Provide either duration or samples, but not both or neither.")

    app = get_application()

    # Prepare MDF creator with an experiment_config shim
    exp_cfg = {
        "SUBJECT": f"SUBJ_{app.general.shortname}" if app.general.shortname else "",
        "DESCRIPTION": "",
        "SHORTNAME": app.general.shortname or "",
        "TIME_SOURCE": "local PC reference timer",
        # We will set MEASUREMENTS after resolving names
        "MEASUREMENTS": [],
        "FUNCTIONS": [],
        "GROUPS": [],
    }

    # Prepare creator based on output format
    output_format = app.general.output_format.upper()
    if hdf5_out or output_format == "HDF5":
        creator_class = HDF5Creator
    else:
        creator_class = MDFCreator

    creator = creator_class(exp_cfg)  # AsamMC passes (app_config, exp_cfg) into on_init

    # Resolve variable names
    # 1) Collect explicit variables
    names = _unique_names_from_groups(groups)
    # 2) Expand any A2L group_name entries to variables via the A2L session
    for g in groups:
        grp_name = g.get("group_name")
        if grp_name:
            extra = names_from_group(
                creator.session, grp_name, exclude=g.get("exclude")
            )
            for n in extra:
                if n not in names:
                    names.append(n)
    if not names:
        raise ValueError("No variable names provided in groups.")

    creator.add_measurements(names)
    if not creator.measurement_variables:
        raise ValueError(
            "None of the requested measurements could be resolved from A2L."
        )

    # Acquire via pyXCP polling
    data: dict[str, Any]
    if use_daq:
        # Build DAQ lists from provided groups
        try:
            # enrich groups with priority/prescaler defaults
            daq_groups: list[dict[str, Any]] = []
            for g in groups:
                gg = dict(g)
                gg.setdefault("priority", 0)
                gg.setdefault("prescaler", 1)
                daq_groups.append(gg)
            daq_lists = build_daq_lists(creator.session, daq_groups)
            if streaming:
                # Use in-process streaming via callbacks
                creator.xcp_connect()
                try:
                    data = acquire_via_daq_stream(
                        creator.xcp_master,
                        daq_lists,
                        duration=duration,
                        samples=samples,
                        enable_timestamps=enable_timestamps,
                    )
                finally:
                    creator.close()
            else:
                # Prefer CSV output from pyXCP's DaqToCsv; we'll parse and convert via A2L.
                from pyxcp.cmdline import ArgumentParser  # type: ignore
    try:
        # enrich groups with priority/prescaler defaults
        daq_groups: list[dict[str, Any]] = []
        for g in groups:
            gg = dict(g)
            gg.setdefault("priority", 0)
            gg.setdefault("prescaler", 1)
            daq_groups.append(gg)
        daq_lists = build_daq_lists(creator.session, daq_groups)

        # Prefer CSV output from pyXCP's DaqToCsv; we'll parse and convert via A2L.
        from pyxcp.cmdline import ArgumentParser  # type: ignore

        # daq_parser = DaqToCsv(daq_lists)
        daq_parser = Hdf5OnlinePolicy(daq_lists)

        ap = ArgumentParser(description="asamint DAQ run")
        with ap.run(policy=daq_parser) as x:
            x.connect()
            if x.slaveProperties.optionalCommMode:
                x.getCommModeInfo()
            x.cond_unlock("DAQ")
            daq_parser.setup()
            daq_parser.start()
            try:
                if samples is not None and period_s:
                    time.sleep(max(0.0, samples * float(period_s)))
                elif duration is not None:
                    time.sleep(max(0.0, float(duration)))
                else:
                    time.sleep(1.0)
            finally:
                daq_parser.stop()
                x.disconnect()
    except Exception as e:
        # Fallback to polling path if DAQ integration fails
        warnings.warn(f"DAQ path failed ({e}); falling back to polling acquisition.")
        creator = creator_class(exp_cfg)
        creator.add_measurements(names)
        creator.xcp_connect()
        try:
            data = creator.acquire_via_pyxcp(
                creator.xcp_master,
                duration_s=duration,
                samples=samples,
                period_s=period_s or 0.01,
            )
        finally:
            creator.close()
    return

    # Prepare per-signal metadata (units, compu method name, counts)
    meta: dict[str, dict[str, Any]] = {}
    for m in creator.measurement_variables:
        unit = None
        if m.compuMethod != "NO_COMPU_METHOD":
            try:
                unit = m.compuMethod.unit
            except Exception:
                unit = None
        meta[m.name] = {
            "units": unit,
            "compu_method": (
                None
                if m.compuMethod == "NO_COMPU_METHOD"
                else getattr(m.compuMethod, "name", None)
            ),
            "sample_count": len(data.get(m.name, [])),
        }

    # Compute and merge timebase metadata (non-breaking)
    tb_meta = _compute_timebase_metadata(data, meta.keys())
    for name, extra in tb_meta.items():
        if name not in meta:
            meta[name] = {}
        meta[name].update(extra)

    # Build timebases summary for RunResult
    timebases: list[dict[str, Any]] = []
    # group by group_id
    groups: dict[int, dict[str, Any]] = {}
    for sig, m in meta.items():
        gid = m.get("group_id")
        if gid is None:
            continue
        if gid not in groups:
            groups[gid] = {
                "group_id": gid,
                "timestamp_source": m.get("timestamp_source"),
                "timebase_s": m.get("timebase_s"),
                "members": [],
            }
        groups[gid]["members"].append(sig)
        # Prefer non-None values if missing in summary
        if (
            groups[gid].get("timestamp_source") is None
            and m.get("timestamp_source") is not None
        ):
            groups[gid]["timestamp_source"] = m.get("timestamp_source")
        if groups[gid].get("timebase_s") is None and m.get("timebase_s") is not None:
            groups[gid]["timebase_s"] = m.get("timebase_s")
    if groups:
        timebases = [groups[k] for k in sorted(groups.keys())]

    # Save measurements in primary format
    primary_path: Optional[str] = None
    csv_path: Optional[str] = None
    h5_path: Optional[str] = None

    if output_format == "HDF5":
        primary_ext = ".h5"
        primary_out = hdf5_out
    else:
        primary_ext = ".mf4"
        primary_out = mdf_out

    primary_file = (
        Path(primary_out)
        if primary_out
        else Path(_auto_filename(app.general.shortname, primary_ext))
    )
    if primary_file.exists() and not overwrite:
        raise FileExistsError(f"File exists and overwrite=False: {primary_file}")

    creator.save_measurements(
        str(primary_file),
        data=data,
        strict=strict_mdf,
        strict_no_trim=strict_no_trim,
        strict_no_synth=strict_no_synth,
    )
    primary_path = str(primary_file)

    # Optional CSV export of converted values
    if csv_out is not None:
        csv_file = Path(csv_out)
    else:
        csv_file = None
    if csv_file is None and csv_out is not None:
        csv_file = Path(csv_out)
    if csv_file is None and csv_out is None:
        # generate alongside primary
        csv_file = primary_file.with_suffix(".csv")
    if csv_file is not None:
        if csv_file.exists() and not overwrite:
            raise FileExistsError(f"File exists and overwrite=False: {csv_file}")
        units = {m: meta[m]["units"] for m in meta.keys()}
        project_meta = {
            "author": app.general.author,
            "company": app.general.company,
            "department": app.general.department,
            "project": app.general.project,
            "shortname": app.general.shortname,
            "subject": exp_cfg.get("SUBJECT"),
            "time_source": exp_cfg.get("TIME_SOURCE"),
        }
        _write_csv(csv_file, data, units, project_meta, meta)
        csv_path = str(csv_file)

    # Optional HDF5 export of converted values with metadata (only if not primary format)
    if hdf5_out is not None and output_format != "HDF5":
        h5_file = Path(hdf5_out)
        if h5_file.exists() and not overwrite:
            raise FileExistsError(f"File exists and overwrite=False: {h5_file}")
        project_meta = {
            "author": app.general.author,
            "company": app.general.company,
            "department": app.general.department,
            "project": app.general.project,
            "shortname": app.general.shortname,
            "subject": exp_cfg.get("SUBJECT"),
            "time_source": exp_cfg.get("TIME_SOURCE"),
        }
        _write_hdf5(h5_file, data, meta, project_meta)
        h5_path = str(h5_file)
    elif output_format == "HDF5":
        h5_path = primary_path

    return RunResult(
        mdf_path=primary_path if output_format == "MDF" else None,
        csv_path=csv_path,
        hdf5_path=h5_path,
        signals=meta,
        timebases=timebases or None,
    )
