#!/usr/bin/env python
"""Tests for asamint.cdf.exporter.dcm (Exporter) and cdf_exporter (CDFExporter)."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from lxml import etree

from asamint.cdf.exporter.cdf_exporter import CDFExporter
from asamint.cdf.exporter.dcm import Exporter, array_elements
from asamint.msrsw.elements import VF, VT, ArraySize, V

# ---------------------------------------------------------------------------
# Helpers – DB-free subclass of Exporter
# ---------------------------------------------------------------------------


class _E(Exporter):
    """Exporter subclass that skips DB __init__ for unit testing."""

    def __init__(self) -> None:  # noqa: D107
        pass  # skip super().__init__()


@pytest.fixture
def exporter() -> _E:
    return _E()


def _ns(**kw):
    return SimpleNamespace(**kw)


def _inst(
    name="Param1",
    long_name="",
    display_name="",
    feature_ref=None,
    category="VALUE",
    values=None,
    axes=None,
    unit="rpm",
):
    """Build a minimal instance SimpleNamespace matching Exporter's attribute access."""
    if values is None:
        values = _ns(
            unit_display_name=_ns(phys=unit), values_phys=[], array_size=ArraySize(())
        )
    return _ns(
        short_name=name,
        long_name=long_name,
        display_name=display_name,
        feature_ref=feature_ref,
        category=category,
        values=values,
        axes=axes or [],
    )


def _vc(phys_values, dims=(3,)):
    """Build a value_container SimpleNamespace."""
    return _ns(
        values_phys=[V(phys=v) for v in phys_values],
        unit_display_name=_ns(phys="rpm"),
        array_size=ArraySize(dimensions=dims),
    )


# ---------------------------------------------------------------------------
# array_elements
# ---------------------------------------------------------------------------


def test_array_elements_1d() -> None:
    assert array_elements(ArraySize(dimensions=(5,))) == 5


def test_array_elements_2d() -> None:
    assert array_elements(ArraySize(dimensions=(3, 4))) == 12


def test_array_elements_3d() -> None:
    assert array_elements(ArraySize(dimensions=(2, 3, 4))) == 24


def test_array_elements_single() -> None:
    assert array_elements(ArraySize(dimensions=(1,))) == 1


# ---------------------------------------------------------------------------
# Exporter._curve_type_name
# ---------------------------------------------------------------------------


def test_curve_type_name_com_axis() -> None:
    assert Exporter._curve_type_name("COM_AXIS") == "GRUPPENKENNLINIE"


def test_curve_type_name_fix_axis() -> None:
    assert Exporter._curve_type_name("FIX_AXIS") == "FESTKENNLINIE"


def test_curve_type_name_std_axis() -> None:
    assert Exporter._curve_type_name("STD_AXIS") == "KENNLINIE"


def test_curve_type_name_unknown_defaults_to_kennlinie() -> None:
    assert Exporter._curve_type_name("RES_AXIS") == "KENNLINIE"


# ---------------------------------------------------------------------------
# Exporter.on_header
# ---------------------------------------------------------------------------


def test_on_header_prints_format_line(exporter: _E, capsys) -> None:
    exporter.on_header("proj", "a2l.a2l", "fw.hex", [], False)
    out = capsys.readouterr().out
    assert "KONSERVIERUNG_FORMAT 2.0" in out


# ---------------------------------------------------------------------------
# Exporter.value_header
# ---------------------------------------------------------------------------


