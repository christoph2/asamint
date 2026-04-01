#!/usr/bin/env python
"""Tests for asamint.calibration.codegen – pure functions and integration."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from asamint.calibration.codegen import (
    CArray,
    CString,
    CValue,
    _axes_from_log,
    _dims_for_nd,
    _first_present,
    _len_of_values,
    build_model_from_log,
    generate_c_structs_from_log,
    render_header,
    sanitize_identifier,
)

# ---------------------------------------------------------------------------
# sanitize_identifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("ValidName", "ValidName"),
        ("also_valid_123", "also_valid_123"),
        ("has.dot", "has_dot"),
        ("has-dash", "has_dash"),
        ("has space", "has_space"),
        ("123startsDigit", "_123startsDigit"),
        ("a__b___c", "a_b_c"),  # collapse multiple underscores
        ("", ""),
        (".", "_"),
        ("!@#", "_"),
        ("a.b.c", "a_b_c"),
    ],
)
def test_sanitize_identifier(name: str, expected: str) -> None:
    assert sanitize_identifier(name) == expected


# ---------------------------------------------------------------------------
# _first_present
# ---------------------------------------------------------------------------


def test_first_present_returns_first_matching_key() -> None:
    assert _first_present({"a": 1, "b": 2}, ["a", "b"]) == 1


def test_first_present_skips_none_values() -> None:
    assert _first_present({"a": None, "b": 2}, ["a", "b"]) == 2


def test_first_present_returns_default_when_missing() -> None:
    assert _first_present({"c": 3}, ["a", "b"]) is None
    assert _first_present({"c": 3}, ["a", "b"], default=99) == 99


def test_first_present_returns_falsy_but_non_none() -> None:
    assert _first_present({"a": 0}, ["a"]) == 0
    assert _first_present({"a": []}, ["a"]) == []


# ---------------------------------------------------------------------------
# _len_of_values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "obj, expected",
    [
        ({"phys": [1.0, 2.0, 3.0]}, 3),
        ({"converted_values": [1, 2]}, 2),
        ({"raw": [10, 20, 30, 40]}, 4),
        ({"raw_values": [0]}, 1),
        ({}, 0),
        ({"phys": None}, 0),
        ({"phys": 42.0}, 0),  # non-list value → 0
    ],
)
def test_len_of_values(obj: dict, expected: int) -> None:
    assert _len_of_values(obj) == expected


def test_len_of_values_prefers_phys_over_raw() -> None:
    # phys listed first in _first_present keys
    assert _len_of_values({"phys": [1, 2], "raw": [1, 2, 3]}) == 2


# ---------------------------------------------------------------------------
# _axes_from_log
# ---------------------------------------------------------------------------


def test_axes_from_log_empty() -> None:
    assert _axes_from_log({}) == {}


def test_axes_from_log_no_axis_pts_key() -> None:
    assert _axes_from_log({"VALUE": {"x": {}}}) == {}


def test_axes_from_log_collects_lengths() -> None:
    log = {
        "AXIS_PTS": {
            "ax_speed": {"phys": [0.0, 10.0, 20.0, 30.0]},
            "ax_temp": {"phys": [20.0, 40.0]},
        }
    }
    result = _axes_from_log(log)
    assert result == {"ax_speed": 4, "ax_temp": 2}


# ---------------------------------------------------------------------------
# _dims_for_nd
# ---------------------------------------------------------------------------


def test_dims_for_nd_explicit_shape() -> None:
    obj = {"shape": [3, 4], "phys": [0.0] * 12}
    assert _dims_for_nd(obj, {}) == [3, 4]


def test_dims_for_nd_axis_pts_ref() -> None:
    obj = {"axes": [{"axis_pts_ref": "ax_x"}, {"axis_pts_ref": "ax_y"}]}
    axis_lengths = {"ax_x": 5, "ax_y": 3}
    assert _dims_for_nd(obj, axis_lengths) == [5, 3]


def test_dims_for_nd_curve_axis_ref() -> None:
    obj = {"axes": [{"curve_axis_ref": "ax_ref"}]}
    axis_lengths = {"ax_ref": 7}
    assert _dims_for_nd(obj, axis_lengths) == [7]


def test_dims_for_nd_embedded_axis_values() -> None:
    obj = {"axes": [{"phys": [0.0, 1.0, 2.0]}]}
    assert _dims_for_nd(obj, {}) == [3]


def test_dims_for_nd_fallback_to_flat_values() -> None:
    obj = {"phys": [1.0, 2.0, 3.0, 4.0, 5.0]}
    assert _dims_for_nd(obj, {}) == [5]


def test_dims_for_nd_no_info_returns_empty() -> None:
    assert _dims_for_nd({}, {}) == []


def test_dims_for_nd_shape_takes_priority_over_axes() -> None:
    obj = {
        "shape": [2, 3],
        "axes": [{"phys": [0.0, 1.0, 2.0, 3.0, 4.0]}],
    }
    assert _dims_for_nd(obj, {}) == [2, 3]


# ---------------------------------------------------------------------------
# build_model_from_log
# ---------------------------------------------------------------------------


def _make_log(**sections: dict) -> dict:
    return sections


def test_build_model_from_log_empty() -> None:
    model = build_model_from_log({})
    assert model["values"] == []
    assert model["asciis"] == []
    for cat_list in model["arrays_by_cat"].values():
        assert cat_list == []


def test_build_model_from_log_values() -> None:
    log = {
        "VALUE": {
            "EngineSpeed": {"comment": "rpm"},
            "Threshold": {},
        }
    }
    model = build_model_from_log(log)
    names = {v.name for v in model["values"]}
    assert names == {"EngineSpeed", "Threshold"}
    speed = next(v for v in model["values"] if v.name == "EngineSpeed")
    assert speed.comment == "rpm"
    assert speed.c_type == "double"


def test_build_model_from_log_ascii() -> None:
    log = {
        "ASCII": {
            "SerialNo": {"length": 16, "comment": "serial"},
        }
    }
    model = build_model_from_log(log)
    assert len(model["asciis"]) == 1
    s = model["asciis"][0]
    assert s.name == "SerialNo"
    assert s.length == 16
    assert s.comment == "serial"


def test_build_model_from_log_axis_pts() -> None:
    log = {
        "AXIS_PTS": {
            "ax_rpm": {"phys": [0.0, 500.0, 1000.0, 2000.0]},
        }
    }
    model = build_model_from_log(log)
    assert len(model["arrays_by_cat"]["AXIS_PTS"]) == 1
    a = model["arrays_by_cat"]["AXIS_PTS"][0]
    assert a.name == "ax_rpm"
    assert a.dims == [4]


def test_build_model_from_log_curve_with_axis_ref() -> None:
    log = {
        "AXIS_PTS": {
            "ax_x": {"phys": list(range(5))},
        },
        "CURVE": {
            "MyCurve": {
                "axes": [{"axis_pts_ref": "ax_x"}],
                "phys": [0.0, 1.0, 2.0, 3.0, 4.0],
            }
        },
    }
    model = build_model_from_log(log)
    curves = model["arrays_by_cat"]["CURVE"]
    assert len(curves) == 1
    assert curves[0].dims == [5]


def test_build_model_from_log_map_2d() -> None:
    log = {
        "MAP": {
            "FuelMap": {
                "axes": [
                    {"phys": [0.0, 1.0, 2.0]},
                    {"phys": [0.0, 1.0]},
                ],
            }
        }
    }
    model = build_model_from_log(log)
    maps = model["arrays_by_cat"]["MAP"]
    assert len(maps) == 1
    assert maps[0].dims == [3, 2]


def test_build_model_from_log_val_blk_explicit_shape() -> None:
    log = {
        "VAL_BLK": {
            "LookupTable": {"shape": [4, 6], "phys": [0.0] * 24},
        }
    }
    model = build_model_from_log(log)
    blks = model["arrays_by_cat"]["VAL_BLK"]
    assert len(blks) == 1
    assert blks[0].dims == [4, 6]


def test_build_model_from_log_skips_empty_dims() -> None:
    """Objects with no resolvable dims must be excluded (not crash)."""
    log = {"CURVE": {"GhostCurve": {}}}
    model = build_model_from_log(log)
    assert model["arrays_by_cat"]["CURVE"] == []


def test_build_model_from_log_sanitizes_names() -> None:
    log = {"VALUE": {"123.bad-name": {}}}
    model = build_model_from_log(log)
    assert model["values"][0].c_name == "_123_bad_name"


# ---------------------------------------------------------------------------
# render_header – end-to-end via real Mako template
# ---------------------------------------------------------------------------


def _minimal_namespace(**overrides) -> dict:
    arrays_by_cat = {
        "AXIS_PTS": [],
        "CURVE": [],
        "MAP": [],
        "CUBOID": [],
        "CUBE_4": [],
        "CUBE_5": [],
        "VAL_BLK": [],
    }
    ns = {
        "project": "TEST",
        "generator": "test",
        "values": [],
        "asciis": [],
        "arrays_by_cat": arrays_by_cat,
        "header_guard": "TEST_H",
    }
    ns.update(overrides)
    return ns


def test_render_header_contains_guard() -> None:
    result = render_header(_minimal_namespace(header_guard="MY_CAL_H"))
    assert "#ifndef MY_CAL_H" in result
    assert "#define MY_CAL_H" in result
    assert "#endif" in result


def test_render_header_empty_log_no_structs() -> None:
    result = render_header(_minimal_namespace())
    # The master Calibration_t struct is always present; category structs must be absent
    assert "VALUE_t" not in result
    assert "AXIS_PTS_t" not in result
    assert "CURVE_t" not in result
    assert "Calibration_t" in result


def test_render_header_value_struct() -> None:
    ns = _minimal_namespace(
        values=[
            CValue(
                name="EngineSpeed", c_name="EngineSpeed", c_type="double", comment="rpm"
            )
        ]
    )
    result = render_header(ns)
    assert "double EngineSpeed;" in result
    assert "VALUE_t" in result


def test_render_header_ascii_struct() -> None:
    ns = _minimal_namespace(
        asciis=[CString(name="Serial", c_name="Serial", length=15, comment=None)]
    )
    result = render_header(ns)
    assert "char Serial[16];" in result  # length + 1 for NUL
    assert "ASCII_t" in result


def test_render_header_axis_pts_1d() -> None:
    ns = _minimal_namespace()
    ns["arrays_by_cat"]["AXIS_PTS"] = [
        CArray(name="ax_rpm", c_name="ax_rpm", dims=[8], c_type="double")
    ]
    result = render_header(ns)
    assert "double ax_rpm[8];" in result
    assert "AXIS_PTS_t" in result


def test_render_header_curve_1d() -> None:
    ns = _minimal_namespace()
    ns["arrays_by_cat"]["CURVE"] = [
        CArray(name="MyCurve", c_name="MyCurve", dims=[5], c_type="double")
    ]
    result = render_header(ns)
    assert "double MyCurve[5];" in result
    assert "CURVE_t" in result


def test_render_header_map_2d() -> None:
    ns = _minimal_namespace()
    ns["arrays_by_cat"]["MAP"] = [
        CArray(name="FuelMap", c_name="FuelMap", dims=[3, 4], c_type="double")
    ]
    result = render_header(ns)
    assert "double FuelMap[3][4];" in result
    assert "MAP_t" in result


def test_render_header_val_blk_multidim() -> None:
    ns = _minimal_namespace()
    ns["arrays_by_cat"]["VAL_BLK"] = [
        CArray(name="BigBlock", c_name="BigBlock", dims=[4, 6], c_type="double")
    ]
    result = render_header(ns)
    assert "double BigBlock[4][6];" in result
    assert "VAL_BLK_t" in result


def test_render_header_comment_included() -> None:
    ns = _minimal_namespace(
        values=[CValue(name="X", c_name="X", c_type="double", comment="important")]
    )
    result = render_header(ns)
    assert "important" in result


def test_render_header_no_comment_no_dash() -> None:
    ns = _minimal_namespace(
        values=[CValue(name="X", c_name="X", c_type="double", comment=None)]
    )
    result = render_header(ns)
    assert " - " not in result


# ---------------------------------------------------------------------------
# generate_c_structs_from_log – integration with tmp_path
# ---------------------------------------------------------------------------


def _stub_mc(tmp_path: Path, shortname: str = "DEMO") -> SimpleNamespace:
    code_dir = tmp_path / "code"
    code_dir.mkdir(exist_ok=True)
    return SimpleNamespace(
        shortname=shortname,
        generate_filename=lambda ext, extra="": f"{shortname}_{extra}{ext}",
        sub_dir=lambda _name: code_dir,
        logger=SimpleNamespace(info=lambda msg: None),
    )


def _write_log(path: Path, content: dict) -> Path:
    log_file = path / "cal.json"
    log_file.write_text(json.dumps(content), encoding="utf-8")
    return log_file


def test_generate_c_structs_creates_file(tmp_path: Path) -> None:
    log_path = _write_log(
        tmp_path,
        {
            "VALUE": {"Speed": {"comment": "rpm"}},
            "AXIS_PTS": {"ax": {"phys": [0.0, 1.0, 2.0]}},
        },
    )
    mc = _stub_mc(tmp_path)
    result = generate_c_structs_from_log(mc, log_path=log_path)
    assert result.exists()
    content = result.read_text(encoding="utf-8")
    assert "#ifndef" in content
    assert "double Speed;" in content


def test_generate_c_structs_custom_out_path(tmp_path: Path) -> None:
    log_path = _write_log(tmp_path, {"VALUE": {"V": {}}})
    mc = _stub_mc(tmp_path)
    out = tmp_path / "my_custom.h"
    result = generate_c_structs_from_log(mc, log_path=log_path, out_path=out)
    assert result == out
    assert out.exists()


def test_generate_c_structs_custom_header_guard(tmp_path: Path) -> None:
    log_path = _write_log(tmp_path, {"VALUE": {"V": {}}})
    mc = _stub_mc(tmp_path)
    out = tmp_path / "out.h"
    generate_c_structs_from_log(
        mc, log_path=log_path, out_path=out, header_guard="CUSTOM_GUARD_H"
    )
    content = out.read_text(encoding="utf-8")
    assert "#ifndef CUSTOM_GUARD_H" in content


def test_generate_c_structs_no_log_raises(tmp_path: Path) -> None:
    mc = _stub_mc(tmp_path)
    # No logs/ directory with JSON → FileNotFoundError
    import os

    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        with pytest.raises(FileNotFoundError, match="No calibration log JSON"):
            generate_c_structs_from_log(mc, log_path=None)
    finally:
        os.chdir(original)
