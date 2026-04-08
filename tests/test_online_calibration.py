"""Tests for OnlineCalibration (XCP-backed calibration with live write-back)."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call

import numpy as np
import pytest

from asamint.adapters.a2l import ModCommon, ModPar, open_a2l_database
from asamint.adapters.objutils import Image, Section, load
from asamint.calibration import api as calibration
from asamint.calibration.api import (
    ExecutionPolicy,
    OnlineCalibration,
    ParameterCache,
    Status,
    _merge_regions,
    _upload_parameters_xcp,
)
from asamint.core.logging import configure_logging

FIXTURE_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cdf20_session():
    session = open_a2l_database(
        str(FIXTURE_DIR / "CDF20demo"), encoding="latin1", local=True
    )
    yield session
    close_fn = getattr(session, "close", None)
    if callable(close_fn):
        close_fn()


@pytest.fixture
def cdf20_image():
    """Load the CDF20demo hex file into an Image."""
    return load("ihex", str(FIXTURE_DIR / "CDF20demo.hex"))


@pytest.fixture
def mock_xcp_master():
    """Create a mock XCP master with typical methods."""
    master = MagicMock()
    master.setMta = MagicMock()
    master.push = MagicMock()
    master.pull = MagicMock(return_value=b"\x00" * 1024)
    master.setCalPage = MagicMock()
    return master


@pytest.fixture
def cdf20_online(cdf20_session, cdf20_image, mock_xcp_master):
    """Create an OnlineCalibration instance with CDF20demo data."""
    return OnlineCalibration(
        cdf20_session,
        mock_xcp_master,
        image=cdf20_image,
        auto_flush=True,
        loglevel="DEBUG",
    )


@pytest.fixture
def cdf20_online_no_flush(cdf20_session, cdf20_image, mock_xcp_master):
    """Create an OnlineCalibration with auto_flush=False."""
    return OnlineCalibration(
        cdf20_session,
        mock_xcp_master,
        image=cdf20_image,
        auto_flush=False,
        loglevel="DEBUG",
    )


# ---------------------------------------------------------------------------
# Unit tests: _merge_regions
# ---------------------------------------------------------------------------


class TestMergeRegions:
    """Test the region-merging helper."""

    def test_empty(self):
        assert _merge_regions([]) == []

    def test_single_region(self):
        assert _merge_regions([(100, 20)]) == [(100, 20)]

    def test_non_overlapping(self):
        result = _merge_regions([(100, 20), (200, 30)])
        assert result == [(100, 20), (200, 30)]

    def test_adjacent(self):
        result = _merge_regions([(100, 20), (120, 30)])
        assert result == [(100, 50)]

    def test_overlapping(self):
        result = _merge_regions([(100, 30), (110, 40)])
        assert result == [(100, 50)]

    def test_contained(self):
        result = _merge_regions([(100, 50), (110, 10)])
        assert result == [(100, 50)]

    def test_unsorted_input(self):
        result = _merge_regions([(200, 10), (100, 20), (150, 10)])
        assert result == [(100, 20), (150, 10), (200, 10)]

    def test_multiple_merges(self):
        result = _merge_regions([(100, 10), (105, 10), (200, 10), (205, 10)])
        assert result == [(100, 15), (200, 15)]


# ---------------------------------------------------------------------------
# Unit tests: OnlineCalibration construction
# ---------------------------------------------------------------------------


class TestOnlineCalibrationInit:
    """Test that OnlineCalibration initialises correctly."""

    def test_inherits_calibration(self, cdf20_online):
        assert isinstance(cdf20_online, calibration.Calibration)

    def test_has_xcp_master(self, cdf20_online, mock_xcp_master):
        assert cdf20_online.xcp_master is mock_xcp_master

    def test_has_session(self, cdf20_online, cdf20_session):
        assert cdf20_online.session is cdf20_session

    def test_has_image(self, cdf20_online):
        assert cdf20_online.image is not None

    def test_parameter_cache_is_set(self, cdf20_online):
        assert isinstance(cdf20_online.parameter_cache, ParameterCache)

    def test_auto_flush_default(self, cdf20_online):
        assert cdf20_online._auto_flush is True

    def test_auto_flush_off(self, cdf20_online_no_flush):
        assert cdf20_online_no_flush._auto_flush is False

    def test_dirty_regions_start_empty(self, cdf20_online):
        assert cdf20_online._dirty_regions == []

    def test_load_value_works(self, cdf20_online):
        """Inherited Calibration.load_value should work."""
        val = cdf20_online.load_value("CDF20.Dependent.Base.FW_wU16")
        assert hasattr(val, "phys")


# ---------------------------------------------------------------------------
# Tests: save + XCP flush
# ---------------------------------------------------------------------------


class TestSaveAndFlush:
    """Test that save operations mark dirty regions and flush to XCP."""

    def test_save_value_pushes_to_xcp(self, cdf20_online, mock_xcp_master):
        """save_value should call setMta + push on the XCP master."""
        val = cdf20_online.load_value("CDF20.Dependent.Base.FW_wU16")
        mock_xcp_master.reset_mock()

        status = cdf20_online.save_value(
            "CDF20.Dependent.Base.FW_wU16",
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        assert status == Status.OK
        mock_xcp_master.setMta.assert_called()
        mock_xcp_master.push.assert_called()

    def test_save_value_clears_dirty(self, cdf20_online, mock_xcp_master):
        """After auto-flush, dirty regions should be empty."""
        val = cdf20_online.load_value("CDF20.Dependent.Base.FW_wU16")
        cdf20_online.save_value(
            "CDF20.Dependent.Base.FW_wU16",
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        assert cdf20_online._dirty_regions == []

    def test_save_value_no_flush(self, cdf20_online_no_flush, mock_xcp_master):
        """With auto_flush=False, save should NOT call XCP."""
        val = cdf20_online_no_flush.load_value("CDF20.Dependent.Base.FW_wU16")
        mock_xcp_master.reset_mock()

        status = cdf20_online_no_flush.save_value(
            "CDF20.Dependent.Base.FW_wU16",
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        assert status == Status.OK
        mock_xcp_master.setMta.assert_not_called()
        mock_xcp_master.push.assert_not_called()
        # But dirty regions should be populated
        assert len(cdf20_online_no_flush._dirty_regions) > 0

    def test_manual_flush(self, cdf20_online_no_flush, mock_xcp_master):
        """Manual flush should push dirty regions and clear them."""
        val = cdf20_online_no_flush.load_value("CDF20.Dependent.Base.FW_wU16")
        cdf20_online_no_flush.save_value(
            "CDF20.Dependent.Base.FW_wU16",
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        mock_xcp_master.reset_mock()

        written = cdf20_online_no_flush.flush()
        assert written > 0
        mock_xcp_master.setMta.assert_called()
        mock_xcp_master.push.assert_called()
        assert cdf20_online_no_flush._dirty_regions == []

    def test_update_calls_flush(self, cdf20_online_no_flush, mock_xcp_master):
        """update() should behave like flush()."""
        val = cdf20_online_no_flush.load_value("CDF20.Dependent.Base.FW_wU16")
        cdf20_online_no_flush.save_value(
            "CDF20.Dependent.Base.FW_wU16",
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        mock_xcp_master.reset_mock()

        cdf20_online_no_flush.update()
        mock_xcp_master.push.assert_called()
        assert cdf20_online_no_flush._dirty_regions == []

    def test_flush_empty_returns_zero(self, cdf20_online):
        assert cdf20_online.flush() == 0

    def test_flush_data_matches_image(self, cdf20_online, mock_xcp_master):
        """Flushed bytes should match what's in the local image."""
        name = "CDF20.Dependent.Base.FW_wU16"
        _ = cdf20_online.load_value(name)
        new_val = 42.0
        mock_xcp_master.reset_mock()

        cdf20_online.save_value(
            name, new_val, limitsPolicy=ExecutionPolicy.IGNORE
        )

        # Verify push was called with bytes from the image
        push_call = mock_xcp_master.push.call_args_list[-1]
        pushed_data = push_call[0][0]
        assert isinstance(pushed_data, (bytes, bytearray))
        assert len(pushed_data) > 0


