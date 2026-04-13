"""Tests for dependent and virtual characteristic evaluation (ASAM Appendix G)."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from asamint.adapters.a2l import ModCommon, ModPar, open_a2l_database
from asamint.calibration import api as calibration
from asamint.calibration.dependent import (
    DependencyEntry,
    DependencyGraph,
    DependencyKind,
    EvaluationResult,
    ValidationResult,
    _detect_special_function,
    _eval_interp_1d,
    _eval_interp_nd,
    _eval_max,
    _eval_min,
)
from asamint.core.exceptions import CalibrationError
from asamint.core.logging import configure_logging

FIXTURE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cdf20_session():
    session = open_a2l_database(str(FIXTURE_DIR / "CDF20demo"), encoding="latin1", local=True)
    yield session
    close_fn = getattr(session, "close", None)
    if callable(close_fn):
        close_fn()


@pytest.fixture(scope="module")
def asap2_session():
    session = open_a2l_database(str(FIXTURE_DIR / "ASAP2_Demo_V161"), encoding="latin1", local=True)
    yield session
    close_fn = getattr(session, "close", None)
    if callable(close_fn):
        close_fn()


@pytest.fixture
def cdf20_offline(cdf20_session):
    from asamint.adapters.objutils import load

    image = load("ihex", str(FIXTURE_DIR / "CDF20demo.hex"))
    return calibration.OfflineCalibration(cdf20_session, image, loglevel="DEBUG")


# ---------------------------------------------------------------------------
# Unit tests: DependencyGraph
# ---------------------------------------------------------------------------


class TestDependencyGraph:
    """Pure unit tests for graph construction and ordering."""

    def test_build_from_cdf20(self, cdf20_session):
        """CDF20demo has exactly 1 DEPENDENT characteristic."""
        graph = DependencyGraph.build(cdf20_session)
        assert "CDF20.Dependent.Ref_1.FW_wU16" in graph.entries
        entry = graph.entries["CDF20.Dependent.Ref_1.FW_wU16"]
        assert entry.formula == "X1 * 5"
        assert entry.input_names == ["CDF20.Dependent.Base.FW_wU16"]
        assert entry.kind == DependencyKind.DEPENDENT

    def test_build_from_asap2(self, asap2_session):
        """ASAP2_Demo_V161 has 5 DEPENDENT + 5 VIRTUAL characteristics."""
        graph = DependencyGraph.build(asap2_session)
        dep_count = sum(1 for e in graph.entries.values() if e.kind == DependencyKind.DEPENDENT)
        virt_count = sum(1 for e in graph.entries.values() if e.kind == DependencyKind.VIRTUAL)
        assert dep_count == 5
        # 4 virtual (ASAM.C.VIRTUAL.ASCII is type ASCII → excluded by G.1.2)
        assert virt_count == 4

    def test_reverse_map(self, cdf20_session):
        """Modifying the base should list the dependent in the reverse map."""
        graph = DependencyGraph.build(cdf20_session)
        dependents = graph.dependents_of("CDF20.Dependent.Base.FW_wU16")
        assert "CDF20.Dependent.Ref_1.FW_wU16" in dependents

    def test_reverse_map_empty(self, cdf20_session):
        """A characteristic with no dependents returns an empty list."""
        graph = DependencyGraph.build(cdf20_session)
        assert graph.dependents_of("NONEXISTENT") == []

    def test_calculation_order_single(self, cdf20_session):
        """Single dependency: order is just the one dependent."""
        graph = DependencyGraph.build(cdf20_session)
        order = graph.calculation_order("CDF20.Dependent.Base.FW_wU16")
        assert len(order) == 1
        assert order[0].name == "CDF20.Dependent.Ref_1.FW_wU16"

    def test_calculation_order_chain(self, asap2_session):
        """ASAP2 demo has a chain:
        REF_1 depends on SBYTE → REF_3 depends on REF_1 and REF_2
        REF_4 depends on REF_1
        REF_5 depends on VIRTUAL.SYSTEM_CONSTANT_1

        Modifying SBYTE should recalculate REF_1 first, then REF_3 and REF_4.
        """
        graph = DependencyGraph.build(asap2_session)
        order = graph.calculation_order("ASAM.C.SCALAR.SBYTE.IDENTICAL")
        names = [e.name for e in order]
        assert "ASAM.C.DEPENDENT.REF_1.SWORD" in names

        # REF_3 depends on REF_1, so REF_1 must come before REF_3
        if "ASAM.C.DEPENDENT.REF_3.SWORD" in names:
            idx_1 = names.index("ASAM.C.DEPENDENT.REF_1.SWORD")
            idx_3 = names.index("ASAM.C.DEPENDENT.REF_3.SWORD")
            assert idx_1 < idx_3

    def test_calculation_order_no_dependents(self, cdf20_session):
        """A characteristic with no dependents returns empty order."""
        graph = DependencyGraph.build(cdf20_session)
        order = graph.calculation_order("CDF20.Dependent.Ref_1.FW_wU16")
        assert order == []

    def test_cycle_detection(self):
        """Manually constructed cycle should raise CalibrationError."""
        graph = DependencyGraph(entries={}, reverse_map={})
        # Create a cycle: A → B → A
        entry_a = DependencyEntry(
            name="A",
            formula="X1",
            input_names=["B"],
            kind=DependencyKind.DEPENDENT,
            dependent_type="VALUE",
        )
        entry_b = DependencyEntry(
            name="B",
            formula="X1",
            input_names=["A"],
            kind=DependencyKind.DEPENDENT,
            dependent_type="VALUE",
        )
        graph.entries = {"A": entry_a, "B": entry_b}
        graph.reverse_map = {"A": ["B"], "B": ["A"]}

        with pytest.raises(CalibrationError, match="[Cc]ircular"):
            graph._detect_cycles()


# ---------------------------------------------------------------------------
# Unit tests: special function detection
# ---------------------------------------------------------------------------


class TestSpecialFunctionDetection:
    """Tests for formula special function parsing."""

    def test_detect_min(self):
        result = _detect_special_function("min(Array_C)")
        assert result == ("min", "Array_C", [])

    def test_detect_max(self):
        result = _detect_special_function("max(Array_C)")
        assert result == ("max", "Array_C", [])

    def test_detect_interp_1d(self):
        result = _detect_special_function("interp(Curve_C, 3.5)")
        assert result is not None
        assert result[0] == "interp"
        assert result[1] == "Curve_C"
        assert len(result[2]) == 1
        assert result[2][0] == pytest.approx(3.5)

    def test_detect_interp_2d(self):
        result = _detect_special_function("interp(Map_C, 3.5, 8)")
        assert result is not None
        assert result[0] == "interp"
        assert result[1] == "Map_C"
        assert len(result[2]) == 2

    def test_detect_none_for_arithmetic(self):
        result = _detect_special_function("X1 + 5")
        assert result is None

    def test_detect_case_insensitive(self):
        assert _detect_special_function("MIN(X)") is not None
        assert _detect_special_function("Max(Y)") is not None
        assert _detect_special_function("INTERP(Z, 1.0)") is not None


# ---------------------------------------------------------------------------
# Unit tests: special functions (min, max, interp)
# ---------------------------------------------------------------------------


class TestSpecialFunctions:
    """Tests for the min/max/interp helper functions (G.1.8)."""

    def test_eval_min(self):
        arr = np.array([8, 5, 3, 4, 6, 7, 21, 7, 11, 9, 13, 14])
        assert _eval_min(arr) == 3.0

    def test_eval_max(self):
        arr = np.array([8, 5, 3, 4, 6, 7, 21, 7, 11, 9, 13, 14])
        assert _eval_max(arr) == 21.0

    def test_eval_interp_1d_exact(self):
        """Interpolation at exact axis points returns exact values."""
        axes = np.array([1.0, 2.0, 3.0, 4.0])
        vals = np.array([5.0, 10.0, 15.0, 20.0])
        assert _eval_interp_1d(axes, vals, 2.0) == 10.0

    def test_eval_interp_1d_between(self):
        """G.2.3 example: interp(Curve_C, 3.5) = 17.5."""
        axes = np.array([1.0, 2.0, 3.0, 4.0])
        vals = np.array([5.0, 10.0, 15.0, 20.0])
        assert _eval_interp_1d(axes, vals, 3.5) == pytest.approx(17.5)

    def test_eval_interp_1d_below_range(self):
        """G.2.3: axis value below lowest returns lowest value."""
        axes = np.array([1.0, 2.0, 3.0, 4.0])
        vals = np.array([5.0, 10.0, 15.0, 20.0])
        assert _eval_interp_1d(axes, vals, 0.0) == pytest.approx(5.0)

    def test_eval_interp_1d_above_range(self):
        """G.2.3: axis value above highest returns highest value."""
        axes = np.array([1.0, 2.0, 3.0, 4.0])
        vals = np.array([5.0, 10.0, 15.0, 20.0])
        assert _eval_interp_1d(axes, vals, 5.0) == pytest.approx(20.0)

    def test_eval_interp_nd_2d(self):
        """2-D interpolation on a simple MAP."""
        x_axis = np.array([1.0, 2.0])
        y_axis = np.array([1.0, 2.0])
        # 2x2 grid: [[10, 20], [30, 40]]
        fnc = np.array([[10.0, 20.0], [30.0, 40.0]])
        # Interpolate at center (1.5, 1.5) → (10+20+30+40)/4 = 25
        result = _eval_interp_nd([x_axis, y_axis], fnc, [1.5, 1.5])
        assert result == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# Integration tests: CDF20 dependent characteristic
# ---------------------------------------------------------------------------


class TestCDF20DependentIntegration:
    """Integration tests using CDF20demo.a2l + CDF20demo.hex."""

    def test_graph_built_lazily(self, cdf20_offline):
        """Dependency graph is accessible via the calibration object."""
        graph = cdf20_offline.dependency_graph
        assert isinstance(graph, DependencyGraph)
        assert "CDF20.Dependent.Ref_1.FW_wU16" in graph.entries

    def test_load_base_value(self, cdf20_offline):
        """Load the base value (non-dependent) successfully."""
        val = cdf20_offline.load_value("CDF20.Dependent.Base.FW_wU16")
        assert val.raw == 17
        assert val.phys == 17.0

    def test_load_dependent_value(self, cdf20_offline):
        """Load the dependent value — category should be DEPENDENT_VALUE."""
        val = cdf20_offline.load_value("CDF20.Dependent.Ref_1.FW_wU16")
        assert val.category == "DEPENDENT_VALUE"

    def test_save_triggers_recalculation(self, cdf20_offline):
        """Saving the base value should recalculate the dependent.

        CDF20.Dependent.Ref_1 = X1 * 5 where X1 = CDF20.Dependent.Base.
        Base starts at 17, so Ref_1 should be 85.
        If we save Base to 10, Ref_1 should become 50.
        """
        # Read initial state
        base = cdf20_offline.load_value("CDF20.Dependent.Base.FW_wU16")
        assert base.raw == 17

        # Save a new value — this should trigger recalculation
        status = cdf20_offline.save_value("CDF20.Dependent.Base.FW_wU16", 10.0)
        assert status == calibration.Status.OK

        # Read the dependent value — it should now be 10 * 5 = 50
        ref = cdf20_offline.load_value("CDF20.Dependent.Ref_1.FW_wU16")
        assert ref.raw == 50
        assert ref.phys == pytest.approx(50.0)

    def test_recalculate_dependents_api(self, cdf20_offline):
        """Explicit call to recalculate_dependents works."""
        results = cdf20_offline.recalculate_dependents("CDF20.Dependent.Base.FW_wU16")
        assert len(results) == 1
        assert results[0].name == "CDF20.Dependent.Ref_1.FW_wU16"
        assert results[0].kind == DependencyKind.DEPENDENT

    def test_no_dependents_returns_empty(self, cdf20_offline):
        """A characteristic with no dependents returns empty list."""
        results = cdf20_offline.recalculate_dependents("CDF20")
        assert results == []


# ---------------------------------------------------------------------------
# Integration tests: ASAP2 Demo dependency chain
# ---------------------------------------------------------------------------


class TestASAP2DependencyChain:
    """Tests with ASAP2_Demo_V161 which has multi-level dependency chains."""

    def test_graph_entry_formulas(self, asap2_session):
        """Verify all dependency entries have correct formulas."""
        graph = DependencyGraph.build(asap2_session)

        # DEPENDENT entries
        ref1 = graph.entries["ASAM.C.DEPENDENT.REF_1.SWORD"]
        assert ref1.formula == "X1 + 5"
        assert ref1.input_names == ["ASAM.C.SCALAR.SBYTE.IDENTICAL"]

        ref2 = graph.entries["ASAM.C.DEPENDENT.REF_2.UWORD"]
        assert ref2.formula == "X1 + 25"
        assert ref2.input_names == ["ASAM.C.SCALAR.UBYTE.IDENTICAL"]

        ref3 = graph.entries["ASAM.C.DEPENDENT.REF_3.SWORD"]
        assert ref3.formula == "X1 + X2"
        assert set(ref3.input_names) == {
            "ASAM.C.DEPENDENT.REF_1.SWORD",
            "ASAM.C.DEPENDENT.REF_2.UWORD",
        }

        ref5 = graph.entries["ASAM.C.DEPENDENT.REF_5.FLOAT64_IEEE"]
        assert ref5.formula == "X1 * 2"
        assert ref5.input_names == ["ASAM.C.VIRTUAL.SYSTEM_CONSTANT_1"]

    def test_virtual_entry_formulas(self, asap2_session):
        """Verify virtual characteristic entries."""
        graph = DependencyGraph.build(asap2_session)

        virt1 = graph.entries["ASAM.C.VIRTUAL.REF_1.SWORD"]
        assert virt1.formula == "X1 - 9"
        assert virt1.kind == DependencyKind.VIRTUAL

        virt_sc = graph.entries["ASAM.C.VIRTUAL.SYSTEM_CONSTANT_1"]
        assert "sysc(System_Constant_1)" in virt_sc.formula

    def test_chain_topology(self, asap2_session):
        """REF_3 depends on REF_1 and REF_2; REF_4 depends on REF_1.

        Modifying SBYTE should yield: REF_1 first, then REF_3/REF_4.
        """
        graph = DependencyGraph.build(asap2_session)
        order = graph.calculation_order("ASAM.C.SCALAR.SBYTE.IDENTICAL")
        names = [e.name for e in order]

        # REF_1 must appear
        assert "ASAM.C.DEPENDENT.REF_1.SWORD" in names

        # REF_4 depends on REF_1
        if "ASAM.C.DEPENDENT.REF_4.FLOAT64_IEEE" in names:
            assert names.index("ASAM.C.DEPENDENT.REF_1.SWORD") < names.index("ASAM.C.DEPENDENT.REF_4.FLOAT64_IEEE")

    def test_virtual_chain_topology(self, asap2_session):
        """VIRTUAL.REF_3 depends on VIRTUAL.REF_1 and VIRTUAL.REF_2.

        Modifying SBYTE should yield: VIRTUAL.REF_1 first, then VIRTUAL.REF_3.
        """
        graph = DependencyGraph.build(asap2_session)
        order = graph.calculation_order("ASAM.C.SCALAR.SBYTE.IDENTICAL")
        names = [e.name for e in order]

        if "ASAM.C.VIRTUAL.REF_1.SWORD" in names and "ASAM.C.VIRTUAL.REF_3.SWORD" in names:
            assert names.index("ASAM.C.VIRTUAL.REF_1.SWORD") < names.index("ASAM.C.VIRTUAL.REF_3.SWORD")


# ---------------------------------------------------------------------------
# Unit tests: DependencyEntry dataclass
# ---------------------------------------------------------------------------


class TestDependencyEntry:
    """Tests for the DependencyEntry data class."""

    def test_frozen(self):
        entry = DependencyEntry(
            name="test",
            formula="X1",
            input_names=["input1"],
            kind=DependencyKind.DEPENDENT,
            dependent_type="VALUE",
        )
        with pytest.raises(AttributeError):
            entry.name = "changed"

    def test_kind_enum(self):
        assert DependencyKind.DEPENDENT != DependencyKind.VIRTUAL
        assert DependencyKind.DEPENDENT.name == "DEPENDENT"
        assert DependencyKind.VIRTUAL.name == "VIRTUAL"


# ---------------------------------------------------------------------------
# Unit tests: EvaluationResult
# ---------------------------------------------------------------------------


class TestEvaluationResult:
    """Tests for EvaluationResult."""

    def test_scalar_result(self):
        result = EvaluationResult(
            name="test",
            physical_value=42.0,
            kind=DependencyKind.DEPENDENT,
        )
        assert result.name == "test"
        assert result.physical_value == 42.0

    def test_array_result(self):
        arr = np.array([1.0, 2.0, 3.0])
        result = EvaluationResult(
            name="test",
            physical_value=arr,
            kind=DependencyKind.VIRTUAL,
        )
        np.testing.assert_array_equal(result.physical_value, arr)
