#!/usr/bin/env python
from __future__ import annotations

import csv
import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

import numpy as np

from asamint.core.logging import configure_logging

logger = configure_logging(__name__)


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


def _parse_daq_csv(csv_file: Path) -> dict[str, Any]:
    """
    Parse a single CSV produced by pyXCP DaqToCsv.

    Returns a dict: {"TIMESTAMPS": np.ndarray | None, <signal>: np.ndarray, ...}
    """
    fast = _fast_parse_daq_csv(csv_file)
    if fast is not None:
        return fast
    return _parse_daq_csv_python(csv_file)


def _fast_parse_daq_csv(csv_file: Path) -> Optional[dict[str, Any]]:
    """Fast path using numpy.genfromtxt; returns None to fall back on errors."""

    try:
        first_non_ws: Optional[str] = None
        with csv_file.open("r", encoding="utf-8") as fh:
            for line in fh:
                stripped = line.lstrip()
                if not stripped:
                    continue
                first_non_ws = stripped[0]
                break
        if first_non_ws == "#":
            return None
    except Exception as exc:  # pragma: no cover - guarded fallback
        logger.debug("Fast CSV precheck skipped for %s: %s", csv_file, exc)
        return None

    try:
        arr = np.genfromtxt(
            csv_file,
            delimiter=",",
            names=True,
            autostrip=True,
            comments="#",
            dtype=float,
            invalid_raise=False,
        )
    except Exception as exc:  # pragma: no cover - guarded fallback
        logger.debug("Fast CSV parse skipped for %s: %s", csv_file, exc)
        return None

    if arr.size == 0:
        return {}
    if arr.dtype.names is None:
        return None

    arr = np.atleast_1d(arr)
    names = list(arr.dtype.names)
    ts_idx = _timestamp_index(names)

    result: dict[str, Any] = {}
    for idx, name in enumerate(names):
        series = np.asarray(arr[name])
        if ts_idx is not None and idx == ts_idx:
            result["TIMESTAMPS"] = series
        else:
            result[name] = series

    return result


def _parse_daq_csv_python(csv_file: Path) -> dict[str, Any]:
    """Original Python parser fallback for DAQ CSV files."""
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


def _merge_daq_csv_results(files: Iterable[Path]) -> dict[str, Any]:
    """
    Merge multiple DaqToCsv CSV files into one data dict.
    Prefer the first file's timestamps if available; warn on length mismatches.
    """
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
    if "TIMESTAMPS" not in merged and merged:
        max_len = max((len(v) for k, v in merged.items() if k != "TIMESTAMPS"), default=0)
        merged["TIMESTAMPS"] = np.arange(max_len, dtype=float)
    return merged