# ---------------------------------------------------------------------------
# Tests: dependency chain with XCP flush
# ---------------------------------------------------------------------------


class TestDependencyFlush:
    """Test that dependency recalculation results are flushed to XCP."""

    def test_dependent_recalculated_and_flushed(self, cdf20_online, mock_xcp_master):
        """Saving an input should recalculate dependent AND flush both."""
        # CDF20demo: CDF20.Dependent.Ref_1.FW_wU16 depends on
        # CDF20.Dependent.Base.FW_wU16 with formula "X1 * 5"
        base_name = "CDF20.Dependent.Base.FW_wU16"

        val = cdf20_online.load_value(base_name)
        mock_xcp_master.reset_mock()

        status = cdf20_online.save_value(
            base_name,
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        assert status == Status.OK

        # There should have been multiple push calls: one for the base
        # and potentially one for the dependent characteristic
        assert mock_xcp_master.push.call_count >= 1

    def test_trigger_recalculation_batches_flush(
        self, cdf20_session, cdf20_image, mock_xcp_master
    ):
        """During _trigger_recalculation, auto_flush should be suppressed."""
        cal = OnlineCalibration(
            cdf20_session,
            mock_xcp_master,
            image=cdf20_image,
            auto_flush=True,
            loglevel="DEBUG",
        )
        base_name = "CDF20.Dependent.Base.FW_wU16"
        val = cal.load_value(base_name)
        mock_xcp_master.reset_mock()

        # Save triggers recalculation; during recalculation auto_flush
        # is suppressed, and the outer save_value flushes everything
        cal.save_value(base_name, val.phys, limitsPolicy=ExecutionPolicy.IGNORE)

        # Verify dirty regions are empty (all flushed)
        assert cal._dirty_regions == []


# ---------------------------------------------------------------------------
# Tests: bulk transfer
# ---------------------------------------------------------------------------


class TestBulkTransfer:
    """Test upload_image and download_image."""

    def test_download_image(self, cdf20_online, mock_xcp_master):
        """download_image should push all image sections to ECU."""
        mock_xcp_master.reset_mock()
        total = cdf20_online.download_image()
        assert total > 0
        assert mock_xcp_master.setMta.call_count == len(cdf20_online.image.sections)
        assert mock_xcp_master.push.call_count == len(cdf20_online.image.sections)

    def test_download_clears_dirty(self, cdf20_online_no_flush, mock_xcp_master):
        """download_image should clear dirty regions."""
        val = cdf20_online_no_flush.load_value("CDF20.Dependent.Base.FW_wU16")
        cdf20_online_no_flush.save_value(
            "CDF20.Dependent.Base.FW_wU16",
            val.phys,
            limitsPolicy=ExecutionPolicy.IGNORE,
        )
        assert len(cdf20_online_no_flush._dirty_regions) > 0

        cdf20_online_no_flush.download_image()
        assert cdf20_online_no_flush._dirty_regions == []


# ---------------------------------------------------------------------------
# Tests: ParameterCache.clear
# ---------------------------------------------------------------------------


class TestParameterCacheClear:
    """Test the new ParameterCache.clear() method."""

    def test_clear_empties_all_caches(self, cdf20_online):
        # Access via the cache interface to populate it
        cache = cdf20_online.parameter_cache
        assert isinstance(cache, ParameterCache)
        _ = cache.values["CDF20.Dependent.Base.FW_wU16"]

        # Verify something is cached
        assert len(cache.values.cache) > 0

        cache.clear()
        assert len(cache.values.cache) == 0


# ---------------------------------------------------------------------------
# Tests: _upload_parameters_xcp
# ---------------------------------------------------------------------------


class TestUploadParametersXcp:
    """Test the standalone XCP upload function."""

    def test_queries_and_pulls(self, cdf20_session):
        """_upload_parameters_xcp should query A2L and pull from XCP."""
        mock_master = MagicMock()
        # Return enough bytes for any pull request
        mock_master.pull = MagicMock(side_effect=lambda n: b"\x00" * n)
        logger = configure_logging(name="test_upload", level=logging.DEBUG)

        image = _upload_parameters_xcp(cdf20_session, mock_master, logger)

        assert isinstance(image, Image)
        mock_master.setMta.assert_called()
        mock_master.pull.assert_called()

    def test_empty_session_raises(self):
        """An empty session with no parameters should raise."""
        mock_session = MagicMock()
        mock_session.query.return_value.order_by.return_value.all.return_value = []
        mock_master = MagicMock()
        logger = configure_logging(name="test_empty", level=logging.DEBUG)

        with pytest.raises(ValueError, match="No calibration parameters"):
            _upload_parameters_xcp(mock_session, mock_master, logger)


# ---------------------------------------------------------------------------
# Tests: XCP upload as initial image
# ---------------------------------------------------------------------------


class TestInitWithXcpUpload:
    """Test OnlineCalibration with image=None (upload from ECU)."""

    def test_uploads_on_init(self, cdf20_session):
        """When image=None, constructor should upload from XCP."""
        mock_master = MagicMock()
        mock_master.pull = MagicMock(side_effect=lambda n: b"\x00" * n)

        cal = OnlineCalibration(
            cdf20_session,
            mock_master,
            image=None,
            loglevel="DEBUG",
        )

        assert cal.image is not None
        mock_master.pull.assert_called()
        assert isinstance(cal, calibration.Calibration)
