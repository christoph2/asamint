#!/usr/bin/env python
# -*- coding: utf-8 -*-
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
from typing import Dict, Any, List


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


def _load_csv(csv_path: Path) -> Dict[str, Any]:
    import csv
    import numpy as np

    cols: List[str] = []
    rows: List[List[str]] = []
    header_lines: List[str] = []
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
    data: Dict[str, Any] = {}
    if not cols:
        return data
    col_data: List[List[float]] = [[] for _ in cols]
    for r in rows:
        for i, v in enumerate(r):
            try:
                col_data[i].append(float(v))
            except Exception:
                pass
    for i, name in enumerate(cols):
        data[name] = np.asarray(col_data[i])
    # Attach parsed header lines for optional timebase map
    data["__HEADER_LINES__"] = header_lines
    return data


def _parse_csv_timebase_header(header_lines: List[str]) -> Dict[str, Dict[str, Any]]:
    """Parse '# timebase:' lines into a mapping {signal: {tb, src, grp}}.

    Expected format: '# timebase: <sig> tb≈<seconds>s src=<src> grp=<id>'
    Returns dict with keys: timebase_s (float|None), timestamp_source (str|None), group_id (int|None)
    """
    import re

    result: Dict[str, Dict[str, Any]] = {}
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
        try:
            tb = float(tb_raw) if tb_raw else None
        except Exception:
            tb = None
        try:
            gid = int(gid_raw) if gid_raw else None
        except Exception:
            gid = None
        result[sig] = {
            "timebase_s": tb,
            "timestamp_source": src,
            "group_id": gid,
        }
    return result


def _load_hdf5(h5_path: Path) -> Dict[str, Any]:
    try:
        import h5py  # type: ignore
    except Exception:
        return {}
    result: Dict[str, Any] = {}
    with h5py.File(str(h5_path), "r") as hf:
        for name, dset in hf.items():
            try:
                result[name] = dset[()]  # numpy array
            except Exception:
                pass
    return result


