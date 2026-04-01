#!/usr/bin/env python
"""Tests for asamint.cdf.walker – utility functions and CdfWalker.do_* methods."""
from __future__ import annotations

import binascii
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from asamint.cdf import walker
from asamint.cdf.walker import (
    array_values,
    axis_formatter,
    convert_timestamp,
    dump_array,
    get_content,
    reshape,
    scalar_value,
)
from asamint.msrsw.elements import VF, VG, VH, VT, V

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ns(**kwargs) -> SimpleNamespace:
    """Build a SimpleNamespace with attribute .content = value."""
    return SimpleNamespace(**kwargs)


def _orm_v(content) -> SimpleNamespace:
    return SimpleNamespace(content=content)


# ---------------------------------------------------------------------------
# array_values
# ---------------------------------------------------------------------------


def test_array_values_flat_integers() -> None:
    values = [V(phys=1), V(phys=2), V(phys=3)]
    assert array_values(values) == [1, 2, 3]


def test_array_values_flat_floats() -> None:
    values = [VF(phys=0.5), VF(phys=1.5)]
    assert array_values(values) == [0.5, 1.5]


def test_array_values_nested_vg_not_flattened() -> None:
    inner = VG(values=[V(phys=10), V(phys=20)])
    outer = [inner]
    result = array_values(outer)
    assert result == [[10, 20]]


def test_array_values_nested_vg_flattened() -> None:
    inner = VG(values=[V(phys=10), V(phys=20)])
    outer = [inner]
    result = array_values(outer, flatten=True)
    assert result == [10, 20]


def test_array_values_text_values() -> None:
    values = [VT(phys="low"), VT(phys="med"), VT(phys="high")]
    assert array_values(values) == ["low", "med", "high"]


def test_array_values_empty() -> None:
    assert array_values([]) == []


# ---------------------------------------------------------------------------
# scalar_value
# ---------------------------------------------------------------------------


def test_scalar_value_numeric() -> None:
    assert scalar_value([V(phys=42.0)]) == 42.0


def test_scalar_value_text_wrapped_in_quotes() -> None:
    assert scalar_value([VT(phys="hello")]) == "'hello'"


def test_scalar_value_uses_first_element() -> None:
    assert scalar_value([V(phys=7), V(phys=99)]) == 7


# ---------------------------------------------------------------------------
# axis_formatter
# ---------------------------------------------------------------------------


def test_axis_formatter_numeric() -> None:
    result = axis_formatter([0.0, 1.0, 2.5])
    assert "0.000" in result
    assert "2.500" in result


def test_axis_formatter_strings() -> None:
    result = axis_formatter(["low", "med", "high"])
    assert "'low'" in result
    assert "'med'" in result


def test_axis_formatter_empty() -> None:
    # all-string check: empty list → all() on empty is True → string path
    result = axis_formatter([])
    assert result == ""


# ---------------------------------------------------------------------------
# dump_array
# ---------------------------------------------------------------------------


def test_dump_array_flat_numbers() -> None:
    result = dump_array([1.0, 2.0, 3.0])
    assert "1.000" in result
    assert "2.000" in result


def test_dump_array_nested_list() -> None:
    result = dump_array([[1.0, 2.0], [3.0, 4.0]])
    assert "1.000" in result
    assert "3.000" in result


def test_dump_array_with_brackets() -> None:
    result = dump_array([[1.0, 2.0]], brackets=True)
    assert "[" in result
    assert "]" in result


def test_dump_array_string_values() -> None:
    result = dump_array(["hello"])
    assert "hello" in result


def test_dump_array_decimal_values() -> None:
    result = dump_array([Decimal("3.14")])
    assert "3.140" in result


# ---------------------------------------------------------------------------
# reshape
# ---------------------------------------------------------------------------


def test_reshape_empty_dim_returns_original() -> None:
    data = [1, 2, 3, 4]
    assert reshape(data, ()) == data


