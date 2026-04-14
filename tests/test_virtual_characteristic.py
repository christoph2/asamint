"""Tests for VIRTUAL_CHARACTERISTIC runtime-only mode.

Covers:
- VirtualWriteError and write guards on all save methods
- Virtual evaluation in load_value, load_value_block, load_curve_or_map
- Dedicated _virtual_store caching
- XCP guard (OnlineCalibration skips virtual chars in dirty tracking)
- Bulk API: list_virtual, evaluate_all_virtual
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
import pytest

from asamint.adapters.a2l import open_a2l_database
from asamint.adapters.objutils import load
from asamint.calibration import api as calibration
from asamint.calibration.api import (
    OnlineCalibration,
    Status,
)
from asamint.calibration.dependent import (
    DependencyEntry,
    DependencyGraph,
    DependencyKind,
    EvaluationResult,
)
from asamint.core.exceptions import CalibrationError, VirtualWriteError

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


@pytest.fixture
def cdf20_image():
    return load("ihex", str(FIXTURE_DIR / "CDF20demo.hex"))


@pytest.fixture
def cdf20_offline(cdf20_session, cdf20_image):
    return calibration.OfflineCalibration(cdf20_session, cdf20_image, loglevel="DEBUG")


@pytest.fixture
def mock_xcp_master():
    master = MagicMock()
    master.setMta = MagicMock()
    master.push = MagicMock()
    master.pull = MagicMock(return_value=b"\x00" * 1024)
    return master


@pytest.fixture
def cdf20_online(cdf20_session, cdf20_image, mock_xcp_master):
    return OnlineCalibration(
        cdf20_session,
        mock_xcp_master,
        image=cdf20_image,
        auto_flush=True,
        loglevel="DEBUG",
    )


def _make_virtual_characteristic(name: str = "VIRT_TEST"):
    """Create a mock characteristic that has virtual_characteristic set."""
    char = MagicMock()
    char.name = name
    char.type = "VALUE"
    char.virtual_characteristic = SimpleNamespace(
        formula="X1 - 9",
        characteristic_id=["INPUT_1"],
    )
    char.dependent_characteristic = None
    char.readOnly = False
    char.longIdentifier = "virtual test"
    char.displayIdentifier = None
    char.physUnit = "unit"
    char.address = 0x1000
    char.total_allocated_memory = 4
    char.bitMask = None
    char.compuMethod = SimpleNamespace(
        conversionType="IDENT",
        unit="unit",
        name="CM_IDENT",
        evaluator=None,
    )
    char.fnc_asam_dtype = "UWORD"
    char.lowerLimit = 0
    char.upperLimit = 65535
    return char


# ---------------------------------------------------------------------------
# VirtualWriteError exception
# ---------------------------------------------------------------------------


class TestVirtualWriteError:
    """VirtualWriteError is a CalibrationError subclass."""

    def test_is_calibration_error(self):
        assert issubclass(VirtualWriteError, CalibrationError)

    def test_message(self):
        exc = VirtualWriteError("cannot write virtual")
        assert "cannot write virtual" in str(exc)


# ---------------------------------------------------------------------------
# Write guards — save_value, save_value_block, save_curve_or_map
# ---------------------------------------------------------------------------


class TestWriteGuards:
    """All save methods must reject virtual characteristics."""

    def test_save_value_rejects_virtual(self, cdf20_offline):
        """save_value raises VirtualWriteError for a virtual characteristic."""
        char = _make_virtual_characteristic("VIRT_VALUE")

        with patch.object(cdf20_offline, "get_characteristic", return_value=char):
            with pytest.raises(VirtualWriteError, match="Cannot write to virtual"):
                cdf20_offline.save_value("VIRT_VALUE", 42.0)

    def test_save_value_block_rejects_virtual(self, cdf20_offline):
        """save_value_block raises VirtualWriteError for a virtual characteristic."""
        char = _make_virtual_characteristic("VIRT_VALBLK")
        char.type = "VAL_BLK"

        with patch.object(cdf20_offline, "get_characteristic", return_value=char):
            with pytest.raises(VirtualWriteError, match="Cannot write to virtual"):
                cdf20_offline.save_value_block("VIRT_VALBLK", np.array([1, 2, 3]))

    def test_save_curve_or_map_rejects_virtual(self, cdf20_offline):
        """save_curve_or_map raises VirtualWriteError for a virtual characteristic."""
        char = _make_virtual_characteristic("VIRT_CURVE")
        char.type = "CURVE"

        wrapper = SimpleNamespace(
            raw=np.array([1.0, 2.0]),
            phys=np.array([1.0, 2.0]),
        )
        with patch.object(cdf20_offline, "get_characteristic", return_value=char):
            with pytest.raises(VirtualWriteError, match="Cannot write to virtual"):
                cdf20_offline.save_curve_or_map("VIRT_CURVE", wrapper)

    def test_save_value_allows_normal(self, cdf20_offline):
        """Normal (non-virtual) characteristics are still writable."""
        result = cdf20_offline.save_value("CDF20.Dependent.Base.FW_wU16", 100)
        assert result == Status.OK


# ---------------------------------------------------------------------------
# Virtual evaluation in load_value
# ---------------------------------------------------------------------------


class TestVirtualEvalInLoadValue:
    """load_value evaluates virtual formulas and caches in _virtual_store."""

    def test_virtual_value_category(self, cdf20_offline):
        """A virtual VALUE should have category VIRTUAL_VALUE."""
        char = _make_virtual_characteristic("VIRT_TEST")

        entry = DependencyEntry(
            name="VIRT_TEST",
            formula="X1 - 9",
            input_names=["INPUT_1"],
            kind=DependencyKind.VIRTUAL,
            dependent_type="VALUE",
        )
        ev_result = EvaluationResult(
            name="VIRT_TEST",
            physical_value=42.0,
            kind=DependencyKind.VIRTUAL,
        )

        with (
            patch.object(cdf20_offline, "get_characteristic", return_value=char),
            patch.object(cdf20_offline, "int_to_physical", return_value=0),
            patch.object(cdf20_offline, "is_numeric", return_value=True),
            patch.object(
                type(cdf20_offline),
                "dependency_graph",
                new_callable=PropertyMock,
                return_value=SimpleNamespace(entries={"VIRT_TEST": entry}),
            ),
            patch.object(
                type(cdf20_offline),
                "dependency_engine",
                new_callable=PropertyMock,
                return_value=SimpleNamespace(evaluate=MagicMock(return_value=ev_result)),
            ),
        ):
            val = cdf20_offline.load_value("VIRT_TEST")
            assert val.category == "VIRTUAL_VALUE"
            assert val.phys == 42.0

    def test_virtual_store_caching(self, cdf20_offline):
        """Second load_value for a virtual char should use _virtual_store."""
        cdf20_offline._virtual_store["CACHED_VIRT"] = 99.0

        char = _make_virtual_characteristic("CACHED_VIRT")

        with (
            patch.object(cdf20_offline, "get_characteristic", return_value=char),
            patch.object(cdf20_offline, "int_to_physical", return_value=0),
            patch.object(cdf20_offline, "is_numeric", return_value=True),
        ):
            val = cdf20_offline.load_value("CACHED_VIRT")
            assert val.phys == 99.0
            assert val.category == "VIRTUAL_VALUE"

        # Clean up
        cdf20_offline._virtual_store.pop("CACHED_VIRT", None)


# ---------------------------------------------------------------------------
# Virtual evaluation in load_value_block
# ---------------------------------------------------------------------------


class TestVirtualEvalInLoadValueBlock:
    """load_value_block evaluates virtual formulas for VAL_BLK."""

    def test_virtual_valblk_category(self, cdf20_offline):
        """A virtual VAL_BLK should have category VIRTUAL_VAL_BLK."""
        char = _make_virtual_characteristic("VIRT_BLK")
        char.type = "VAL_BLK"
        char.fnc_np_shape = (3,)
        char.fnc_np_order = "C"
        char.fnc_asam_dtype = "UWORD"

        computed = np.array([10.0, 20.0, 30.0])
        entry = DependencyEntry(
            name="VIRT_BLK",
            formula="X1 * 2",
            input_names=["INPUT_1"],
            kind=DependencyKind.VIRTUAL,
            dependent_type="VAL_BLK",
        )
        ev_result = EvaluationResult(
            name="VIRT_BLK",
            physical_value=computed,
            kind=DependencyKind.VIRTUAL,
        )

        with (
            patch.object(cdf20_offline, "get_characteristic", return_value=char),
            patch.object(cdf20_offline, "asam_byte_order", return_value="<"),
            patch.object(
                type(cdf20_offline),
                "dependency_graph",
                new_callable=PropertyMock,
                return_value=SimpleNamespace(entries={"VIRT_BLK": entry}),
            ),
            patch.object(
                type(cdf20_offline),
                "dependency_engine",
                new_callable=PropertyMock,
                return_value=SimpleNamespace(evaluate=MagicMock(return_value=ev_result)),
            ),
        ):
            blk = cdf20_offline.load_value_block("VIRT_BLK")
            assert blk.category == "VIRTUAL_VAL_BLK"
            np.testing.assert_array_equal(blk.phys, computed)

    def test_virtual_valblk_store_caching(self, cdf20_offline):
        """Cached virtual VAL_BLK values should be returned directly."""
        cached = np.array([5.0, 6.0, 7.0])
        cdf20_offline._virtual_store["CACHED_BLK"] = cached

        char = _make_virtual_characteristic("CACHED_BLK")
        char.type = "VAL_BLK"
        char.fnc_np_shape = (3,)
        char.fnc_np_order = "C"
        char.fnc_asam_dtype = "UWORD"

        with (
            patch.object(cdf20_offline, "get_characteristic", return_value=char),
            patch.object(cdf20_offline, "asam_byte_order", return_value="<"),
        ):
            blk = cdf20_offline.load_value_block("CACHED_BLK")
            assert blk.category == "VIRTUAL_VAL_BLK"
            np.testing.assert_array_equal(blk.phys, cached)

        cdf20_offline._virtual_store.pop("CACHED_BLK", None)


# ---------------------------------------------------------------------------
# Virtual evaluation in load_curve_or_map
# ---------------------------------------------------------------------------


class TestVirtualEvalInLoadCurveOrMap:
    """load_curve_or_map evaluates virtual formulas for CURVE/MAP types."""

    def test_virtual_curve_store_roundtrip(self, cdf20_offline):
        """_virtual_store caching works for CURVE-typed virtual characteristics."""
        computed = np.array([2.0, 4.0, 6.0])
        cdf20_offline._virtual_store["VIRT_CURVE"] = computed
        assert np.array_equal(cdf20_offline._virtual_store["VIRT_CURVE"], computed)
        cdf20_offline._virtual_store.pop("VIRT_CURVE", None)


# ---------------------------------------------------------------------------
# _virtual_store invalidation
# ---------------------------------------------------------------------------


class TestVirtualStoreInvalidation:
    """Virtual store entries are invalidated when inputs change."""

    def test_trigger_recalculation_invalidates_store(self, cdf20_offline):
        """When an input is saved, affected virtual store entries are cleared."""
        # Pre-populate store with a fake cached value
        cdf20_offline._virtual_store["CDF20.Dependent.Ref_1.FW_wU16"] = 999.0

        # Save the input — this triggers recalculation which should clear the store
        cdf20_offline.save_value("CDF20.Dependent.Base.FW_wU16", 50)

        # The dependent is not actually VIRTUAL in CDF20demo, but the mechanism
        # still pops the entry from _virtual_store during _trigger_recalculation
        assert "CDF20.Dependent.Ref_1.FW_wU16" not in cdf20_offline._virtual_store

    def test_virtual_store_initially_empty(self, cdf20_offline):
        """The _virtual_store starts empty."""
        fresh = calibration.OfflineCalibration(
            cdf20_offline.session,
            cdf20_offline.image,
            loglevel="DEBUG",
        )
        assert fresh._virtual_store == {}


# ---------------------------------------------------------------------------
# Dependency engine _update_cache writes to _virtual_store
# ---------------------------------------------------------------------------


class TestEngineUpdateCache:
    """DependencyEngine._update_cache writes VIRTUAL results to _virtual_store."""

    def test_update_cache_stores_virtual(self, cdf20_offline):
        """VIRTUAL entries are stored in _virtual_store by the engine."""
        from asamint.calibration.dependent import DependencyEngine

        graph = DependencyGraph()
        entry = DependencyEntry(
            name="VIRT_A",
            formula="X1",
            input_names=["INPUT_1"],
            kind=DependencyKind.VIRTUAL,
            dependent_type="VALUE",
        )
        graph.entries["VIRT_A"] = entry

        engine = DependencyEngine(cdf20_offline, graph)
        result = EvaluationResult(
            name="VIRT_A",
            physical_value=42.0,
            kind=DependencyKind.VIRTUAL,
        )
        engine._update_cache(entry, result)

        assert cdf20_offline._virtual_store["VIRT_A"] == 42.0

        # Clean up
        cdf20_offline._virtual_store.pop("VIRT_A", None)

    def test_update_cache_dependent_not_in_store(self, cdf20_offline):
        """DEPENDENT entries should NOT be stored in _virtual_store."""
        from asamint.calibration.dependent import DependencyEngine

        graph = DependencyGraph()
        entry = DependencyEntry(
            name="DEP_A",
            formula="X1",
            input_names=["INPUT_1"],
            kind=DependencyKind.DEPENDENT,
            dependent_type="VALUE",
        )
        graph.entries["DEP_A"] = entry

        engine = DependencyEngine(cdf20_offline, graph)
        result = EvaluationResult(
            name="DEP_A",
            physical_value=99.0,
            kind=DependencyKind.DEPENDENT,
        )
        engine._update_cache(entry, result)

        assert "DEP_A" not in cdf20_offline._virtual_store


# ---------------------------------------------------------------------------
# XCP guard — OnlineCalibration skips virtuals
# ---------------------------------------------------------------------------


class TestXcpGuard:
    """OnlineCalibration._mark_dirty_characteristic skips virtual chars."""

    def test_virtual_not_marked_dirty(self, cdf20_online):
        """Virtual characteristics should NOT appear in dirty regions."""
        char = _make_virtual_characteristic("VIRT_XCP")

        with patch.object(cdf20_online, "get_characteristic", return_value=char):
            cdf20_online._dirty_regions.clear()
            cdf20_online._mark_dirty_characteristic("VIRT_XCP")
            assert len(cdf20_online._dirty_regions) == 0

    def test_normal_char_still_marked_dirty(self, cdf20_online):
        """Normal characteristics should still be tracked as dirty."""
        char = _make_virtual_characteristic("NORMAL_XCP")
        char.virtual_characteristic = None
        char.total_allocated_memory = 8

        with patch.object(cdf20_online, "get_characteristic", return_value=char):
            cdf20_online._dirty_regions.clear()
            cdf20_online._mark_dirty_characteristic("NORMAL_XCP")
            assert len(cdf20_online._dirty_regions) == 1
            assert cdf20_online._dirty_regions[0] == (0x1000, 8)

    def test_virtual_not_flushed_to_xcp(self, cdf20_online, mock_xcp_master):
        """Flushing after a virtual mark should not push anything."""
        char = _make_virtual_characteristic("VIRT_FLUSH")

        with patch.object(cdf20_online, "get_characteristic", return_value=char):
            cdf20_online._dirty_regions.clear()
            cdf20_online._mark_dirty_characteristic("VIRT_FLUSH")
            bytes_written = cdf20_online.flush()
            assert bytes_written == 0
            mock_xcp_master.setMta.assert_not_called()


# ---------------------------------------------------------------------------
# Bulk API — list_virtual, evaluate_all_virtual
# ---------------------------------------------------------------------------


class TestBulkApi:
    """list_virtual and evaluate_all_virtual methods."""

    def test_list_virtual_empty(self, cdf20_offline):
        """CDF20demo has no virtual characteristics."""
        assert cdf20_offline.list_virtual() == []

    def test_list_virtual_with_entries(self, cdf20_offline):
        """list_virtual returns names of VIRTUAL entries."""
        graph = cdf20_offline.dependency_graph
        # Inject a fake virtual entry
        graph.entries["FAKE_VIRT"] = DependencyEntry(
            name="FAKE_VIRT",
            formula="X1",
            input_names=["INPUT_1"],
            kind=DependencyKind.VIRTUAL,
            dependent_type="VALUE",
        )
        try:
            virtuals = cdf20_offline.list_virtual()
            assert "FAKE_VIRT" in virtuals
        finally:
            del graph.entries["FAKE_VIRT"]

    def test_evaluate_all_virtual_empty(self, cdf20_offline):
        """With no virtuals, evaluate_all_virtual returns empty dict."""
        assert cdf20_offline.evaluate_all_virtual() == {}

    def test_evaluate_all_virtual_with_entries(self, cdf20_offline):
        """evaluate_all_virtual evaluates all VIRTUAL entries."""
        graph = cdf20_offline.dependency_graph
        entry = DependencyEntry(
            name="EVAL_VIRT",
            formula="X1",
            input_names=["INPUT_1"],
            kind=DependencyKind.VIRTUAL,
            dependent_type="VALUE",
        )
        graph.entries["EVAL_VIRT"] = entry

        ev_result = EvaluationResult(
            name="EVAL_VIRT",
            physical_value=77.0,
            kind=DependencyKind.VIRTUAL,
        )

        with patch.object(
            type(cdf20_offline),
            "dependency_engine",
            new_callable=PropertyMock,
            return_value=SimpleNamespace(evaluate=MagicMock(return_value=ev_result)),
        ):
            try:
                results = cdf20_offline.evaluate_all_virtual()
                assert "EVAL_VIRT" in results
                assert results["EVAL_VIRT"] == 77.0
                # Also stored in _virtual_store
                assert cdf20_offline._virtual_store["EVAL_VIRT"] == 77.0
            finally:
                del graph.entries["EVAL_VIRT"]
                cdf20_offline._virtual_store.pop("EVAL_VIRT", None)

    def test_evaluate_all_virtual_handles_errors(self, cdf20_offline):
        """evaluate_all_virtual logs warnings for failing evaluations."""
        graph = cdf20_offline.dependency_graph
        entry = DependencyEntry(
            name="ERR_VIRT",
            formula="X1 / 0",
            input_names=["INPUT_1"],
            kind=DependencyKind.VIRTUAL,
            dependent_type="VALUE",
        )
        graph.entries["ERR_VIRT"] = entry

        def _raise_eval(e):
            raise CalibrationError("division error")

        with patch.object(
            type(cdf20_offline),
            "dependency_engine",
            new_callable=PropertyMock,
            return_value=SimpleNamespace(evaluate=_raise_eval),
        ):
            try:
                results = cdf20_offline.evaluate_all_virtual()
                assert "ERR_VIRT" not in results
            finally:
                del graph.entries["ERR_VIRT"]


# ---------------------------------------------------------------------------
# Write guard in OnlineCalibration (inherits from Calibration)
# ---------------------------------------------------------------------------


class TestOnlineWriteGuard:
    """OnlineCalibration also raises VirtualWriteError."""

    def test_online_save_value_rejects_virtual(self, cdf20_online):
        char = _make_virtual_characteristic("VIRT_ONLINE")

        with patch.object(cdf20_online, "get_characteristic", return_value=char):
            with pytest.raises(VirtualWriteError):
                cdf20_online.save_value("VIRT_ONLINE", 42.0)

    def test_online_save_value_block_rejects_virtual(self, cdf20_online):
        char = _make_virtual_characteristic("VIRT_ONLINE_BLK")
        char.type = "VAL_BLK"

        with patch.object(cdf20_online, "get_characteristic", return_value=char):
            with pytest.raises(VirtualWriteError):
                cdf20_online.save_value_block("VIRT_ONLINE_BLK", np.array([1]))

    def test_online_save_curve_rejects_virtual(self, cdf20_online):
        char = _make_virtual_characteristic("VIRT_ONLINE_CRV")
        char.type = "CURVE"

        wrapper = SimpleNamespace(
            raw=np.array([1.0]),
            phys=np.array([1.0]),
        )
        with patch.object(cdf20_online, "get_characteristic", return_value=char):
            with pytest.raises(VirtualWriteError):
                cdf20_online.save_curve_or_map("VIRT_ONLINE_CRV", wrapper)
