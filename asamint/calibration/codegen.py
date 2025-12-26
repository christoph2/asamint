#!/usr/bin/env python
"""
Mako-based C code generator for calibration logs.

This module renders C headers (structs/arrays) from the JSON calibration log
produced by CalibrationData.load_hex(). It aims to be robust across slightly
varying JSON formats observed in examples.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from asamint.utils.templates import do_template


@dataclass
class CArray:
    name: str
    c_name: str
    dims: list[int]  # e.g., [len_x] or [rows, cols]
    c_type: str = "double"
    comment: str | None = None


@dataclass
class CString:
    name: str
    c_name: str
    length: int  # not including the terminating NUL we will add in declaration
    comment: str | None = None


@dataclass
class CValue:
    name: str
    c_name: str
    c_type: str = "double"
    comment: str | None = None


def sanitize_identifier(name: str) -> str:
    """Convert arbitrary characteristic name to a valid C identifier.
    - Replace non [A-Za-z0-9_] with '_'
    - If it starts with a digit, prefix with '_'
    - Collapse multiple underscores
    """
    s = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if re.match(r"^[0-9]", s):
        s = f"_{s}"
    s = re.sub(r"_+", "_", s)
    return s


def _first_present(d: dict[str, Any], keys: list[str], default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _len_of_values(obj: dict[str, Any]) -> int:
    """Return length of values list for an object supporting different JSON shapes."""
    vals = _first_present(obj, ["phys", "converted_values", "raw", "raw_values"], [])
    if isinstance(vals, list):
        return len(vals)
    return 0


def _axes_from_log(log: dict[str, Any]) -> dict[str, int]:
    """Build a mapping of axis name -> length from AXIS_PTS section in the log."""
    axis_section = log.get("AXIS_PTS") or {}
    lens: dict[str, int] = {}
    for name, obj in axis_section.items():
        lens[name] = _len_of_values(obj)
    return lens


def _dims_for_nd(obj: dict[str, Any], axis_lengths: dict[str, int]) -> list[int]:
    """Return the dimension list for CURVE/MAP/CUBOID-like objects.
    - If shape present (VAL_BLK), use it directly.
    - Otherwise use axes references to determine per-axis lengths.
    - Fallback to a single-dim length from values if no axes are available.
    """
    # Explicit shape
    if "shape" in obj and isinstance(obj["shape"], list) and obj["shape"]:
        return list(obj["shape"])

    axes = obj.get("axes") or []
    dims: list[int] = []
    for ax in axes:
        ref = _first_present(
            ax, ["axis_pts_ref", "curve_axis_ref"]
        )  # name in AXIS_PTS or curve axis
        if isinstance(ref, str) and ref in axis_lengths:
            dims.append(axis_lengths[ref])
        else:
            # Try to infer from embedded axis values
            ln = _len_of_values(ax)
            if ln:
                dims.append(ln)
    if dims:
        return dims

    # Fallback to flat length
    ln = _len_of_values(obj)
    return [ln] if ln else []


def parse_calibration_log(json_path: Path) -> dict[str, Any]:
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def build_model_from_log(log: dict[str, Any]) -> dict[str, Any]:
    """Transform raw log JSON into simple structures consumable by the Mako template."""
    axis_lengths = _axes_from_log(log)

    # Collect per-category declarations
    values: list[CValue] = []
    asciis: list[CString] = []
    arrays_by_cat: dict[str, list[CArray]] = (
        {  # for AXIS_PTS, CURVE, MAP, CUBOID, CUBE_4, CUBE_5, VAL_BLK
            "AXIS_PTS": [],
            "CURVE": [],
            "MAP": [],
            "CUBOID": [],
            "CUBE_4": [],
            "CUBE_5": [],
            "VAL_BLK": [],
        }
    )

    # VALUEs
    for name, obj in (log.get("VALUE") or {}).items():
        values.append(
            CValue(
                name=name,
                c_name=sanitize_identifier(name),
                c_type="double",  # Without datatype in log, use a wide type
                comment=obj.get("comment") or None,
            )
        )

    # ASCII strings
    for name, obj in (log.get("ASCII") or {}).items():
        length = int(obj.get("length") or 0)
        asciis.append(
            CString(
                name=name,
                c_name=sanitize_identifier(name),
                length=length,
                comment=obj.get("comment") or None,
            )
        )

    # Arrays by category
    for cat in ["AXIS_PTS", "CURVE", "MAP", "CUBOID", "CUBE_4", "CUBE_5", "VAL_BLK"]:
        section = log.get(cat) or {}
        for name, obj in section.items():
            dims = _dims_for_nd(obj, axis_lengths)
            if not dims:
                # Skip empty
                continue
            arrays_by_cat[cat].append(
                CArray(
                    name=name,
                    c_name=sanitize_identifier(name),
                    dims=dims,
                    c_type="double",
                    comment=obj.get("comment") or None,
                )
            )

    return {
        "values": values,
        "asciis": asciis,
        "arrays_by_cat": arrays_by_cat,
    }


def default_template_path() -> Path:
    return (
        Path(__file__).resolve().parent.parent
        / "data"
        / "templates"
        / "c_structs.h.mako"
    )


def render_header(
    namespace: dict[str, Any],
    template_path: Path | None = None,
    encoding: str = "utf-8",
) -> str:
    tmpl = str(template_path or default_template_path())
    return do_template(tmpl, namespace=namespace, encoding=encoding)


def generate_c_structs_from_log(
    asam_mc: Any,
    log_path: Path | None = None,
    out_path: Path | None = None,
    template_path: Path | None = None,
    header_guard: str | None = None,
) -> Path:
    """Generate a C header with structs/arrays from a calibration JSON log.

    Args:
        asam_mc: AsamMC instance used for configuration (naming and directories).
        log_path: Path to a calibration log JSON; if None, try to pick the newest from logs/.
        out_path: Output header path; if None, create under asam_mc.sub_dir("code").
        template_path: Optional path to mako template to override default.
        header_guard: Optional header guard symbol; if None, derive from output name.

    Returns:
        Path to the generated header file.
    """
    logs_dir = Path("logs") if log_path is None else Path(log_path).parent

    if log_path is None:
        # Choose latest first_steps_*.json in logs/
        candidates = sorted(
            Path("logs").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        if not candidates:
            raise FileNotFoundError(
                "No calibration log JSON found in 'logs' directory."
            )
        log_path = candidates[0]

    log = parse_calibration_log(Path(log_path))
    model = build_model_from_log(log)

    # Build namespace for template
    out_name = (
        out_path.name if out_path else asam_mc.generate_filename(".h", extra="cstructs")
    )
    if out_name.endswith(".h"):
        base_symbol = out_name[:-2]
    else:
        base_symbol = out_name
    guard = header_guard or sanitize_identifier(base_symbol.upper()) + "_H"

    namespace = {
        "project": getattr(asam_mc, "shortname", "ASAMINT"),
        "generator": "asamint.calibration.codegen",
        "values": model["values"],
        "asciis": model["asciis"],
        "arrays_by_cat": model["arrays_by_cat"],
        "header_guard": guard,
    }

    rendered = render_header(namespace, template_path)

    # Determine output path
    if out_path is None:
        code_dir = (
            asam_mc.sub_dir("code") if hasattr(asam_mc, "sub_dir") else Path("code")
        )
        code_dir.mkdir(exist_ok=True)
        out_path = code_dir / out_name

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    if hasattr(asam_mc, "logger"):
        asam_mc.logger.info(f"Generated C header: {out_path}")

    return out_path
