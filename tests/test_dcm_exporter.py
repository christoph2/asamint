#!/usr/bin/env python
"""Tests for asamint.damos.dcm_exporter – dataclasses and DcmExporter methods."""
from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from asamint.damos.dcm_exporter import AxisData, DcmExporter, ParamData

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_data(value, attrs=None, dims=None, coords=None):
    """Return a minimal data-like SimpleNamespace (mimics an xarray DataArray)."""
    return SimpleNamespace(
        values=value,
        attrs=attrs or {},
        dims=dims or [],
        coords=coords or {},
    )


def _make_db_exporter(instances=None):
    """Return a DcmExporter backed by a fully mocked MSRSWDatabase."""
    db = MagicMock()
    db.session.query.return_value.all.return_value = instances or []
    return DcmExporter(db=db, h5_db=None)


def _make_sw_instance(name: str, category: str) -> MagicMock:
    inst = MagicMock()
    inst.short_name.content = name
    inst.category.content = category
    return inst


# ---------------------------------------------------------------------------
# AxisData
# ---------------------------------------------------------------------------


def test_axis_data_fields() -> None:
    a = AxisData(category="STD_AXIS", unit="rpm", converted_values=[0.0, 1.0, 2.0])
    assert a.category == "STD_AXIS"
    assert a.unit == "rpm"
    assert a.converted_values == [0.0, 1.0, 2.0]


# ---------------------------------------------------------------------------
# ParamData.__post_init__
# ---------------------------------------------------------------------------


def test_param_data_values_none() -> None:
    p = ParamData("p", "VALUE", "", "", "", None)
    assert p.converted_value == 0
    assert p.converted_values == []


def test_param_data_value_category_plain_float() -> None:
    p = ParamData("p", "VALUE", "", "", "", _mock_data(42.5))
    assert p.converted_value == 42.5
    assert p.value == 42.5


def test_param_data_value_category_numpy_scalar() -> None:
    p = ParamData("p", "VALUE", "", "", "", _mock_data(np.float64(3.14)))
    assert pytest.approx(p.converted_value, abs=1e-5) == 3.14


def test_param_data_boolean_category() -> None:
    p = ParamData("p", "BOOLEAN", "", "", "", _mock_data(1))
    assert p.converted_value == 1


def test_param_data_text_category() -> None:
    p = ParamData("p", "TEXT", "", "", "", _mock_data("hello"))
    assert p.converted_value == "hello"


def test_param_data_curve_category_stores_converted_values() -> None:
    arr = np.array([1.0, 2.0, 3.0])
    p = ParamData("p", "CURVE", "", "", "", _mock_data(arr))
    assert list(p.converted_values) == [1.0, 2.0, 3.0]


def test_param_data_map_category_stores_2d_array() -> None:
    arr = np.ones((2, 3))
    p = ParamData("p", "MAP", "", "", "", _mock_data(arr))
    assert p.converted_values.shape == (2, 3)


def test_param_data_val_blk_category() -> None:
    arr = np.array([5.0, 6.0, 7.0, 8.0])
    p = ParamData("p", "VAL_BLK", "", "", "", _mock_data(arr))
    assert list(p.converted_values) == [5.0, 6.0, 7.0, 8.0]


def test_param_data_axes_default_empty() -> None:
    p = ParamData("p", "VALUE", "", "", "", None)
    assert p.axes == []


def test_param_data_axes_provided() -> None:
    axis = AxisData("STD_AXIS", "rpm", [0.0, 1.0])
    p = ParamData("p", "CURVE", "", "", "", None, axes=[axis])
    assert len(p.axes) == 1
    assert p.axes[0].category == "STD_AXIS"


# ---------------------------------------------------------------------------
# DcmExporter._empty_params
# ---------------------------------------------------------------------------


def test_empty_params_has_all_keys() -> None:
    result = DcmExporter._empty_params()
    assert set(result.keys()) == {
        "AXIS_PTS",
        "VALUE",
        "ASCII",
        "VAL_BLK",
        "CURVE",
        "MAP",
    }


def test_empty_params_all_values_are_dicts() -> None:
    result = DcmExporter._empty_params()
    assert all(isinstance(v, dict) for v in result.values())


def test_empty_params_all_dicts_empty() -> None:
    result = DcmExporter._empty_params()
    assert all(len(v) == 0 for v in result.values())


