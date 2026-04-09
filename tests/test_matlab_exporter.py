#!/usr/bin/env python
"""Tests for asamint.cdf.exporter.matlab (Exporter, do_axis_containers)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from asamint.cdf.exporter.matlab import Exporter, do_axis_containers
from asamint.msrsw.elements import VT, ArraySize, V

# ---------------------------------------------------------------------------
# Helpers – DB-free subclass
# ---------------------------------------------------------------------------


class _ME(Exporter):
    """Exporter subclass that skips DB __init__ for unit testing."""

    def __init__(self) -> None:  # noqa: D107
        # skip super().__init__() to avoid DB; _out=None defers to sys.stdout
        self._out = None


@pytest.fixture()
def exp() -> _ME:
    return _ME()


def _ns(**kw):
    return SimpleNamespace(**kw)


def _scalar_inst(name="P1", category="VALUE", phys_val=42.0, unit="rpm"):
    return _ns(
        short_name=name,
        category=category,
        values=_ns(
            unit_display_name=_ns(value=unit, phys=unit),
            values_phys=[V(phys=phys_val)],
            array_size=ArraySize(()),
        ),
    )


def _array_inst(
    name="A1", category="VAL_BLK", phys_vals=(1.0, 2.0, 3.0), dims=(3,), unit="m"
):
    return _ns(
        short_name=name,
        category=category,
        values=_ns(
            unit_display_name=_ns(value=unit, phys=unit),
            values_phys=[V(phys=v) for v in phys_vals],
            array_size=ArraySize(dims),
        ),
    )


# ---------------------------------------------------------------------------
# _scalar_suffix
# ---------------------------------------------------------------------------


def test_scalar_suffix_value() -> None:
    assert Exporter._scalar_suffix("VALUE") == ""


def test_scalar_suffix_dependent_value() -> None:
    assert Exporter._scalar_suffix("DEPENDENT_VALUE") == "  -- DEP"


def test_scalar_suffix_boolean() -> None:
    assert Exporter._scalar_suffix("BOOLEAN") == "  -- BOOL"


def test_scalar_suffix_unknown_raises() -> None:
    with pytest.raises(KeyError):
        Exporter._scalar_suffix("UNKNOWN")


# ---------------------------------------------------------------------------
# _array_suffix
# ---------------------------------------------------------------------------


def test_array_suffix_val_blk() -> None:
    assert Exporter._array_suffix("VAL_BLK") == "  -- BLK"


def test_array_suffix_curve() -> None:
    assert Exporter._array_suffix("CURVE") == "  -- CURVE"


def test_array_suffix_map() -> None:
    assert Exporter._array_suffix("MAP") == "  -- MAP"


def test_array_suffix_com_axis() -> None:
    assert Exporter._array_suffix("COM_AXIS") == "  -- COM"


def test_array_suffix_res_axis() -> None:
    assert Exporter._array_suffix("RES_AXIS") == "  -- RES"


def test_array_suffix_unknown_raises() -> None:
    with pytest.raises(KeyError):
        Exporter._array_suffix("UNKNOWN")


# ---------------------------------------------------------------------------
# on_header
# ---------------------------------------------------------------------------


def test_on_header_prints_all_args(exp: _ME, capsys) -> None:
    exp.on_header("MyProject", "model.a2l", "fw.hex", [], False)
    out = capsys.readouterr().out
    assert "HEADER" in out
    assert "MyProject" in out
    assert "model.a2l" in out
    assert "fw.hex" in out


def test_on_header_variants_flag(exp: _ME, capsys) -> None:
    exp.on_header("Proj", "f.a2l", "f.hex", [], True)
    out = capsys.readouterr().out
    assert "True" in out


# ---------------------------------------------------------------------------
# _emit_scalar
# ---------------------------------------------------------------------------


def test_emit_scalar_numeric(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=3.14)], array_size=ArraySize(()))
    exp._emit_scalar("MyParam", vc, "rpm", "")
    out = capsys.readouterr().out
    assert "MyParam = 3.14" in out
    assert "%[rpm]" in out
    assert "@CANAPE_ORIGIN@MyParam" in out


def test_emit_scalar_with_suffix(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=1.0)], array_size=ArraySize(()))
    exp._emit_scalar("P", vc, "K", "  -- DEP")
    out = capsys.readouterr().out
    assert "  -- DEP" in out


def test_emit_scalar_string_value(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[VT(phys="hello")], array_size=ArraySize(()))
    exp._emit_scalar("S", vc, "", "")
    out = capsys.readouterr().out
    assert "'hello'" in out


def test_emit_scalar_empty_unit(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=0.0)], array_size=ArraySize(()))
    exp._emit_scalar("X", vc, "", "")
    out = capsys.readouterr().out
    assert "%[]" in out


# ---------------------------------------------------------------------------
# _array_values
# ---------------------------------------------------------------------------


def test_array_values_val_blk(exp: _ME) -> None:
    vc = _ns(values_phys=[V(phys=1.0), V(phys=2.0)], array_size=ArraySize((2,)))
    result = exp._array_values(vc, "VAL_BLK")
    assert result == [1.0, 2.0]


def test_array_values_curve(exp: _ME) -> None:
    vc = _ns(values_phys=[V(phys=10.0), V(phys=20.0)], array_size=ArraySize((2,)))
    result = exp._array_values(vc, "CURVE")
    assert result == [10.0, 20.0]


def test_array_values_map_no_dims(exp: _ME) -> None:
    vc = _ns(values_phys=[V(phys=5.0), V(phys=6.0)], array_size=ArraySize(()))
    result = exp._array_values(vc, "MAP")
    assert result == [5.0, 6.0]


def test_array_values_map_with_dims(exp: _ME) -> None:
    # slicer(6 values, 2) → 3 rows of 2; further slicing by 3 wraps into [[…]]
    # net result: 3 rows of 2 elements each
    vc = _ns(
        values_phys=[V(phys=float(i)) for i in range(6)],
        array_size=ArraySize((2, 3)),
    )
    result = exp._array_values(vc, "MAP")
    assert len(result) == 3
    assert len(result[0]) == 2


def test_array_values_map_preserves_values(exp: _ME) -> None:
    vc = _ns(
        values_phys=[V(phys=float(i)) for i in range(4)],
        array_size=ArraySize((2, 2)),
    )
    result = exp._array_values(vc, "MAP")
    flat = [v for row in result for v in row]
    assert flat == [0.0, 1.0, 2.0, 3.0]


# ---------------------------------------------------------------------------
# _emit_array
# ---------------------------------------------------------------------------


def test_emit_array_val_blk(exp: _ME, capsys) -> None:
    vc = _ns(
        values_phys=[V(phys=float(i)) for i in range(3)], array_size=ArraySize((3,))
    )
    exp._emit_array("Arr", vc, "m", "VAL_BLK")
    out = capsys.readouterr().out
    assert "Arr = [" in out
    assert "]" in out
    assert "  -- BLK" in out
    assert "@CANAPE_ORIGIN@Arr" in out


def test_emit_array_curve(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=1.0), V(phys=2.0)], array_size=ArraySize((2,)))
    exp._emit_array("CRV", vc, "V", "CURVE")
    out = capsys.readouterr().out
    assert "  -- CURVE" in out


def test_emit_array_map(exp: _ME, capsys) -> None:
    vc = _ns(
        values_phys=[V(phys=float(i)) for i in range(4)], array_size=ArraySize((2, 2))
    )
    exp._emit_array("M", vc, "K", "MAP")
    out = capsys.readouterr().out
    assert "M = [" in out
    assert "  -- MAP" in out


def test_emit_array_unit_in_comment(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=1.0)], array_size=ArraySize((1,)))
    exp._emit_array("X", vc, "bar", "VAL_BLK")
    out = capsys.readouterr().out
    assert "%[bar]" in out


# ---------------------------------------------------------------------------
# _emit_axis
# ---------------------------------------------------------------------------


def test_emit_axis_com(exp: _ME, capsys) -> None:
    vc = _ns(
        values_phys=[V(phys=1.0), V(phys=2.0), V(phys=3.0)], array_size=ArraySize((3,))
    )
    exp._emit_axis("AX", vc, "rpm", "COM_AXIS")
    out = capsys.readouterr().out
    assert "AX = [" in out
    assert "  -- COM" in out
    assert "1.000" in out


def test_emit_axis_res(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=10.0)], array_size=ArraySize((1,)))
    exp._emit_axis("RA", vc, "", "RES_AXIS")
    out = capsys.readouterr().out
    assert "  -- RES" in out
    assert "10.000" in out


def test_emit_axis_unit_in_comment(exp: _ME, capsys) -> None:
    vc = _ns(values_phys=[V(phys=5.0)], array_size=ArraySize((1,)))
    exp._emit_axis("B", vc, "deg", "COM_AXIS")
    out = capsys.readouterr().out
    assert "%[deg]" in out


# ---------------------------------------------------------------------------
# on_instance – dispatch
# ---------------------------------------------------------------------------


def test_on_instance_value(exp: _ME, capsys) -> None:
    exp.on_instance(_scalar_inst(name="P", category="VALUE", phys_val=1.5, unit="bar"))
    out = capsys.readouterr().out
    assert "P = 1.5" in out
    assert "%[bar]" in out


def test_on_instance_value_no_suffix(exp: _ME, capsys) -> None:
    exp.on_instance(_scalar_inst(name="P", category="VALUE"))
    out = capsys.readouterr().out
    # VALUE has empty suffix, so line ends with unit comment
    assert "@CANAPE_ORIGIN@P\n" in out


def test_on_instance_dependent_value(exp: _ME, capsys) -> None:
    exp.on_instance(_scalar_inst(name="DP", category="DEPENDENT_VALUE"))
    out = capsys.readouterr().out
    assert "  -- DEP" in out


def test_on_instance_boolean(exp: _ME, capsys) -> None:
    exp.on_instance(_scalar_inst(name="BP", category="BOOLEAN", phys_val=1.0))
    out = capsys.readouterr().out
    assert "  -- BOOL" in out


def test_on_instance_ascii(exp: _ME, capsys) -> None:
    inst = _ns(
        short_name="S",
        category="ASCII",
        values=_ns(
            unit_display_name=None,
            values_phys=[VT(phys="hello")],
            array_size=ArraySize(()),
        ),
    )
    exp.on_instance(inst)
    out = capsys.readouterr().out
    assert "'hello'" in out
    assert " -- ASCII" in out


def test_on_instance_val_blk(exp: _ME, capsys) -> None:
    exp.on_instance(_array_inst(name="BLK", category="VAL_BLK"))
    out = capsys.readouterr().out
    assert "BLK = [" in out
    assert "  -- BLK" in out


def test_on_instance_curve(exp: _ME, capsys) -> None:
    exp.on_instance(_array_inst(name="CRV", category="CURVE", phys_vals=(10.0, 20.0)))
    out = capsys.readouterr().out
    assert "CRV = [" in out
    assert "  -- CURVE" in out


def test_on_instance_map(exp: _ME, capsys) -> None:
    exp.on_instance(
        _array_inst(
            name="MP", category="MAP", phys_vals=(1.0, 2.0, 3.0, 4.0), dims=(2, 2)
        )
    )
    out = capsys.readouterr().out
    assert "MP = [" in out
    assert "  -- MAP" in out


def test_on_instance_com_axis(exp: _ME, capsys) -> None:
    exp.on_instance(_array_inst(name="CA", category="COM_AXIS"))
    out = capsys.readouterr().out
    assert "CA = [" in out
    assert "  -- COM" in out


def test_on_instance_res_axis(exp: _ME, capsys) -> None:
    exp.on_instance(_array_inst(name="RA", category="RES_AXIS"))
    out = capsys.readouterr().out
    assert "RA = [" in out
    assert "  -- RES" in out


def test_on_instance_no_unit_display_name(exp: _ME, capsys) -> None:
    inst = _ns(
        short_name="NUP",
        category="VALUE",
        values=_ns(
            unit_display_name=None,
            values_phys=[V(phys=7.0)],
            array_size=ArraySize(()),
        ),
    )
    exp.on_instance(inst)
    out = capsys.readouterr().out
    assert "NUP = 7.0" in out
    assert "%[]" in out


def test_on_instance_unknown_category_no_output(exp: _ME, capsys) -> None:
    inst = _ns(
        short_name="X",
        category="UNKNOWN_CAT",
        values=_ns(
            unit_display_name=None, values_phys=[V(phys=0.0)], array_size=ArraySize(())
        ),
    )
    exp.on_instance(inst)
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# do_axis_containers
# ---------------------------------------------------------------------------


def test_do_axis_containers_empty_list(capsys) -> None:
    do_axis_containers([])
    assert capsys.readouterr().out == ""


def test_do_axis_containers_none(capsys) -> None:
    do_axis_containers(None)
    assert capsys.readouterr().out == ""


def test_do_axis_containers_single(caplog) -> None:
    cont = _ns(
        category=_ns(phys="COM_AXIS"),
        unit_display_name="rpm",
        array_size=_ns(dimensions=(3,)),
        instance_ref=_ns(name="MyRef"),
        values=[V(phys=float(i)) for i in range(3)],
    )
    import logging

    target = logging.getLogger("asamint.cdf.exporter.matlab")
    handler = caplog.handler
    target.addHandler(handler)
    old_level = target.level
    target.setLevel(logging.DEBUG)
    try:
        caplog.clear()
        do_axis_containers([cont])
        assert "AX:" in caplog.text
        assert "COM_AXIS" in caplog.text
        assert "MyRef" in caplog.text
    finally:
        target.removeHandler(handler)
        target.setLevel(old_level)


def test_do_axis_containers_multiple(caplog) -> None:
    def _cont(cat, ref):
        return _ns(
            category=_ns(phys=cat),
            unit_display_name="m",
            array_size=_ns(dimensions=(2,)),
            instance_ref=_ns(name=ref),
            values=[V(phys=1.0), V(phys=2.0)],
        )

    import logging

    target = logging.getLogger("asamint.cdf.exporter.matlab")
    handler = caplog.handler
    target.addHandler(handler)
    old_level = target.level
    target.setLevel(logging.DEBUG)
    try:
        caplog.clear()
        do_axis_containers([_cont("COM_AXIS", "Ref1"), _cont("RES_AXIS", "Ref2")])
        assert "Ref1" in caplog.text
        assert "Ref2" in caplog.text
        assert caplog.text.count("AX:") == 2
    finally:
        target.removeHandler(handler)
        target.setLevel(old_level)