def test_reshape_single_dim() -> None:
    data = [1, 2, 3, 4, 5, 6]
    result = reshape(data, (3,))
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# convert_timestamp
# ---------------------------------------------------------------------------


def test_convert_timestamp_default_format() -> None:
    dt = convert_timestamp("2024-03-15T10:30:00")
    assert dt == datetime(2024, 3, 15, 10, 30, 0)


def test_convert_timestamp_custom_format() -> None:
    dt = convert_timestamp("15.03.2024 10:30", fmt="%d.%m.%Y %H:%M")
    assert dt.year == 2024
    assert dt.month == 3
    assert dt.day == 15


def test_convert_timestamp_invalid_raises() -> None:
    with pytest.raises(ValueError):
        convert_timestamp("not-a-date")


# ---------------------------------------------------------------------------
# get_content
# ---------------------------------------------------------------------------


def test_get_content_with_attr() -> None:
    attr = _ns(content=42)
    assert get_content(attr) == 42


def test_get_content_none_attr_returns_default() -> None:
    assert get_content(None, default="fallback") == "fallback"


def test_get_content_with_converter() -> None:
    attr = _ns(content="3")
    assert get_content(attr, converter=int) == 3


def test_get_content_converter_exception_returns_original() -> None:
    attr = _ns(content="not-a-number")
    # converter raises → returns original string
    result = get_content(attr, converter=int)
    assert result == "not-a-number"


# ---------------------------------------------------------------------------
# CdfWalker.do_* methods – tested via a DB-free subclass
# ---------------------------------------------------------------------------


class _NoDBWalker(walker.CdfWalker):
    """CdfWalker subclass that skips DB connection for unit testing."""

    def __init__(self) -> None:  # noqa: D107
        pass  # skip super().__init__() which opens a DB

    def on_instance(self, instance) -> None:  # noqa: D102
        pass

    def on_header(self, *args, **kwargs) -> None:  # noqa: D102
        pass


@pytest.fixture
def w() -> _NoDBWalker:
    return _NoDBWalker()


def test_do_shortname(w: _NoDBWalker) -> None:
    result = w.do_shortname(_ns(content="MyParam"))
    assert result.value == "MyParam"


def test_do_shortname_none_attr(w: _NoDBWalker) -> None:
    result = w.do_shortname(None)
    assert result.value == ""


def test_do_longname(w: _NoDBWalker) -> None:
    assert w.do_longname(_ns(content="Long Name")).value == "Long Name"


def test_do_displayname(w: _NoDBWalker) -> None:
    assert w.do_displayname(_ns(content="Display")).value == "Display"


def test_do_category(w: _NoDBWalker) -> None:
    assert w.do_category(_ns(content="VALUE")).value == "VALUE"


def test_do_feature_ref(w: _NoDBWalker) -> None:
    result = w.do_feature_ref(_ns(content="MyFunction"))
    assert result.name == "MyFunction"


def test_do_instance_ref(w: _NoDBWalker) -> None:
    result = w.do_instance_ref(_ns(content="AxisRef"))
    assert result.name == "AxisRef"


def test_do_sw_model_link(w: _NoDBWalker) -> None:
    result = w.do_sw_model_link(_ns(content="/path/to/model"))
    assert result.value == "/path/to/model"


def test_do_unit_display_name(w: _NoDBWalker) -> None:
    result = w.do_unit_display_name(_ns(content="rpm"))
    assert result.value == "rpm"
    assert result.phys == "rpm"  # .phys alias must work


def test_do_vs_creates_v_elements(w: _NoDBWalker) -> None:
    orm_vs = [_orm_v(1.0), _orm_v(2.0), _orm_v(3.0)]
    result = w.do_vs(orm_vs)
    assert len(result) == 3
    assert all(isinstance(v, V) for v in result)
    assert [v.phys for v in result] == [1.0, 2.0, 3.0]


def test_do_vs_empty(w: _NoDBWalker) -> None:
    assert w.do_vs(None) == []
    assert w.do_vs([]) == []