# ---------------------------------------------------------------------------
# DcmExporter._bucket_for_category
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category,expected_bucket",
    [
        ("VALUE", "VALUE"),
        ("BOOLEAN", "VALUE"),
        ("TEXT", "VALUE"),
        ("ASCII", "ASCII"),
        ("VAL_BLK", "VAL_BLK"),
        ("STUETZSTELLENVERTEILUNG", "AXIS_PTS"),
        ("CURVE", "CURVE"),
        ("MAP", "MAP"),
        ("UNKNOWN_XYZ", None),
        ("", None),
    ],
)
def test_bucket_for_category(category: str, expected_bucket: str | None) -> None:
    assert DcmExporter._bucket_for_category(category) == expected_bucket


# ---------------------------------------------------------------------------
# DcmExporter._create_namespace
# ---------------------------------------------------------------------------


def test_create_namespace_contains_all_keys() -> None:
    ns = DcmExporter._create_namespace(DcmExporter._empty_params())
    assert {"params", "dataset", "experiment", "current_datetime"} <= set(ns.keys())


def test_create_namespace_datetime_format() -> None:
    ns = DcmExporter._create_namespace({})
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", ns["current_datetime"])


def test_create_namespace_passes_params() -> None:
    params = DcmExporter._empty_params()
    ns = DcmExporter._create_namespace(params)
    assert ns["params"] is params


# ---------------------------------------------------------------------------
# DcmExporter._normalize_category
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category,expected",
    [
        ("VALUE_ARRAY", "VAL_BLK"),
        ("AXIS_PTS", "STUETZSTELLENVERTEILUNG"),
        ("CURVE", "CURVE"),
        ("MAP", "MAP"),
        ("VALUE", "VALUE"),
        ("ASCII", "ASCII"),
    ],
)
def test_normalize_category(category: str, expected: str) -> None:
    assert DcmExporter._normalize_category(category) == expected


# ---------------------------------------------------------------------------
# DcmExporter._metadata_from_data
# ---------------------------------------------------------------------------


def test_metadata_from_data_none() -> None:
    assert DcmExporter._metadata_from_data(None) == ("", "", "")


def test_metadata_from_data_all_attrs() -> None:
    data = SimpleNamespace(
        attrs={"comment": "my note", "display_identifier": "ID1", "unit": "rpm"}
    )
    assert DcmExporter._metadata_from_data(data) == ("my note", "ID1", "rpm")


def test_metadata_from_data_partial_attrs() -> None:
    data = SimpleNamespace(attrs={"comment": "only me"})
    comment, disp, unit = DcmExporter._metadata_from_data(data)
    assert comment == "only me"
    assert disp == ""
    assert unit == ""


def test_metadata_from_data_empty_attrs() -> None:
    data = SimpleNamespace(attrs={})
    assert DcmExporter._metadata_from_data(data) == ("", "", "")


# ---------------------------------------------------------------------------
# DcmExporter._build_axes_data
# ---------------------------------------------------------------------------


def test_build_axes_data_none() -> None:
    assert DcmExporter._build_axes_data(None) == []


def test_build_axes_data_no_dims() -> None:
    data = SimpleNamespace(dims=[], coords={})
    assert DcmExporter._build_axes_data(data) == []


def test_build_axes_data_one_dim_with_coord() -> None:
    vals = np.array([0.0, 1.0, 2.0])
    coord_mock = MagicMock()
    coord_mock.values = vals
    data = SimpleNamespace(dims=["x"], coords={"x": coord_mock})
    result = DcmExporter._build_axes_data(data)
    assert len(result) == 1
    assert result[0].category == "STD_AXIS"
    assert result[0].unit == ""
    assert list(result[0].converted_values) == [0.0, 1.0, 2.0]


def test_build_axes_data_dim_not_in_coords() -> None:
    data = SimpleNamespace(dims=["x"], coords={})
    result = DcmExporter._build_axes_data(data)
    assert len(result) == 1
    assert result[0].converted_values == []


def test_build_axes_data_two_dims() -> None:
    cx = MagicMock()
    cx.values = np.array([0.0, 1.0])
    cy = MagicMock()
    cy.values = np.array([10.0, 20.0, 30.0])
    data = SimpleNamespace(dims=["x", "y"], coords={"x": cx, "y": cy})
    result = DcmExporter._build_axes_data(data)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# DcmExporter._instance_name
# ---------------------------------------------------------------------------


def test_instance_name_with_short_name() -> None:
    inst = SimpleNamespace(short_name=SimpleNamespace(content="MyParam"))
    assert DcmExporter._instance_name(inst) == "MyParam"


def test_instance_name_short_name_none() -> None:
    inst = SimpleNamespace(short_name=None)
    assert DcmExporter._instance_name(inst) is None


