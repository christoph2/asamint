#!/usr/bin/env python
"""
validate_mf4: Inspect an MF4 file and optionally cross-check with CSV/HDF5.

Usage:
  python -m tools.validate_mf4 --mf4 path/to/file.mf4 [--csv path/to/file.csv] [--hdf5 path/to/file.h5]

Outputs a summary of MDF channel groups (sample counts, inferred timebase in seconds)
and member signals. If CSV/HDF5 are provided, lengths and basic timebase consistency
are cross-checked. Exit code 0 on OK; non-zero if mismatches are detected.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_length(value: Any) -> int | None:
    try:
        return len(value)
    except TypeError:
        return None


def _read_hdf5_dataset(dset: Any) -> Any | None:
    try:
        return dset[()]
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _group_index(channel: Any) -> int | None:
    raw_group_index = getattr(channel, "group_index", getattr(channel, "group_id", -1))
    return _safe_int(raw_group_index)


def _iter_mdf_channels(mdf: Any) -> list[Any]:
    iter_channels = getattr(mdf, "iter_channels", None)
    if callable(iter_channels):
        try:
            return list(iter_channels())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            pass
    channels_db = getattr(mdf, "channels_db", None)
    if isinstance(channels_db, dict):
        return list(channels_db.values())
    return []


def _channel_sample_count(channel: Any) -> int | None:
    samples = getattr(channel, "samples", None)
    return _safe_length(samples)


def _channel_timebase(channel: Any) -> float | None:
    timestamps = getattr(channel, "timestamps", None)
    if timestamps is None:
        return None
    return _infer_timebase_seconds(timestamps)


def _infer_timebase_seconds(timestamps) -> float | None:
    try:
        import numpy as np

        ts = np.asarray(timestamps)
        if ts.size < 2:
            return None
        # Work in float to ensure diff
        tsf = ts.astype(float)
        dt = np.diff(tsf)
        if dt.size == 0:
            return None
        median_dt = float(np.median(dt))
        # Heuristic: MDF timestamps likely in nanoseconds if values are very large
        # Normalize to seconds when either dt or absolute ts are big.
        if median_dt > 1e6 or (np.nanmax(tsf) if tsf.size else 0.0) > 1e6:
            return median_dt / 1e9
        return median_dt
    except Exception:
        return None


def _load_csv(csv_path: Path) -> dict[str, Any]:
    import csv

    import numpy as np

    cols: list[str] = []
    rows: list[list[str]] = []
    header_lines: list[str] = []
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        rdr = csv.reader(fh)
        for raw in rdr:
            if not raw:
                continue
            if raw[0].startswith("#"):
                # Keep header comments for timebase parsing
                header_lines.append(",".join(raw))
                continue
            if not cols:
                cols = [c.strip() for c in raw]
                continue
            rows.append(raw)
    data: dict[str, Any] = {}
    if not cols:
        return data
    col_data: list[list[float]] = [[] for _ in cols]
    for r in rows:
        for i, v in enumerate(r):
            parsed_value = _safe_float(v)
            if parsed_value is not None:
                col_data[i].append(parsed_value)
    for i, name in enumerate(cols):
        data[name] = np.asarray(col_data[i])
    # Attach parsed header lines for optional timebase map
    data["__HEADER_LINES__"] = header_lines
    return data


def _parse_csv_timebase_header(header_lines: list[str]) -> dict[str, dict[str, Any]]:
    """Parse '# timebase:' lines into a mapping {signal: {tb, src, grp}}.

    Expected format: '# timebase: <sig> tb≈<seconds>s src=<src> grp=<id>'
    Returns dict with keys: timebase_s (float|None), timestamp_source (str|None), group_id (int|None)
    """
    import re

    result: dict[str, dict[str, Any]] = {}
    # Regex to capture: timebase: <sig> tb≈<num>s src=<src> grp=<gid>
    pattern = re.compile(
        r"^#\s*timebase:\s*(?P<sig>[^\s]+)\s+tb≈(?P<tb>[^s]*)s\s+src=(?P<src>[^\s]*)\s+grp=(?P<gid>.*)$"
    )
    for line in header_lines:
        txt = line.strip()
        if not txt.startswith("#"):
            continue
        if "# timebase:" not in txt:
            continue
        m = pattern.match(txt)
        if not m:
            continue
        sig = m.group("sig").strip()
        tb_raw = m.group("tb").strip()
        src = m.group("src").strip() or None
        gid_raw = m.group("gid").strip()
        tb = _safe_float(tb_raw) if tb_raw else None
        gid = _safe_int(gid_raw) if gid_raw else None
        result[sig] = {
            "timebase_s": tb,
            "timestamp_source": src,
            "group_id": gid,
        }
    return result


def _load_hdf5(h5_path: Path) -> dict[str, Any]:
    try:
        import h5py  # type: ignore
    except Exception:
        return {}
    result: dict[str, Any] = {}
    with h5py.File(str(h5_path), "r") as hf:
        for name, dset in hf.items():
            dataset = _read_hdf5_dataset(dset)
            if dataset is not None:
                result[name] = dataset
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate MF4 and cross-check with CSV/HDF5"
    )
    parser.add_argument("--mf4", required=True, type=Path, help="Path to MF4 file")
    parser.add_argument(
        "--csv", type=Path, default=None, help="Optional CSV to cross-check"
    )
    parser.add_argument(
        "--hdf5", type=Path, default=None, help="Optional HDF5 to cross-check"
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Print per-signal checks (length, timebase, and referenced timestamp presence)",
    )
    return parser


def _collect_members_by_group(mdf) -> dict[int, list[Any]]:
    members_by_group: dict[int, list[Any]] = {}
    for channel in _iter_mdf_channels(mdf):
        group_index = _group_index(channel)
        if group_index is not None:
            members_by_group.setdefault(group_index, []).append(channel)
    return members_by_group


def _build_groups_info(members_by_group: dict[int, list[Any]]) -> list[dict[str, Any]]:
    groups_info: list[dict[str, Any]] = []
    for group_index, members in sorted(members_by_group.items(), key=lambda kv: kv[0]):
        timebase = None
        sample_count = None
        for channel in members:
            if sample_count is None:
                sample_count = _channel_sample_count(channel)
            if timebase is None:
                timebase = _channel_timebase(channel)
        groups_info.append(
            {
                "group_index": group_index,
                "members": [getattr(member, "name", "?") for member in members],
                "timebase_s": timebase,
                "sample_count": sample_count,
            }
        )
    return groups_info


def _print_group_summary(groups_info: list[dict[str, Any]]) -> None:
    print("Channel groups summary:")
    for info in groups_info:
        print(
            f"- Group {info['group_index']}: samples≈{info['sample_count']} tb≈{info['timebase_s']}s members={len(info['members'])}"
        )


def _print_group_details(members_by_group: dict[int, list[Any]]) -> None:
    print("Per-signal details:")
    for group_index, members in sorted(members_by_group.items(), key=lambda kv: kv[0]):
        for channel in members:
            name = getattr(channel, "name", "?")
            timebase = _channel_timebase(channel)
            sample_count = _channel_sample_count(channel)
            print(f"  - {name}: group={group_index} tb≈{timebase}s len={sample_count}")


def _load_csv_info(
    csv_path: Path | None, warnings: list[str]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not csv_path or not csv_path.exists():
        return {}, {}
    csv_data = _load_csv(csv_path)
    if not csv_data:
        warnings.append(f"CSV could not be parsed or empty: {csv_path}")
        return {}, {}
    print(
        f"CSV: {csv_path} (columns={len(csv_data) - (1 if '__HEADER_LINES__' in csv_data else 0)})"
    )
    header_lines = csv_data.pop("__HEADER_LINES__", [])
    return csv_data, _parse_csv_timebase_header(header_lines) if header_lines else {}


def _load_hdf5_info(hdf5_path: Path | None, warnings: list[str]) -> dict[str, Any]:
    if not hdf5_path or not hdf5_path.exists():
        return {}
    h5_data = _load_hdf5(hdf5_path)
    if h5_data:
        print(f"HDF5: {hdf5_path} (datasets={len(h5_data)})")
        return h5_data
    warnings.append(f"HDF5 could not be parsed or empty: {hdf5_path}")
    return {}


def _compare_csv_hdf5_lengths(
    csv_data: dict[str, Any], h5_data: dict[str, Any], errors: list[str]
) -> None:
    common = set(csv_data.keys()).intersection(set(h5_data.keys()))
    for key in list(common)[:10]:
        csv_length = _safe_length(csv_data[key])
        hdf5_length = _safe_length(h5_data[key])
        if (
            csv_length is not None
            and hdf5_length is not None
            and csv_length != hdf5_length
        ):
            errors.append(
                f"Length mismatch for '{key}': CSV={csv_length} vs HDF5={hdf5_length}"
            )


def _normalized_timestamp_source(source: Any) -> str:
    base = str(source)
    base = base.split("[")[0]
    return base.replace("(ns)", "").strip()


def _compare_csv_signal_to_mf4(
    mf4_path: Path,
    signal_name: str,
    signal_values,
    csv_data: dict[str, Any],
    csv_timebase_map: dict[str, dict[str, Any]],
    details: bool,
    warnings: list[str],
    errors: list[str],
) -> None:
    from asammdf import MDF  # type: ignore

    with MDF(str(mf4_path)) as mdf:
        channel = _get_mf4_channel(mdf, signal_name)
        if channel is None:
            warnings.append(f"CSV column '{signal_name}' not found in MF4")
            return
        len_mf4, len_csv = _compare_signal_lengths(
            signal_name, channel, signal_values, errors
        )
        _compare_signal_timebase(
            signal_name,
            channel,
            csv_data,
            csv_timebase_map,
            details,
            len_csv,
            len_mf4,
            warnings,
        )


def _get_mf4_channel(mdf, signal_name: str):
    try:
        return mdf.get(signal_name)
    except Exception:
        return None


def _compare_signal_lengths(
    signal_name: str, channel, signal_values, errors: list[str]
) -> tuple[int, int]:
    len_mf4 = len(channel.samples)
    len_csv = len(signal_values)
    if len_mf4 != len_csv:
        errors.append(
            f"Length mismatch for signal '{signal_name}': MF4={len_mf4} vs CSV={len_csv}"
        )
    return len_mf4, len_csv


def _compare_signal_timebase(
    signal_name: str,
    channel,
    csv_data: dict[str, Any],
    csv_timebase_map: dict[str, dict[str, Any]],
    details: bool,
    len_csv: int,
    len_mf4: int,
    warnings: list[str],
) -> None:
    if signal_name not in csv_timebase_map:
        return
    tb_csv = csv_timebase_map[signal_name].get("timebase_s")
    tb_mf4 = _infer_timebase_seconds(channel.timestamps)
    if tb_csv is not None and tb_mf4 is not None:
        denom = max(tb_csv, 1e-12)
        if abs(tb_mf4 - tb_csv) / denom > 0.05:
            warnings.append(
                f"Timebase differs for '{signal_name}': CSV header tb≈{tb_csv}s vs MF4≈{tb_mf4}s"
            )
    if details:
        print(
            f"Check: {signal_name}: len CSV/MF4 = {len_csv}/{len_mf4}, tb CSV/MF4 = {tb_csv}/{tb_mf4}"
        )
    source = csv_timebase_map[signal_name].get("timestamp_source")
    if source and source != "synthetic":
        base = _normalized_timestamp_source(source)
        if base and base not in csv_data:
            warnings.append(
                f"CSV missing referenced timestamp column '{base}' for signal '{signal_name}'"
            )
        elif details:
            print(f"Check: {signal_name}: referenced timestamp column present: {base}")


def _compare_csv_to_mf4(
    mf4_path: Path,
    csv_data: dict[str, Any],
    csv_timebase_map: dict[str, dict[str, Any]],
    details: bool,
    warnings: list[str],
    errors: list[str],
) -> None:
    skip_columns = {"timestamp", "time"}
    skip_columns.update({key for key in csv_data.keys() if key.startswith("timestamp")})
    for signal_name, signal_values in csv_data.items():
        if signal_name in skip_columns:
            continue
        try:
            _compare_csv_signal_to_mf4(
                mf4_path,
                signal_name,
                signal_values,
                csv_data,
                csv_timebase_map,
                details,
                warnings,
                errors,
            )
        except Exception as e:
            warnings.append(f"Comparison failed for '{signal_name}': {e}")


def _report_results(warnings: list[str], errors: list[str]) -> int:
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    from asammdf import MDF  # type: ignore

    errors: list[str] = []
    warnings: list[str] = []

    print(f"MF4: {args.mf4}")
    with MDF(str(args.mf4)) as mdf:
        members_by_group = _collect_members_by_group(mdf)
        _print_group_summary(_build_groups_info(members_by_group))
        if args.details:
            try:
                _print_group_details(members_by_group)
            except Exception:
                warnings.append("Failed to print detailed MF4 channel information.")

    csv_data, csv_timebase_map = _load_csv_info(args.csv, warnings)
    h5_data = _load_hdf5_info(args.hdf5, warnings)
    if csv_data and h5_data:
        _compare_csv_hdf5_lengths(csv_data, h5_data, errors)
    if csv_data:
        _compare_csv_to_mf4(
            args.mf4, csv_data, csv_timebase_map, args.details, warnings, errors
        )
    return _report_results(warnings, errors)


if __name__ == "__main__":
    sys.exit(main())
