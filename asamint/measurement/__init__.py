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
import logging
import time
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from asamint.adapters.a2l import model
from asamint.adapters.xcp import (
    ArgumentParser,
    DaqList,
    DaqRecorder,
    DaqToCsv,
    Hdf5OnlinePolicy,
)
from asamint.config import get_application
from asamint.hdf5 import HDF5Creator
from asamint.mdf import MDFCreator

logger = logging.getLogger(__name__)

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
    except Exception as exc:
        logger.debug("Failed to resolve group %s: %s", group_name, exc)
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


def _csv_fieldnames(data: dict[str, Any]) -> list[str]:
    return ["timestamp"] + sorted([k for k in data.keys() if k != "TIMESTAMPS"])


def _write_metadata_headers(
    fh,
    units: dict[str, Optional[str]],
    project_meta: Optional[dict[str, Any]],
    meta: Optional[dict[str, dict[str, Any]]],
) -> None:
    fh.write("# asamint measurement (converted physical values)\n")
    if project_meta:
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
            fh.write(f"# timebase: {sig} tb≈{tb_str}s src={src_str} grp={gid_str}\n")
    fh.write("#\n")


def _iter_csv_rows(
    timestamps: list[Any], series_keys: list[str], data: dict[str, Any]
) -> Iterable[list[Any]]:
    for idx, t_val in enumerate(timestamps):
        row = [t_val]
        for key in series_keys:
            arr = data.get(key)
            try:
                row.append(arr[idx])
            except Exception:
                row.append("")
        yield row


def _write_csv(
    csv_path: Path,
    data: dict[str, Any],
    units: dict[str, Optional[str]],
    project_meta: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, dict[str, Any]]] = None,
) -> None:
    fieldnames = _csv_fieldnames(data)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        _write_metadata_headers(fh, units, project_meta, meta)
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
                except Exception as exc:
                    logger.debug("Cannot determine length for series %s: %s", k, exc)
            ts = list(range(max_len))
        series_keys = [k for k in fieldnames if k != "timestamp"]
        for row in _iter_csv_rows(list(ts), series_keys, data):
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

    ts_items = _timestamp_candidates(data)
    result: dict[str, dict[str, Any]] = {}
    group_map: dict[str, int] = {}
    next_gid = 0

    for name in signal_names:
        chosen_src, chosen_ts, sample_len = _select_timestamp_for_signal(
            data, name, ts_items
        )
        tb = _median_timebase(chosen_src, chosen_ts)
        key = chosen_src or "synthetic"
        if key not in group_map:
            group_map[key] = next_gid
            next_gid += 1
        gid = group_map[key]
        result[name] = {
            "timestamp_source": chosen_src,
            "timebase_s": tb,
            "group_id": gid,
            "sample_count": sample_len,
        }

    return result


def _timestamp_candidates(data: dict[str, Any]) -> list[tuple[str, Any]]:
    import numpy as np

    candidates: dict[str, np.ndarray] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            continue
        lowered = key.lower()
        if lowered == "timestamps" or lowered.startswith("timestamp"):
            try:
                arr = np.asarray(value)
                if arr.ndim == 1 and arr.size > 0:
                    candidates[key] = arr
            except Exception as exc:
                logger.debug("Skipping timestamp candidate %s: %s", key, exc)
    return sorted(candidates.items(), key=_ts_priority, reverse=True)


def _ts_priority(item: tuple[str, Any]) -> tuple[int, int]:
    name, arr = item
    lname = name.lower()
    is_event = (
        1
        if lname.startswith("timestamp") and lname not in ("timestamp", "timestamps")
        else 0
    )
    try:
        length = int(arr.shape[0])
    except Exception:
        length = 0
    return (is_event, length)


def _select_timestamp_for_signal(
    data: dict[str, Any], name: str, ts_items: list[tuple[str, Any]]
) -> tuple[Optional[str], Optional[Any], int]:
    import numpy as np

    samples = data.get(name)
    if samples is None:
        return None, None, 0
    try:
        arr = np.asarray(samples)
    except Exception:
        return None, None, 0
    n = int(arr.shape[0]) if arr.ndim >= 1 else 0
    chosen_src, chosen_ts = _exact_timestamp_match(ts_items, n)
    if chosen_ts is None:
        chosen_src, chosen_ts = _stride_timestamp_match(ts_items, n)
    return chosen_src, chosen_ts, n


