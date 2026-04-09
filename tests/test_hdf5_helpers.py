#!/usr/bin/env python
"""Tests for asamint.measurement.hdf5 helper functions and HDF5Creator."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import h5py
import numpy as np
import numpy.testing as npt
import pytest

from asamint.measurement.hdf5 import (
    _annotate_daq_hdf5_metadata,
    _annotate_hdf5_root,
    _serialize_daq_lists,
    _write_hdf5,
)


# ---------------------------------------------------------------------------
# _write_hdf5
# ---------------------------------------------------------------------------


class TestWriteHdf5:
    def test_writes_data_and_meta(self, tmp_path: Path):
        h5 = tmp_path / "test.h5"
        data = {
            "TIMESTAMPS": np.array([0.0, 0.1, 0.2]),
            "signal_a": np.array([1.0, 2.0, 3.0]),
        }
        meta = {
            "signal_a": {"units": "V", "compu_method": "LINEAR", "sample_count": 3},
        }
        project = {"author": "Test", "project": "Demo"}
        _write_hdf5(h5, data, meta, project)

        with h5py.File(str(h5), "r") as hf:
            assert "timestamps" in hf
            npt.assert_array_equal(hf["timestamps"][:], data["TIMESTAMPS"])
            assert hf["timestamps"].attrs["description"] == "Relative timestamps in seconds"
            assert "signal_a" in hf
            npt.assert_array_equal(hf["signal_a"][:], data["signal_a"])
            assert hf["signal_a"].attrs["units"] == "V"
            assert hf["signal_a"].attrs["compu_method"] == "LINEAR"
            assert hf["signal_a"].attrs["sample_count"] == 3
            assert hf.attrs["author"] == "Test"

    def test_handles_no_timestamps(self, tmp_path: Path):
        h5 = tmp_path / "no_ts.h5"
        data = {"sig": np.array([1, 2])}
        _write_hdf5(h5, data, {}, {})
        with h5py.File(str(h5), "r") as hf:
            assert "timestamps" not in hf
            assert "sig" in hf

    def test_none_project_meta_values(self, tmp_path: Path):
        h5 = tmp_path / "none_meta.h5"
        _write_hdf5(h5, {"s": np.array([1])}, {}, {"author": None, "ok": "yes"})
        with h5py.File(str(h5), "r") as hf:
            assert hf.attrs["author"] == ""
            assert hf.attrs["ok"] == "yes"

    def test_empty_data(self, tmp_path: Path):
        h5 = tmp_path / "empty.h5"
        _write_hdf5(h5, {}, {}, {"author": "X"})
        with h5py.File(str(h5), "r") as hf:
            assert hf.attrs["author"] == "X"
            assert len(list(hf.keys())) == 0

    def test_missing_meta_keys_ignored(self, tmp_path: Path):
        h5 = tmp_path / "sparse.h5"
        data = {"sig": np.array([10, 20])}
        meta = {"sig": {}}
        _write_hdf5(h5, data, meta, {})
        with h5py.File(str(h5), "r") as hf:
            assert "units" not in hf["sig"].attrs
            assert "compu_method" not in hf["sig"].attrs


# ---------------------------------------------------------------------------
# _annotate_hdf5_root
# ---------------------------------------------------------------------------


class TestAnnotateHdf5Root:
    def test_appends_metadata_to_existing(self, tmp_path: Path):
        h5 = tmp_path / "existing.h5"
        with h5py.File(str(h5), "w") as hf:
            hf.attrs["original"] = "yes"

        _annotate_hdf5_root(h5, {"author": "New"})
        with h5py.File(str(h5), "r") as hf:
            assert hf.attrs["original"] == "yes"
            assert hf.attrs["author"] == "New"

    def test_nonexistent_file_returns_silently(self, tmp_path: Path):
        h5 = tmp_path / "nonexistent.h5"
        _annotate_hdf5_root(h5, {"author": "Nobody"})
        assert not h5.exists()

    def test_none_meta_value_stored_as_empty(self, tmp_path: Path):
        h5 = tmp_path / "none_val.h5"
        with h5py.File(str(h5), "w") as hf:
            pass
        _annotate_hdf5_root(h5, {"k": None})
        with h5py.File(str(h5), "r") as hf:
            assert hf.attrs["k"] == ""


# ---------------------------------------------------------------------------
# _serialize_daq_lists
# ---------------------------------------------------------------------------


class TestSerializeDaqLists:
    def _make_daq(self, **kw) -> SimpleNamespace:
        defaults = {
            "name": "daq1",
            "event_num": 1,
            "stim": False,
            "enable_timestamps": True,
            "measurements": [("sig1", 0x100, 0, "U8")],
        }
        defaults.update(kw)
        return SimpleNamespace(**defaults)

    def test_basic_serialization(self):
        dl = self._make_daq()
        result = _serialize_daq_lists([dl])
        assert len(result) == 1
        entry = result[0]
        assert entry["name"] == "daq1"
        assert entry["event_num"] == 1
        assert entry["stim"] is False
        assert entry["enable_timestamps"] is True
        assert entry["measurements"] == ["sig1"]

    def test_empty_list(self):
        assert _serialize_daq_lists([]) == []

    def test_missing_attributes_skipped(self):
        broken = SimpleNamespace()  # no name, event_num, etc.
        result = _serialize_daq_lists([broken])
        assert result == []

    def test_multiple_daq_lists(self):
        dl1 = self._make_daq(name="fast", event_num=1)
        dl2 = self._make_daq(
            name="slow",
            event_num=2,
            stim=True,
            measurements=[("sig_a", 0, 0, "U16"), ("sig_b", 4, 0, "F32")],
        )
        result = _serialize_daq_lists([dl1, dl2])
        assert len(result) == 2
        assert result[1]["measurements"] == ["sig_a", "sig_b"]
        assert result[1]["stim"] is True


# ---------------------------------------------------------------------------
# _annotate_daq_hdf5_metadata
# ---------------------------------------------------------------------------


class TestAnnotateDaqHdf5Metadata:
    def test_writes_daq_config(self, tmp_path: Path):
        import json

        h5 = tmp_path / "daq.h5"
        with h5py.File(str(h5), "w") as hf:
            pass

        dl = SimpleNamespace(
            name="daq1",
            event_num=1,
            stim=False,
            enable_timestamps=True,
            measurements=[("sig1", 0x100, 0, "U8")],
        )
        _annotate_daq_hdf5_metadata(h5, [dl], {"author": "Tester"}, timebase_hint_s=0.01)

        with h5py.File(str(h5), "r") as hf:
            cfg = json.loads(hf.attrs["daq_config"])
            assert len(cfg) == 1
            assert cfg[0]["name"] == "daq1"
            assert hf.attrs["daq_timebase_hint_s"] == pytest.approx(0.01)
            assert hf.attrs["author"] == "Tester"

    def test_nonexistent_file_no_error(self, tmp_path: Path):
        h5 = tmp_path / "missing.h5"
        _annotate_daq_hdf5_metadata(h5, [], {})
        assert not h5.exists()

    def test_no_timebase_hint(self, tmp_path: Path):
        h5 = tmp_path / "no_hint.h5"
        with h5py.File(str(h5), "w") as hf:
            pass

        _annotate_daq_hdf5_metadata(h5, [], {"author": "X"}, timebase_hint_s=None)
        with h5py.File(str(h5), "r") as hf:
            assert "daq_timebase_hint_s" not in hf.attrs
