#!/usr/bin/env python
from __future__ import annotations

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

import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from asamint.adapters.a2l import model
from asamint.adapters.measurement import (
    MeasurementFormat,
    available_measurement_formats,
    get_measurement_format,
    register_measurement_format,
)
from asamint.adapters.xcp import ArgumentParser, DaqList, Hdf5OnlinePolicy
from asamint.config import get_application
from asamint.core.logging import configure_logging
from asamint.measurement.csv import (
    _csv_fieldnames,
    _iter_csv_rows,
    _merge_daq_csv_results,
    _parse_daq_csv,
    _read_daq_csv_rows,
    _timestamp_index,
    _write_csv,
    _write_metadata_headers,
)
from asamint.measurement.hdf5 import (
    HDF5Creator,
    _annotate_daq_hdf5_metadata,
    _annotate_hdf5_root,
    _write_hdf5,
)
from asamint.measurement.mdf import MDFCreator

logger = configure_logging(__name__)

__all__ = [
    "RunResult",
    "group_measurements",
    "resolve_measurements_by_names",
    "names_from_group",
    "daq_list_from_names",
    "daq_list_from_group",
    "build_daq_lists",
    "finalize_measurement_outputs",
    "finalize_from_daq_csv",
    "run",
    "_csv_fieldnames",
    "_write_metadata_headers",
    "_iter_csv_rows",
    "_write_csv",
    "_parse_daq_csv",
    "_read_daq_csv_rows",
    "_timestamp_index",
    "_compute_timebase_metadata",
    "_median_timebase",
    "_merge_daq_csv_results",
    "_stride_for_ratio",
    "_unique_names_from_groups",
    "_write_hdf5",
    "_annotate_hdf5_root",
    "_annotate_daq_hdf5_metadata",
    "_prepare_daq_groups",
    "_collect_timebase_summary",
    "persist_measurements",
    "list_measurement_formats",
    "available_measurement_formats",
    "register_measurement_format",
    "get_measurement_format",
    "HDF5Creator",
    "MDFCreator",
]

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
    session: Any, group_name: str, exclude: Optional[Union[list[str], set[str]]] = None
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
    session: Any,
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
    session: Any,
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
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug("Failed to resolve group %s: %s", group_name, exc)
    return names