def _exact_timestamp_match(
    ts_items: list[tuple[str, Any]], sample_len: int
) -> tuple[Optional[str], Optional[Any]]:
    for src, ts in ts_items:
        if int(getattr(ts, "shape", [0])[0]) == sample_len:
            return src, ts
    return None, None


def _stride_timestamp_match(
    ts_items: list[tuple[str, Any]], sample_len: int
) -> tuple[Optional[str], Optional[Any]]:
    for src, ts in ts_items:
        ts_len = int(getattr(ts, "shape", [0])[0])
        if ts_len <= sample_len or sample_len <= 0:
            continue
        step = _stride_for_ratio(ts_len, sample_len)
        if step is None:
            continue
        target = step * sample_len
        ts_use = ts[:target]
        try:
            chosen_ts = ts_use[::step]
            trimmed = "(trim)" if target != ts_len else ""
            chosen_src = f"{src}[::${step}]{trimmed}"
            if int(getattr(chosen_ts, "shape", [0])[0]) == sample_len:
                return chosen_src, chosen_ts
        except Exception as exc:
            logger.debug("Failed stride selection for %s: %s", src, exc)
    return None, None


def _stride_for_ratio(ts_len: int, n: int) -> Optional[int]:
    if ts_len <= 0 or n <= 0:
        return None
    ratio = ts_len / float(n)
    step = int(round(ratio)) if ratio > 0 else 0
    if step <= 0:
        return None
    target = step * n
    if target > ts_len or abs(ts_len - target) > max(1, int(0.01 * ts_len)):
        return None
    return step


def _median_timebase(src: Optional[str], ts: Optional[Any]) -> Optional[float]:
    import numpy as np

    if ts is None:
        return None
    try:
        if getattr(ts, "shape", [0])[0] <= 1:
            return None
        dt = np.diff(ts.astype(float))
        if not dt.size:
            return None
        median_dt = float(np.median(dt))
        base_src = (src or "").lower().split("[")[0]
        if base_src.startswith("timestamp") and base_src not in (
            "timestamp",
            "timestamps",
        ):
            return median_dt / 1e9
        return median_dt
    except Exception:
        return None


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
            stacklevel=2,
        )
        return

    with h5py.File(str(h5_path), "w") as hf:
        # store a root-level attrs for project metadata
        for k, v in project_meta.items():
            try:
                hf.attrs[k] = v if v is not None else ""
            except Exception as exc:
                logger.debug("Skipping HDF5 root attr %s: %s", k, exc)
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


def finalize_measurement_outputs(
    data: dict[str, Any],
    units: Optional[dict[str, Optional[str]]] = None,
    project_meta: Optional[dict[str, Any]] = None,
    csv_out: Optional[str | Path] = None,
    hdf5_out: Optional[str | Path] = None,
) -> RunResult:
    """Persist measurement data to CSV/HDF5 with metadata and return paths/meta.

    Args:
        data: Mapping of signal name to samples; may include ``TIMESTAMPS``.
        units: Optional units per signal.
        project_meta: Optional project-level metadata to embed in outputs.
        csv_out: Target CSV path (absolute or relative to CWD).
        hdf5_out: Target HDF5 path (absolute or relative to CWD).

    Returns:
        RunResult with written CSV/HDF5 paths and per-signal metadata.

    Raises:
        ValueError: If neither ``csv_out`` nor ``hdf5_out`` is provided.
    """

    if csv_out is None and hdf5_out is None:
        msg = "At least one of csv_out or hdf5_out must be provided."
        raise ValueError(msg)

    units = units or {}
    project_meta = project_meta or {}
    signal_names = [name for name in data.keys() if name != "TIMESTAMPS"]
    meta = _compute_timebase_metadata(data, signal_names)
    meta_with_units = {
        name: {**meta.get(name, {}), "units": units.get(name)} for name in signal_names
    }

    csv_path: Path | None = None
    h5_path: Path | None = None

    if csv_out is not None:
        csv_path = Path(csv_out)
        if not csv_path.is_absolute():
            csv_path = Path.cwd() / csv_path
        _write_csv(csv_path, data, units, project_meta, meta_with_units)

    if hdf5_out is not None:
        h5_path = Path(hdf5_out)
        if not h5_path.is_absolute():
            h5_path = Path.cwd() / h5_path
        _write_hdf5(h5_path, data, meta_with_units, project_meta)

    return RunResult(
        mdf_path=None,
        csv_path=str(csv_path) if csv_path else None,
        hdf5_path=str(h5_path) if h5_path else None,
        signals=meta_with_units,
    )