# ---------------------------------------------------------------------------
# DcmExporter._collect_params (mocked DB)
# ---------------------------------------------------------------------------


def test_collect_params_empty_db() -> None:
    exporter = _make_db_exporter([])
    params = exporter._collect_params()
    assert params == DcmExporter._empty_params()


def test_collect_params_value_instance() -> None:
    exporter = _make_db_exporter([_make_sw_instance("P1", "VALUE")])
    params = exporter._collect_params()
    assert "P1" in params["VALUE"]


def test_collect_params_curve_instance() -> None:
    exporter = _make_db_exporter([_make_sw_instance("C1", "CURVE")])
    params = exporter._collect_params()
    assert "C1" in params["CURVE"]


def test_collect_params_axis_pts_normalized() -> None:
    exporter = _make_db_exporter([_make_sw_instance("A1", "AXIS_PTS")])
    params = exporter._collect_params()
    assert "A1" in params["AXIS_PTS"]


def test_collect_params_value_array_normalized() -> None:
    exporter = _make_db_exporter([_make_sw_instance("V1", "VALUE_ARRAY")])
    params = exporter._collect_params()
    assert "V1" in params["VAL_BLK"]


def test_collect_params_unknown_category_skipped() -> None:
    exporter = _make_db_exporter([_make_sw_instance("U1", "UNKNOWN_CAT")])
    params = exporter._collect_params()
    total = sum(len(v) for v in params.values())
    assert total == 0


def test_collect_params_missing_short_name_skipped() -> None:
    inst = MagicMock()
    inst.short_name = None
    exporter = _make_db_exporter([inst])
    params = exporter._collect_params()
    total = sum(len(v) for v in params.values())
    assert total == 0


def test_collect_params_multiple_instances() -> None:
    instances = [
        _make_sw_instance("P1", "VALUE"),
        _make_sw_instance("P2", "VALUE"),
        _make_sw_instance("C1", "CURVE"),
        _make_sw_instance("M1", "MAP"),
    ]
    exporter = _make_db_exporter(instances)
    params = exporter._collect_params()
    assert len(params["VALUE"]) == 2
    assert len(params["CURVE"]) == 1
    assert len(params["MAP"]) == 1


# ---------------------------------------------------------------------------
# DcmExporter._render_template + export (integration via mocked DB)
# ---------------------------------------------------------------------------


def _minimal_namespace() -> dict:
    ns = DcmExporter._create_namespace(DcmExporter._empty_params())
    ns["dataset"] = {}
    ns["experiment"] = {}
    return ns


def test_render_template_success(tmp_path) -> None:
    exporter = _make_db_exporter()
    out = tmp_path / "test.dcm"
    result = exporter._render_template(str(out), _minimal_namespace())
    assert result is True
    assert out.exists()


def test_render_template_produces_valid_dcm(tmp_path) -> None:
    exporter = _make_db_exporter()
    out = tmp_path / "test.dcm"
    exporter._render_template(str(out), _minimal_namespace())
    content = out.read_text(encoding="latin-1")
    assert "KONSERVIERUNG_FORMAT 2.0" in content


def test_render_template_datetime_in_output(tmp_path) -> None:
    exporter = _make_db_exporter()
    out = tmp_path / "test.dcm"
    exporter._render_template(str(out), _minimal_namespace())
    content = out.read_text(encoding="latin-1")
    assert re.search(r"\d{4}-\d{2}-\d{2}", content)


def test_render_template_bad_path_returns_false(tmp_path) -> None:
    exporter = _make_db_exporter()
    result = exporter._render_template("/nonexistent/path/x.dcm", _minimal_namespace())
    assert result is False


def test_export_creates_output_file(tmp_path) -> None:
    exporter = _make_db_exporter([])
    out = tmp_path / "out.dcm"
    assert exporter.export(str(out)) is True
    assert out.exists()


def test_export_with_value_param_renders_festwert(tmp_path) -> None:
    exporter = _make_db_exporter([_make_sw_instance("Gain", "VALUE")])
    out = tmp_path / "out.dcm"
    exporter.export(str(out))
    content = out.read_text(encoding="latin-1")
    assert "FESTWERT" in content
    assert "Gain" in content


def test_export_with_ascii_param_renders_textstring(tmp_path) -> None:
    exporter = _make_db_exporter([_make_sw_instance("Label", "ASCII")])
    out = tmp_path / "out.dcm"
    exporter.export(str(out))
    content = out.read_text(encoding="latin-1")
    assert "TEXTSTRING" in content
    assert "Label" in content