def daq_list_from_names(
    session: Any,
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
    session: Any,
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
    session: Any,
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


def _resolve_output_format(preferred: Optional[str], hdf5_out: Optional[str]) -> str:
    if hdf5_out:
        return "HDF5"
    if preferred:
        return preferred.upper()
    return "MDF"


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
            except (TypeError, ValueError) as exc:
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
    except (AttributeError, IndexError, TypeError):
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
    except (TypeError, ValueError):
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
        except (IndexError, AttributeError, TypeError) as exc:
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
    except (TypeError, AttributeError, ZeroDivisionError):
        return None


def _collect_timebase_summary(meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[int, dict[str, Any]] = {}
    for sig, info in meta.items():
        gid = info.get("group_id")
        if gid is None:
            continue
        entry = summary.setdefault(
            int(gid),
            {
                "group_id": int(gid),
                "timestamp_source": info.get("timestamp_source"),
                "timebase_s": info.get("timebase_s"),
                "members": [],
            },
        )
        if entry.get("timestamp_source") is None and info.get("timestamp_source"):
            entry["timestamp_source"] = info["timestamp_source"]
        if entry.get("timebase_s") is None and info.get("timebase_s") is not None:
            entry["timebase_s"] = info["timebase_s"]
        entry["members"].append(sig)
    return [summary[idx] for idx in sorted(summary.keys())]


def _collect_daq_timebases(
    daq_lists: list[DaqList], timebase_hint_s: Optional[float]
) -> list[dict[str, Any]]:
    hint = float(timebase_hint_s) if timebase_hint_s is not None else None
    summary: list[dict[str, Any]] = []
    for dl in daq_lists:
        members = [m[0] for m in getattr(dl, "measurements", [])]
        summary.append(
            {
                "group_id": dl.event_num,
                "timestamp_source": dl.name,
                "timebase_s": hint,
                "members": members,
            }
        )
    return summary


def _prepare_daq_metadata(
    daq_lists: list[DaqList],
    project_meta: dict[str, Any],
    *,
    duration: Optional[float],
    samples: Optional[int],
    period_s: Optional[float],
) -> dict[str, Any]:
    meta = {k: v for k, v in project_meta.items() if v not in (None, "")}
    meta["daq_list_count"] = len(daq_lists)
    meta["daq_event_numbers"] = [dl.event_num for dl in daq_lists]
    meta["daq_list_names"] = [dl.name for dl in daq_lists]
    if period_s is not None:
        try:
            meta["daq_timebase_hint_s"] = float(period_s)
        except (ValueError, TypeError):
            pass
    if duration is not None:
        try:
            meta["daq_duration_s"] = float(duration)
        except (ValueError, TypeError):
            pass
    if samples is not None:
        try:
            meta["daq_samples"] = int(samples)
        except (ValueError, TypeError):
            pass
    return meta


def finalize_measurement_outputs(
    data: dict[str, Any],
    units: Optional[dict[str, Optional[str]]] = None,
    project_meta: Optional[dict[str, Any]] = None,
    csv_out: Optional[str | Path] = None,
    hdf5_out: Optional[str | Path] = None,
    signal_metadata: Optional[dict[str, dict[str, Any]]] = None,
    *,
    hdf5_only: bool = False,
) -> RunResult:
    """Persist measurement data to CSV/HDF5 with metadata and return paths/meta.

    Args:
        data: Mapping of signal name to samples; may include ``TIMESTAMPS``.
        units: Optional units per signal.
        project_meta: Optional project-level metadata to embed in outputs.
        csv_out: Target CSV path (absolute or relative to CWD).
        hdf5_out: Target HDF5 path (absolute or relative to CWD).
        signal_metadata: Optional per-signal metadata to merge (e.g., compu methods).
        hdf5_only: If True, skip CSV writing even if ``csv_out`` is provided.

    Returns:
        RunResult with written CSV/HDF5 paths and per-signal metadata.

    Raises:
        ValueError: If neither ``csv_out`` nor ``hdf5_out`` is provided.
    """

    if hdf5_only:
        csv_out = None

    if csv_out is None and hdf5_out is None:
        msg = "At least one of csv_out or hdf5_out must be provided."
        raise ValueError(msg)

    units = units or {}
    project_meta = project_meta or {}
    signal_names = [name for name in data.keys() if name != "TIMESTAMPS"]
    meta = _compute_timebase_metadata(data, signal_names)
    if signal_metadata:
        for name, extra in signal_metadata.items():
            base = meta.setdefault(name, {})
            base.update(extra)
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

    timebases = _collect_timebase_summary(meta_with_units)

    return RunResult(
        mdf_path=None,
        csv_path=str(csv_path) if csv_path else None,
        hdf5_path=str(h5_path) if h5_path else None,
        signals=meta_with_units,
        timebases=timebases,
    )


def finalize_from_daq_csv(
    csv_files: Iterable[str | Path],
    units: Optional[dict[str, Optional[str]]] = None,
    project_meta: Optional[dict[str, Any]] = None,
    csv_out: Optional[str | Path] = None,
    hdf5_out: Optional[str | Path] = None,
    *,
    hdf5_only: bool = False,
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
        csv_out=None if hdf5_only else csv_out,
        hdf5_out=hdf5_out,
        hdf5_only=hdf5_only,
    )


def persist_measurements(
    format_name: str,
    *,
    data: dict[str, Any],
    units: Optional[dict[str, Optional[str]]] = None,
    project_meta: Optional[dict[str, Any]] = None,
    output_path: str | Path | None = None,
    **kwargs: Any,
) -> RunResult:
    """Persist measurement data using a registered backend."""

    fmt = get_measurement_format(format_name)
    return fmt.persist(
        data=data,
        units=units,
        project_meta=project_meta,
        output_path=output_path,
        **kwargs,
    )


def list_measurement_formats() -> list[str]:
    """Return supported measurement formats."""

    return available_measurement_formats()


def _persist_csv_format(
    *,
    data: dict[str, Any],
    units: Optional[dict[str, Optional[str]]],
    project_meta: Optional[dict[str, Any]],
    output_path: str | Path | None,
    **_: Any,
) -> RunResult:
    target = str(output_path) if output_path is not None else _auto_filename("measurement", ".csv")
    return finalize_measurement_outputs(
        data=data, units=units, project_meta=project_meta, csv_out=target, hdf5_out=None
    )


def _persist_hdf5_format(
    *,
    data: dict[str, Any],
    units: Optional[dict[str, Optional[str]]],
    project_meta: Optional[dict[str, Any]],
    output_path: str | Path | None,
    **_: Any,
) -> RunResult:
    target = str(output_path) if output_path is not None else _auto_filename("measurement", ".h5")
    return finalize_measurement_outputs(
        data=data,
        units=units,
        project_meta=project_meta,
        csv_out=None,
        hdf5_out=target,
        hdf5_only=True,
    )


def _persist_mdf_format(
    *,
    data: dict[str, Any],
    units: Optional[dict[str, Optional[str]]],
    project_meta: Optional[dict[str, Any]],
    output_path: str | Path | None,
    creator: Optional[Any] = None,
    exp_cfg: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> RunResult:
    local_creator = creator
    created_here = False
    if local_creator is None:
        if exp_cfg is None:
            msg = "MDF persistence requires either an MDFCreator instance or exp_cfg."
            raise ValueError(msg)
        local_creator = MDFCreator(exp_cfg)
        created_here = True
    try:
        return local_creator.save_measurements(
            mdf_filename=str(output_path) if output_path is not None else None,
            data=data,
            csv_out=kwargs.get("csv_out"),
            hdf5_out=kwargs.get("hdf5_out"),
            project_meta=project_meta,
            strict=bool(kwargs.get("strict", False)),
            strict_no_trim=bool(kwargs.get("strict_no_trim", False)),
            strict_no_synth=bool(kwargs.get("strict_no_synth", False)),
        )
    finally:
        if created_here:
            try:
                local_creator.close()
            except (OSError, AttributeError):  # pragma: no cover - best-effort cleanup
                logger.debug("Failed to close temporary MDFCreator", exc_info=True)


def _register_default_formats() -> None:
    register_measurement_format(
        MeasurementFormat(
            name="CSV",
            persist=_persist_csv_format,
            description="CSV export of physical measurements",
            default_extension=".csv",
        )
    )
    register_measurement_format(
        MeasurementFormat(
            name="HDF5",
            persist=_persist_hdf5_format,
            creator_factory=lambda exp_cfg: HDF5Creator(exp_cfg),
            description="HDF5 export and live capture via HDF5Creator",
            default_extension=".h5",
        )
    )
    register_measurement_format(
        MeasurementFormat(
            name="MDF",
            persist=_persist_mdf_format,
            creator_factory=lambda exp_cfg: MDFCreator(exp_cfg),
            description="ASAM MDF export via asammdf",
            default_extension=".mf4",
        )
    )


_register_default_formats()


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
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    target_hdf5 = hdf5_out or _auto_filename(shortname or "daq", "h5")
    daq_parser = Hdf5OnlinePolicy(target_hdf5, daq_lists, **(metadata or {}))
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


def _run_daq_flow(
    creator: Any,
    daq_groups: list[dict[str, Any]],
    *,
    daq_lists: Optional[list[DaqList]] = None,
    duration: Optional[float],
    samples: Optional[int],
    period_s: Optional[float],
    hdf5_out: Optional[str],
    shortname: str,
    project_meta: dict[str, Any],
) -> RunResult:
    daq_lists = (
        daq_lists if daq_lists is not None else build_daq_lists(creator.session, daq_groups)
    )
    timebase_hint_s = float(period_s) if period_s is not None else None
    metadata = _prepare_daq_metadata(
        daq_lists,
        project_meta,
        duration=duration,
        samples=samples,
        period_s=period_s,
    )
    hdf5_path = _execute_daq_capture(
        daq_lists=daq_lists,
        duration=duration,
        samples=samples,
        period_s=period_s,
        hdf5_out=hdf5_out,
        shortname=shortname,
        metadata=metadata,
    )
    return RunResult(
        mdf_path=None,
        csv_path=None,
        hdf5_path=str(hdf5_path) if hdf5_path else None,
        signals={},
        timebases=_collect_daq_timebases(daq_lists, timebase_hint_s),
    )


def _run_daq_flow_wrapper(
    groups: list[dict[str, Any]],
    duration: Optional[float],
    samples: Optional[int],
    period_s: Optional[float],
    hdf5_out: Optional[str],
) -> RunResult:
    app = get_application()
    exp_cfg = {
        "SUBJECT": f"SUBJ_{app.general.shortname}" if app.general.shortname else "",
        "DESCRIPTION": "",
        "SHORTNAME": app.general.shortname or "",
        "TIME_SOURCE": "local PC reference timer",
        "MEASUREMENTS": [],
        "FUNCTIONS": [],
        "GROUPS": [],
    }
    format_name = _resolve_output_format(app.general.output_format, hdf5_out)
    fmt = get_measurement_format(format_name)
    if not fmt.supports_live_capture or fmt.creator_factory is None:
        raise ValueError(f"Measurement format '{format_name}' does not support DAQ capture.")
    creator = fmt.creator_factory(exp_cfg)

    names = _unique_names_from_groups(groups)
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
        creator.close()
        raise ValueError("No variable names provided in groups.")
    creator.add_measurements(names)
    if not creator.measurement_variables:
        creator.close()
        raise ValueError(
            "None of the requested measurements could be resolved from A2L."
        )

    project_meta = {
        "author": getattr(app.general, "author", None),
        "company": getattr(app.general, "company", None),
        "department": getattr(app.general, "department", None),
        "project": getattr(app.general, "project", None),
        "shortname": getattr(app.general, "shortname", None),
        "subject": exp_cfg.get("SUBJECT"),
        "time_source": exp_cfg.get("TIME_SOURCE"),
    }

    daq_groups = _prepare_daq_groups(groups)
    daq_lists = build_daq_lists(creator.session, daq_groups)
    try:
        result = _run_daq_flow(
            creator=creator,
            daq_groups=daq_groups,
            daq_lists=daq_lists,
            duration=duration,
            samples=samples,
            period_s=period_s,
            hdf5_out=hdf5_out,
            shortname=app.general.shortname or "daq",
            project_meta=project_meta,
        )
        if result.hdf5_path:
            _annotate_hdf5_root(Path(result.hdf5_path), project_meta)
            _annotate_daq_hdf5_metadata(
                Path(result.hdf5_path),
                daq_lists,
                project_meta,
                timebase_hint_s=result.timebases[0]["timebase_s"] if result.timebases else None,
            )
        return result
    finally:
        creator.close()


def _run_polling_flow(
    creator: Any,
    *,
    duration: Optional[float],
    samples: Optional[int],
    period_s: Optional[float],
    mdf_out: Optional[str],
    csv_out: Optional[str],
    hdf5_out: Optional[str],
    strict_mdf: bool,
    strict_no_trim: bool,
    strict_no_synth: bool,
    project_meta: dict[str, Any],
) -> RunResult:
    data = creator.acquire_via_pyxcp(
        master=creator.xcp_master,
        duration_s=duration,
        samples=samples,
        period_s=period_s or 0.01,
    )
    if isinstance(creator, MDFCreator):
        mdf_path = mdf_out or creator.generate_filename(".mf4")
        return creator.save_measurements(
            mdf_filename=mdf_path,
            data=data,
            csv_out=csv_out,
            hdf5_out=hdf5_out,
            strict=strict_mdf,
            strict_no_trim=strict_no_trim,
            strict_no_synth=strict_no_synth,
            project_meta=project_meta,
        )
    if isinstance(creator, HDF5Creator):
        csv_target = csv_out or mdf_out
        h5_target = hdf5_out or creator.generate_filename(".h5")
        return finalize_measurement_outputs(
            data=data,
            units=None,
            project_meta=project_meta,
            csv_out=csv_target,
            hdf5_out=h5_target,
        )
    return RunResult(
        mdf_path=None,
        csv_path=None,
        hdf5_path=hdf5_out,
        signals={},
    )


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
    # DAQ path handled separately to keep this function within lint complexity limits.
    if use_daq:
        return _run_daq_flow_wrapper(
            groups=groups,
            duration=duration,
            samples=samples,
            period_s=period_s,
            hdf5_out=hdf5_out,
        )

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
    format_name = _resolve_output_format(app.general.output_format, hdf5_out)
    fmt = get_measurement_format(format_name)
    if not fmt.supports_live_capture or fmt.creator_factory is None:
        raise ValueError(
            f"Measurement format '{format_name}' does not support polling acquisition."
        )
    creator = fmt.creator_factory(
        exp_cfg
    )  # AsamMC passes (app_config, exp_cfg) into on_init

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

    project_meta = {
        "author": getattr(app.general, "author", None),
        "company": getattr(app.general, "company", None),
        "department": getattr(app.general, "department", None),
        "project": getattr(app.general, "project", None),
        "shortname": getattr(app.general, "shortname", None),
        "subject": exp_cfg.get("SUBJECT"),
        "time_source": exp_cfg.get("TIME_SOURCE"),
    }

    try:
        return _run_polling_flow(
            creator=creator,
            duration=duration,
            samples=samples,
            period_s=period_s,
            mdf_out=mdf_out,
            csv_out=csv_out,
            hdf5_out=hdf5_out,
            strict_mdf=strict_mdf,
            strict_no_trim=strict_no_trim,
            strict_no_synth=strict_no_synth,
            project_meta=project_meta,
        )
    finally:
        creator.close()