def finalize_from_daq_csv(
    csv_files: Iterable[str | Path],
    units: Optional[dict[str, Optional[str]]] = None,
    project_meta: Optional[dict[str, Any]] = None,
    csv_out: Optional[str | Path] = None,
    hdf5_out: Optional[str | Path] = None,
) -> RunResult:
    """Merge DAQ CSV results, compute metadata, and persist to CSV/HDF5."""

    files = [Path(p) for p in csv_files]
    if not files:
        raise ValueError("No CSV files provided for finalization.")
    data = _merge_daq_csv_results(files)
    if not data:
        raise ValueError("No data parsed from DAQ CSV files.")
    return finalize_measurement_outputs(
        data=data,
        units=units,
        project_meta=project_meta,
        csv_out=csv_out,
        hdf5_out=hdf5_out,
    )


def _parse_daq_csv(csv_file: Path) -> dict[str, Any]:
    """
    Parse a single CSV produced by pyXCP DaqToCsv.

    Returns a dict: {"TIMESTAMPS": np.ndarray | None, <signal>: np.ndarray, ...}
    """
    import numpy as np  # local import to avoid hard dep when not used

    columns, rows = _read_daq_csv_rows(csv_file)
    if not columns:
        return {}

    norm = [c.strip() for c in columns]
    ts_idx = _timestamp_index(norm)

    col_data: list[list[float]] = [[] for _ in norm]
    for row in rows:
        for idx, value in enumerate(row):
            try:
                col_data[idx].append(float(value))
            except Exception as exc:
                logger.debug(
                    "Skipping non-numeric value %r at column %s: %s", value, idx, exc
                )

    result: dict[str, Any] = {}
    if ts_idx is not None:
        result["TIMESTAMPS"] = np.asarray(col_data[ts_idx])
    for i, name in enumerate(norm):
        if ts_idx is not None and i == ts_idx:
            continue
        result[name] = np.asarray(col_data[i])
    return result


def _read_daq_csv_rows(csv_file: Path) -> tuple[list[str], list[list[str]]]:
    columns: list[str] = []
    rows: list[list[str]] = []
    with csv_file.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        for raw in reader:
            if not raw or raw[0].startswith("#"):
                continue
            if not columns:
                columns = [c.strip() for c in raw]
                continue
            rows.append(raw)
    return columns, rows


def _timestamp_index(headers: list[str]) -> Optional[int]:
    ts_names = {"timestamp", "time", "TIMESTAMP", "TIME"}
    return next((i for i, col in enumerate(headers) if col in ts_names), None)


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
            warnings.warn(f"Failed to parse DAQ CSV {f}: {e}", stacklevel=2)
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


def _prepare_daq_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for group in groups:
        item = dict(group)
        item.setdefault("priority", 0)
        item.setdefault("prescaler", 1)
        prepared.append(item)
    return prepared


def _execute_daq_capture(
    daq_lists: list[DaqList],
    duration: Optional[float],
    samples: Optional[int],
    period_s: Optional[float],
    hdf5_out: Optional[str],
    shortname: str,
) -> str:
    target_hdf5 = hdf5_out or _auto_filename(shortname or "daq", "h5")
    daq_parser = Hdf5OnlinePolicy(target_hdf5, daq_lists)
    ap = ArgumentParser(description="asamint DAQ run")
    with ap.run(policy=daq_parser) as connection:
        connection.connect()
        if connection.slaveProperties.optionalCommMode:
            connection.getCommModeInfo()
        connection.cond_unlock("DAQ")
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
            connection.disconnect()
    return target_hdf5


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

    # valid_measurement = valid_measurements(names)
    creator.add_measurements(names)
    if not creator.measurement_variables:
        raise ValueError(
            "None of the requested measurements could be resolved from A2L."
        )

    daq_groups = _prepare_daq_groups(groups)
    try:
        daq_lists = build_daq_lists(creator.session, daq_groups)
        hdf5_out = _execute_daq_capture(
            daq_lists=daq_lists,
            duration=duration,
            samples=samples,
            period_s=period_s,
            hdf5_out=hdf5_out,
            shortname=app.general.shortname or "daq",
        )
    except Exception:
        raise
    finally:
        creator.close()

    return RunResult(
        mdf_path=None,
        csv_path=None,
        hdf5_path=str(hdf5_out) if hdf5_out else None,
        signals={},
    )