def test_do_vfs_creates_vf_elements(w: _NoDBWalker) -> None:
    result = w.do_vfs([_orm_v(0.5), _orm_v(1.5)])
    assert all(isinstance(v, VF) for v in result)
    assert result[0].phys == 0.5


def test_do_vts_creates_vt_elements(w: _NoDBWalker) -> None:
    result = w.do_vts([_orm_v("low"), _orm_v("high")])
    assert all(isinstance(v, VT) for v in result)
    assert result[0].phys == "low"


def test_do_vhs_hex_content(w: _NoDBWalker) -> None:
    hex_str = "DEADBEEF"
    orm_vhs = [SimpleNamespace(content=hex_str)]
    result = w.do_vhs(orm_vhs)
    assert len(result) == 1
    assert isinstance(result[0], VH)
    assert result[0].phys == binascii.unhexlify("DEADBEEF")


def test_do_vhs_non_hex_kept_as_string(w: _NoDBWalker) -> None:
    orm_vhs = [SimpleNamespace(content="not-hex!")]
    result = w.do_vhs(orm_vhs)
    assert result[0].phys == "not-hex!"


def test_do_array_size_from_vfs(w: _NoDBWalker) -> None:
    arr = SimpleNamespace(
        vfs=[_orm_v(5.0), _orm_v(3.0)],
        vs=None,
    )
    result = w.do_array_size(arr)
    assert result.dimensions == (5, 3)


def test_do_array_size_none(w: _NoDBWalker) -> None:
    result = w.do_array_size(None)
    assert result.dimensions == ()


def test_do_array_index(w: _NoDBWalker) -> None:
    result = w.do_array_index(_ns(content=2))
    assert result.value == 2


def test_do_remark_with_paragraphs(w: _NoDBWalker) -> None:
    remark = SimpleNamespace(ps=[_ns(content="para1"), _ns(content="para2")])
    result = w.do_remark(remark)
    assert len(result) == 2
    assert result[0].value == "para1"


def test_do_remark_empty(w: _NoDBWalker) -> None:
    remark = SimpleNamespace(ps=None)
    result = w.do_remark(remark)
    # returns Remark([]) when no paragraphs
    from asamint.msrsw.elements import Remark

    assert isinstance(result, Remark)


def test_do_vgs_with_vs(w: _NoDBWalker) -> None:
    vg_item = SimpleNamespace(
        label=_ns(content="myLabel"),
        vs=[_orm_v(1.0), _orm_v(2.0)],
        vfs=None,
        vts=None,
        vhs=None,
        children=[],
    )
    result = w.do_vgs([vg_item])
    assert len(result) == 1
    vg = result[0]
    assert vg.label == "myLabel"
    assert len(vg.values) == 2
    assert vg.values[0].phys == 1.0


def test_do_values_vs_branch(w: _NoDBWalker) -> None:
    values_orm = SimpleNamespace(
        vs=[_orm_v(10.0), _orm_v(20.0)],
        vgs=None,
        vts=None,
        vfs=None,
        vhs=None,
    )
    result = w.do_values(values_orm)
    assert len(result) == 2
    assert result[0].phys == 10.0


def test_do_values_none(w: _NoDBWalker) -> None:
    assert w.do_values(None) == []


def test_do_sw_cs_collection_feature(w: _NoDBWalker) -> None:
    coll = SimpleNamespace(
        category=_ns(content="FEATURE"),
        sw_feature_ref=_ns(content="FuncA"),
        sw_collection_ref=None,
    )
    collections = SimpleNamespace(sw_cs_collection=[coll])
    result = w.do_sw_cs_collection(collections)
    assert len(result) == 1
    from asamint.msrsw.elements import A2LFunction

    assert isinstance(result[0], A2LFunction)
    assert result[0].name == "FuncA"


def test_do_sw_cs_collection_none(w: _NoDBWalker) -> None:
    assert w.do_sw_cs_collection(None) == []