def test_value_header_name_only(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERT", _inst("MyParam"))
    out = capsys.readouterr().out
    assert "FESTWERT MyParam" in out


def test_value_header_with_size_x(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERTEBLOCK", _inst("BLK"), size_x=8)
    out = capsys.readouterr().out
    assert "FESTWERTEBLOCK BLK 8" in out


def test_value_header_with_size_x_and_y(exporter: _E, capsys) -> None:
    exporter.value_header("KENNFELD", _inst("MAP"), size_x=4, size_y=3)
    out = capsys.readouterr().out
    assert "KENNFELD MAP 4 3" in out


def test_value_header_prints_comment(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERT", _inst("P", long_name="My comment"))
    out = capsys.readouterr().out
    assert 'LANGNAME "My comment"' in out


def test_value_header_no_comment_no_langname(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERT", _inst("P", long_name=""))
    out = capsys.readouterr().out
    assert "LANGNAME" not in out


def test_value_header_prints_display_name(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERT", _inst("P", display_name="P_DISP"))
    out = capsys.readouterr().out
    assert 'DISPLAYNAME "P_DISP"' in out


def test_value_header_prints_unit(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERT", _inst("P", unit="Nm"))
    out = capsys.readouterr().out
    assert 'EINHEIT_W "Nm"' in out


def test_value_header_prints_funktion(exporter: _E, capsys) -> None:
    exporter.value_header("FESTWERT", _inst("P", feature_ref="FuncA"))
    out = capsys.readouterr().out
    assert "FUNKTION FuncA" in out


# ---------------------------------------------------------------------------
# Exporter._emit_rows
# ---------------------------------------------------------------------------


def test_emit_rows_single_row(exporter: _E, capsys) -> None:
    exporter._emit_rows("WERT", [1.0, 2.0])
    out = capsys.readouterr().out
    assert "WERT" in out
    assert "1.000" in out


def test_emit_rows_slices_at_6(exporter: _E, capsys) -> None:
    values = [float(i) for i in range(13)]
    exporter._emit_rows("WERT", values)
    out = capsys.readouterr().out
    # 13 values → 3 lines (6+6+1)
    assert out.count("WERT") == 3


# ---------------------------------------------------------------------------
# Exporter._emit_scalar
# ---------------------------------------------------------------------------


def test_emit_scalar_decimal(exporter: _E, capsys) -> None:
    vc = _ns(values_phys=[V(phys=Decimal("3.14"))])
    exporter._emit_scalar(
        _inst(values=_ns(unit_display_name=_ns(phys=""))), "VALUE", vc
    )
    out = capsys.readouterr().out
    assert "WERT 3.14" in out
    assert "END" in out


def test_emit_scalar_boolean_true(exporter: _E, capsys) -> None:
    vc = _ns(values_phys=[V(phys="true")])
    exporter._emit_scalar(
        _inst(values=_ns(unit_display_name=_ns(phys=""))), "BOOLEAN", vc
    )
    out = capsys.readouterr().out
    assert "WERT 1" in out


def test_emit_scalar_boolean_false(exporter: _E, capsys) -> None:
    vc = _ns(values_phys=[V(phys="false")])
    exporter._emit_scalar(
        _inst(values=_ns(unit_display_name=_ns(phys=""))), "BOOLEAN", vc
    )
    out = capsys.readouterr().out
    assert "WERT 0" in out


def test_emit_scalar_text(exporter: _E, capsys) -> None:
    vc = _ns(values_phys=[VT(phys="hello")])
    exporter._emit_scalar(
        _inst(values=_ns(unit_display_name=_ns(phys=""))), "VALUE", vc
    )
    out = capsys.readouterr().out
    assert 'TEXT "hello"' in out


def test_emit_scalar_zero_value_no_wert(exporter: _E, capsys) -> None:
    vc = _ns(values_phys=[V(phys=0)])
    exporter._emit_scalar(
        _inst(values=_ns(unit_display_name=_ns(phys=""))), "VALUE", vc
    )
    out = capsys.readouterr().out
    # zero is falsy → no "  WERT …" value line, but "END" is printed
    assert "END" in out
    assert "  WERT" not in out  # indented WERT lines start with two spaces


# ---------------------------------------------------------------------------
# Exporter._emit_axis_distribution
# ---------------------------------------------------------------------------


def test_emit_axis_distribution(exporter: _E, capsys) -> None:
    vc = _vc([0.0, 1.0, 2.0], dims=(3,))
    exporter._emit_axis_distribution(_inst(values=vc), vc)
    out = capsys.readouterr().out
    assert "STUETZSTELLENVERTEILUNG" in out
    assert "ST/X" in out
    assert "END" in out


# ---------------------------------------------------------------------------
# Exporter._emit_value_block
# ---------------------------------------------------------------------------


def test_emit_value_block(exporter: _E, capsys) -> None:
    vc = _vc([1.0, 2.0, 3.0, 4.0], dims=(4,))
    exporter._emit_value_block(_inst(values=vc), vc)
    out = capsys.readouterr().out
    assert "FESTWERTEBLOCK" in out
    assert "WERT" in out
    assert "END" in out


# ---------------------------------------------------------------------------
# Exporter._emit_curve
# ---------------------------------------------------------------------------


def test_emit_curve_std_axis(exporter: _E, capsys) -> None:
    vc = _vc([10.0, 20.0, 30.0], dims=(3,))
    axis = _ns(
        category="STD_AXIS",
        values_phys=[V(phys=float(i)) for i in range(3)],
    )
    exporter._emit_curve(_inst(values=vc), vc, [axis])
    out = capsys.readouterr().out
    assert "KENNLINIE" in out
    assert "ST/X" in out
    assert "WERT" in out
    assert "END" in out


def test_emit_curve_com_axis(exporter: _E, capsys) -> None:
    vc = _vc([1.0, 2.0], dims=(2,))
    axis = _ns(
        category="COM_AXIS",
        instance_ref=_ns(name="SharedAxis"),
        values_phys=[],
    )
    exporter._emit_curve(_inst(values=vc), vc, [axis])
    out = capsys.readouterr().out
    assert "GRUPPENKENNLINIE" in out
    assert "*SSTX SharedAxis" in out


def test_emit_curve_fix_axis(exporter: _E, capsys) -> None:
    vc = _vc([5.0, 6.0], dims=(2,))
    axis = _ns(
        category="FIX_AXIS",
        values_phys=[V(phys=0.0), V(phys=1.0)],
    )
    exporter._emit_curve(_inst(values=vc), vc, [axis])
    out = capsys.readouterr().out
    assert "FESTKENNLINIE" in out


# ---------------------------------------------------------------------------
# Exporter.on_instance – category dispatch
# ---------------------------------------------------------------------------


def test_on_instance_value_category(exporter: _E, capsys) -> None:
    vc = _ns(values_phys=[V(phys=Decimal("7.0"))], unit_display_name=_ns(phys=""))
    inst = _inst(category="VALUE", values=vc)
    exporter.on_instance(inst)
    out = capsys.readouterr().out
    assert "FESTWERT" in out


def test_on_instance_com_axis_category(exporter: _E, capsys) -> None:
    vc = _vc([1.0, 2.0], dims=(2,))
    inst = _inst(category="COM_AXIS", values=vc)
    exporter.on_instance(inst)
    out = capsys.readouterr().out
    assert "STUETZSTELLENVERTEILUNG" in out


def test_on_instance_val_blk_category(exporter: _E, capsys) -> None:
    vc = _vc([1.0, 2.0, 3.0], dims=(3,))
    inst = _inst(category="VAL_BLK", values=vc)
    exporter.on_instance(inst)
    out = capsys.readouterr().out
    assert "FESTWERTEBLOCK" in out


def test_on_instance_skipped_categories(exporter: _E, capsys) -> None:
    for cat in ("CURVE_AXIS", "RES_AXIS", "MAP"):
        exporter.on_instance(_inst(category=cat))
    out = capsys.readouterr().out
    assert out == ""


def test_on_instance_unknown_category_prints_warning(exporter: _E, capsys) -> None:
    exporter.on_instance(_inst(category="WEIRD_CAT", values=_ns(values_phys=[])))
    out = capsys.readouterr().out
    assert "CATEGORY!?" in out


def test_on_instance_curve_category(exporter: _E, capsys) -> None:
    vc = _vc([1.0, 2.0], dims=(2,))
    axis = _ns(category="STD_AXIS", values_phys=[V(phys=0.0), V(phys=1.0)])
    inst = _inst(category="CURVE", values=vc, axes=[axis])
    exporter.on_instance(inst)
    out = capsys.readouterr().out
    assert "KENNLINIE" in out


# ---------------------------------------------------------------------------
# CDFExporter._format_tag
# ---------------------------------------------------------------------------


def _make_cdf_exporter(variant_coding=False) -> CDFExporter:
    db = MagicMock()
    return CDFExporter(db=db, variant_coding=variant_coding)


def test_format_tag_known_override() -> None:
    exp = _make_cdf_exporter()
    assert exp._format_tag("ShortName") == "SHORT-NAME"
    assert exp._format_tag("SwInstance") == "SW-INSTANCE"
    assert exp._format_tag("SwValueCont") == "SW-VALUE-CONT"


def test_format_tag_fallback_heuristic() -> None:
    exp = _make_cdf_exporter()
    # "SomeNewTag" → "S-OME-NEW-TAG" (hyphen before each capital)
    result = exp._format_tag("SomeNewTag")
    assert result == result.upper()
    assert "-" in result


def test_format_tag_single_word() -> None:
    exp = _make_cdf_exporter()
    result = exp._format_tag("Msrsw")
    assert result == "MSRSW"


# ---------------------------------------------------------------------------
# CDFExporter._apply_xml_attributes
# ---------------------------------------------------------------------------


def test_apply_xml_attributes_with_attributes() -> None:
    exp = _make_cdf_exporter()
    elem = etree.Element("root")
    obj = MagicMock(spec=["ATTRIBUTES", "my_attr"])
    obj.ATTRIBUTES = {"xml-id": "my_attr"}
    obj.my_attr = "42"
    exp._apply_xml_attributes(elem, obj)
    assert elem.get("xml-id") == "42"


def test_apply_xml_attributes_none_value_skipped() -> None:
    exp = _make_cdf_exporter()
    elem = etree.Element("root")
    obj = MagicMock(spec=["ATTRIBUTES", "missing"])
    obj.ATTRIBUTES = {"xml-id": "missing"}
    obj.missing = None
    exp._apply_xml_attributes(elem, obj)
    assert elem.get("xml-id") is None


def test_apply_xml_attributes_no_attributes_attr() -> None:
    exp = _make_cdf_exporter()
    elem = etree.Element("root")
    # obj without ATTRIBUTES → no-op
    exp._apply_xml_attributes(elem, SimpleNamespace())
    assert len(elem.attrib) == 0


# ---------------------------------------------------------------------------
# CDFExporter._apply_terminal_content
# ---------------------------------------------------------------------------


def test_apply_terminal_content_terminal_node() -> None:
    elem = etree.Element("val")
    obj = SimpleNamespace(TERMINAL=True, content="hello")
    CDFExporter._apply_terminal_content(elem, obj)
    assert elem.text == "hello"


def test_apply_terminal_content_non_terminal() -> None:
    elem = etree.Element("val")
    obj = SimpleNamespace(TERMINAL=False, content="hello")
    CDFExporter._apply_terminal_content(elem, obj)
    assert elem.text is None


def test_apply_terminal_content_none_content() -> None:
    elem = etree.Element("val")
    obj = SimpleNamespace(TERMINAL=True, content=None)
    CDFExporter._apply_terminal_content(elem, obj)
    assert elem.text is None


def test_apply_terminal_content_no_terminal_attr() -> None:
    elem = etree.Element("val")
    obj = SimpleNamespace(content="x")  # no TERMINAL attr
    CDFExporter._apply_terminal_content(elem, obj)
    assert elem.text is None


# ---------------------------------------------------------------------------
# CDFExporter._append_scalar_value
# ---------------------------------------------------------------------------


def test_append_scalar_value_creates_subelement() -> None:
    elem = etree.Element("root")
    CDFExporter._append_scalar_value(elem, 3.14, "V")
    assert len(elem) == 1
    assert elem[0].tag == "V"
    assert elem[0].text == "3.14"


def test_append_scalar_value_string() -> None:
    elem = etree.Element("root")
    CDFExporter._append_scalar_value(elem, "hello", "VT")
    assert elem[0].tag == "VT"
    assert elem[0].text == "hello"


# ---------------------------------------------------------------------------
# CDFExporter._append_flat_values
# ---------------------------------------------------------------------------


def test_append_flat_values_creates_children() -> None:
    elem = etree.Element("root")
    CDFExporter._append_flat_values(elem, [1.0, 2.0, 3.0], "V")
    assert len(elem) == 3
    assert [e.tag for e in elem] == ["V", "V", "V"]
    assert [e.text for e in elem] == ["1.0", "2.0", "3.0"]


def test_append_flat_values_empty() -> None:
    elem = etree.Element("root")
    CDFExporter._append_flat_values(elem, [], "V")
    assert len(elem) == 0


# ---------------------------------------------------------------------------
# CDFExporter._skip_child_tag
# ---------------------------------------------------------------------------


def test_skip_child_tag_non_sw_instance_never_skipped() -> None:
    exp = _make_cdf_exporter(variant_coding=True)
    obj = SimpleNamespace()  # not SwInstance
    assert exp._skip_child_tag(obj, "SwValueCont") is False


def test_skip_child_tag_variant_coding_skips_value_cont() -> None:
    from asamint.calibration.msrsw_db import SwInstance

    exp = _make_cdf_exporter(variant_coding=True)
    obj = MagicMock(spec=SwInstance)
    assert exp._skip_child_tag(obj, "SwValueCont") is True
    assert exp._skip_child_tag(obj, "SwAxisConts") is True


def test_skip_child_tag_no_variant_coding_skips_props_variants() -> None:
    from asamint.calibration.msrsw_db import SwInstance

    exp = _make_cdf_exporter(variant_coding=False)
    obj = MagicMock(spec=SwInstance)
    assert exp._skip_child_tag(obj, "SwInstancePropsVariants") is True
    assert exp._skip_child_tag(obj, "SwValueCont") is False