def main(argv: List[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    from asammdf import MDF  # type: ignore

    errors: List[str] = []
    warnings: List[str] = []

    print(f"MF4: {args.mf4}")
    with MDF(str(args.mf4)) as mdf:
        # Robust enumeration across asammdf versions: iterate channels and group by group_index
        groups_info: List[Dict[str, Any]] = []
        members_by_group: Dict[int, List[Any]] = {}
        try:
            # Preferred: iterator over channels
            for ch in mdf.iter_channels():  # type: ignore[attr-defined]
                gi = getattr(ch, "group_index", getattr(ch, "group_id", -1))
                members_by_group.setdefault(int(gi), []).append(ch)
        except Exception:
            # Fallback: try channels_db attribute
            try:
                for ch in getattr(mdf, "channels_db", {}).values():  # type: ignore
                    gi = getattr(ch, "group_index", getattr(ch, "group_id", -1))
                    members_by_group.setdefault(int(gi), []).append(ch)
            except Exception:
                members_by_group = {}

        # Build summary
        for gi, members in sorted(members_by_group.items(), key=lambda kv: kv[0]):
            tb = None
            sample_count = None
            for ch in members:
                try:
                    if sample_count is None:
                        sample_count = len(ch.samples)
                    if tb is None and getattr(ch, "timestamps", None) is not None:
                        tb = _infer_timebase_seconds(ch.timestamps)
                except Exception:
                    pass
            groups_info.append(
                {
                    "group_index": gi,
                    "members": [getattr(c, "name", "?") for c in members],
                    "timebase_s": tb,
                    "sample_count": sample_count,
                }
            )

        print("Channel groups summary:")
        for info in groups_info:
            print(
                f"- Group {info['group_index']}: samples≈{info['sample_count']} tb≈{info['timebase_s']}s members={len(info['members'])}"
            )
        if args.details:
            # Print per-signal assignment with group and inferred tb
            try:
                print("Per-signal details:")
                for gi, members in sorted(
                    members_by_group.items(), key=lambda kv: kv[0]
                ):
                    for ch in members:
                        try:
                            name = getattr(ch, "name", "?")
                            tb = _infer_timebase_seconds(
                                getattr(ch, "timestamps", None)
                            )
                            print(
                                f"  - {name}: group={gi} tb≈{tb}s len={len(ch.samples)}"
                            )
                        except Exception:
                            pass
            except Exception:
                pass

    # Cross-checks
    csv_timebase_map: Dict[str, Dict[str, Any]] = {}
    if args.csv and args.csv.exists():
        csv_data = _load_csv(args.csv)
        if csv_data:
            print(
                f"CSV: {args.csv} (columns={len(csv_data) - (1 if '__HEADER_LINES__' in csv_data else 0)})"
            )
            # Parse timebase header metadata if present
            header_lines = csv_data.pop("__HEADER_LINES__", [])  # remove helper key
            if header_lines:
                csv_timebase_map = _parse_csv_timebase_header(header_lines)
        else:
            warnings.append(f"CSV could not be parsed or empty: {args.csv}")

    if args.hdf5 and args.hdf5.exists():
        h5_data = _load_hdf5(args.hdf5)
        if h5_data:
            print(f"HDF5: {args.hdf5} (datasets={len(h5_data)})")
        else:
            warnings.append(f"HDF5 could not be parsed or empty: {args.hdf5}")

    # Cross-checks between CSV and HDF5 lengths (basic)
    if args.csv and args.csv.exists() and args.hdf5 and args.hdf5.exists():
        csv_data = _load_csv(args.csv)
        h5_data = _load_hdf5(args.hdf5)
        common = set(csv_data.keys()).intersection(set(h5_data.keys()))
        for key in list(common)[:10]:
            try:
                if len(csv_data[key]) != len(h5_data[key]):
                    errors.append(
                        f"Length mismatch for '{key}': CSV={len(csv_data[key])} vs HDF5={len(h5_data[key])}"
                    )
            except Exception:
                pass

    # Cross-checks MF4 vs CSV: per-signal lengths and timebase hints
    if args.csv and args.csv.exists():
        csv_data = _load_csv(args.csv)
        header_lines = csv_data.pop("__HEADER_LINES__", [])
        if not csv_timebase_map and header_lines:
            csv_timebase_map = _parse_csv_timebase_header(header_lines)
        # Compare lengths for common signals (skip non-numeric timestamp keys)
        skip_cols = {"timestamp", "time"}
        skip_cols.update({k for k in csv_data.keys() if k.startswith("timestamp")})
        for sig, arr in csv_data.items():
            if sig in skip_cols:
                continue
            try:
                # Load from MF4 and compare
                with MDF(str(args.mf4)) as mdf2:
                    try:
                        ch = mdf2.get(sig)
                    except Exception:
                        ch = None
                    if ch is None:
                        warnings.append(f"CSV column '{sig}' not found in MF4")
                        continue
                    len_mf4 = len(ch.samples)
                    len_csv = len(arr)
                    if len_mf4 != len_csv:
                        errors.append(
                            f"Length mismatch for signal '{sig}': MF4={len_mf4} vs CSV={len_csv}"
                        )
                    # If we have CSV timebase header for this signal, compare to inferred tb
                    if sig in csv_timebase_map:
                        tb_csv = csv_timebase_map[sig].get("timebase_s")
                        tb_mf4 = _infer_timebase_seconds(ch.timestamps)
                        if tb_csv is not None and tb_mf4 is not None:
                            # relative tolerance 5%
                            denom = max(tb_csv, 1e-12)
                            if abs(tb_mf4 - tb_csv) / denom > 0.05:
                                warnings.append(
                                    f"Timebase differs for '{sig}': CSV header tb≈{tb_csv}s vs MF4≈{tb_mf4}s"
                                )
                        if args.details:
                            print(
                                f"Check: {sig}: len CSV/MF4 = {len_csv}/{len_mf4}, tb CSV/MF4 = {tb_csv}/{tb_mf4}"
                            )
                        # If CSV header mentions a timestamp source like timestampX, ensure such a column exists
                        src = csv_timebase_map[sig].get("timestamp_source")
                        if src and src != "synthetic":
                            base = str(src)
                            # Strip stride and unit annotations like [::10](trim)(ns)
                            base = base.split("[")[0]
                            base = base.replace("(ns)", "").strip()
                            if base and base not in csv_data:
                                # CSV did not include the referenced timestamp column
                                warnings.append(
                                    f"CSV missing referenced timestamp column '{base}' for signal '{sig}'"
                                )
                            elif args.details:
                                print(
                                    f"Check: {sig}: referenced timestamp column present: {base}"
                                )
            except Exception as e:
                warnings.append(f"Comparison failed for '{sig}': {e}")

    for w in warnings:
        print(f"WARNING: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
