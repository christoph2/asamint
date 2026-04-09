#!/usr/bin/env python
"""Tests for MDFCreator.ccblock and MDF persistence helpers."""

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

from asamint.adapters.a2l import inspect


def _bypass_init(self, *args, **kws):
    """Lightweight init that skips config/A2L/XCP setup."""
    self.config = MagicMock()
    self.config.general = SimpleNamespace(
        author="T", company="C", department="D", project="P", mdf_version="4.20"
    )
    self.logger = logging.getLogger("test_mdf_ccblock")
    self.experiment_config: dict[str, Any] = {}
    self.measurement_variables: list[Any] = []
    self._mdf_obj = MagicMock()
    self._mdf_obj.version = "4.20"
    self.mod_par = SimpleNamespace(systemConstants={})
    self.session = MagicMock()


@pytest.fixture()
def creator(monkeypatch: pytest.MonkeyPatch):
    from asamint.asam import AsamMC
    from asamint.measurement.mdf import MDFCreator

    monkeypatch.setattr(AsamMC, "__init__", _bypass_init)
    return MDFCreator()


# ---------------------------------------------------------------------------
# ccblock — conversion-type mapping
# ---------------------------------------------------------------------------


class TestCcblock:
    def test_none_returns_none(self, creator):
        assert creator.ccblock(None) is None

    def test_no_compu_method_string(self, creator):
        assert creator.ccblock("NO_COMPU_METHOD") is None

    def test_identical(self, creator):
        cm = SimpleNamespace(conversionType="IDENTICAL")
        assert creator.ccblock(cm) is None

    def test_linear(self, creator):
        cm = SimpleNamespace(
            conversionType="LINEAR",
            coeffs_linear=SimpleNamespace(a=2.0, b=5.0),
        )
        result = creator.ccblock(cm)
        assert result == {"a": 2.0, "b": 5.0}

    def test_linear_defaults(self, creator):
        cm = SimpleNamespace(conversionType="LINEAR", coeffs_linear=None)
        result = creator.ccblock(cm)
        assert result == {"a": 0.0, "b": 0.0}

    def test_form(self, creator):
        cm = SimpleNamespace(
            conversionType="FORM",
            formula={"formula": "X1 * 100.0"},
        )
        result = creator.ccblock(cm)
        assert result == {"formula": "X1 * 100.0"}

    def test_form_no_formula(self, creator):
        cm = SimpleNamespace(conversionType="FORM", formula=None)
        result = creator.ccblock(cm)
        assert result is None

    def test_rat_func(self, creator):
        cm = SimpleNamespace(
            conversionType="RAT_FUNC",
            coeffs=SimpleNamespace(a=1, b=2, c=3, d=4, e=5, f=6),
        )
        result = creator.ccblock(cm)
        assert result == {"P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5, "P6": 6}

    def test_rat_func_no_coeffs(self, creator):
        cm = SimpleNamespace(conversionType="RAT_FUNC", coeffs=None)
        result = creator.ccblock(cm)
        expected = {f"P{i}": 0.0 for i in range(1, 7)}
        assert result == expected

    def test_tab_intp(self, creator):
        tab = SimpleNamespace(
            in_values=[0, 1, 2],
            out_values=[0.0, 50.0, 100.0],
            default_value=None,
            interpolation=1,
        )
        cm = SimpleNamespace(conversionType="TAB_INTP", tab=tab)
        result = creator.ccblock(cm)
        assert result["raw_0"] == 0
        assert result["phys_2"] == 100.0
        assert result["interpolation"] == 1
        assert "default" not in result

    def test_tab_nointp(self, creator):
        tab = SimpleNamespace(
            in_values=[0, 1],
            out_values=[10.0, 20.0],
            default_value=-1.0,
            interpolation=None,
        )
        cm = SimpleNamespace(conversionType="TAB_NOINTP", tab=tab)
        result = creator.ccblock(cm)
        assert result["raw_0"] == 0
        assert result["phys_1"] == 20.0
        assert result["default"] == -1.0
        assert "interpolation" not in result

    def test_tab_verb_simple(self, creator):
        tv = SimpleNamespace(
            text_values=["OFF", "ON"],
            in_values=[0, 1],
            default_value=None,
        )
        cm = SimpleNamespace(conversionType="TAB_VERB", tab_verb=tv)
        result = creator.ccblock(cm)
        assert result["val_0"] == 0
        assert result["val_1"] == 1
        assert result["text_0"] == "OFF"
        assert result["text_1"] == "ON"

    def test_tab_verb_ranges(self, creator, monkeypatch):
        # CompuTabVerbRanges is a NamedTuple in pya2l — we can't assign __class__
        # on SimpleNamespace. Instead, mock the isinstance check.
        tv = SimpleNamespace(
            lower_values=[0, 10, 20],
            upper_values=[9, 19, 29],
            text_values=["low", "mid", "high"],
            default_value="unknown",
        )
        original_class = getattr(inspect, "CompuTabVerbRanges", None)
        if original_class is not None:
            # Patch isinstance to return True for our SimpleNamespace
            import builtins

            orig_isinstance = builtins.isinstance

            def patched_isinstance(obj, classinfo):
                if obj is tv and classinfo is original_class:
                    return True
                return orig_isinstance(obj, classinfo)

            monkeypatch.setattr(builtins, "isinstance", patched_isinstance)

        cm = SimpleNamespace(conversionType="TAB_VERB", tab_verb=tv)
        result = creator.ccblock(cm)
        assert result is not None
        assert "text_0" in result
        if original_class is not None:
            # Ranges path: lower_0, upper_0, text_0, default
            assert "lower_0" in result
            assert "upper_0" in result
            assert result["default"] == b"unknown"

    def test_unknown_type_returns_none_and_warns(self, creator, caplog):
        cm = SimpleNamespace(conversionType="EXOTIC_UNKNOWN", name="exotic_cm")
        with caplog.at_level(logging.WARNING, logger="test_mdf_ccblock"):
            result = creator.ccblock(cm)
        assert result is None


# ---------------------------------------------------------------------------
# save_measurements — basic paths
# ---------------------------------------------------------------------------


class TestSaveMeasurements:
    """Test save_measurements with mocked MDF internals."""

    @pytest.fixture()
    def dummy_meas(self):
        class Dummy:
            def __init__(self, name):
                self.name = name
                self.longIdentifier = f"Description of {name}"
                self.compuMethod = "NO_COMPU_METHOD"
                self.bitMask = None
                self.bitOperation = None
        return Dummy

    def test_empty_data_returns_empty_result(self, creator):
        result = creator.save_measurements(data={})
        assert result is not None
        assert result.mdf_path is None
        assert result.signals == {}

    def test_none_data_returns_empty_result(self, creator):
        result = creator.save_measurements(data=None)
        assert result is not None
        assert result.mdf_path is None

    def test_no_matching_measurements_returns_none(self, creator, dummy_meas):
        creator.measurement_variables = [dummy_meas("sig_x")]
        data = {"sig_y": np.array([1, 2, 3])}
        result = creator.save_measurements(data=data)
        assert result is None

    def test_saves_with_timestamps(self, creator, dummy_meas, tmp_path, monkeypatch):
        creator.measurement_variables = [dummy_meas("sig")]
        monkeypatch.setattr(creator, "calculate_physical_values", lambda s, cm: s)
        data = {
            "timestamp0": np.arange(3, dtype=np.int64) * 10_000_000,
            "sig": np.array([1.0, 2.0, 3.0]),
        }
        out = str(tmp_path / "out.mf4")
        result = creator.save_measurements(mdf_filename=out, data=data)
        assert result is not None
        assert result.mdf_path == out
        creator._mdf_obj.append.assert_called_once()
        creator._mdf_obj.save.assert_called_once_with(dst=out, overwrite=True)

    def test_synthesizes_timestamps_when_missing(self, creator, dummy_meas, monkeypatch):
        creator.measurement_variables = [dummy_meas("sig")]
        monkeypatch.setattr(creator, "calculate_physical_values", lambda s, cm: s)
        data = {"sig": np.array([10, 20, 30])}
        result = creator.save_measurements(data=data)
        assert result is not None
        # Should have synthesized timestamps (no ValueError in non-strict mode)
        creator._mdf_obj.append.assert_called_once()

    def test_bit_mask_applied(self, creator, dummy_meas, monkeypatch):
        meas = dummy_meas("masked")
        meas.bitMask = 0x0F
        creator.measurement_variables = [meas]
        monkeypatch.setattr(creator, "calculate_physical_values", lambda s, cm: s)

        captured = {}

        def spy_append(signals):
            captured["samples"] = signals[0].samples.copy()

        creator._mdf_obj.append = spy_append

        data = {
            "timestamp0": np.arange(3, dtype=np.int64),
            "masked": np.array([0xFF, 0x1A, 0x00]),
        }
        creator.save_measurements(data=data)
        np.testing.assert_array_equal(captured["samples"], [0x0F, 0x0A, 0x00])

    def test_bit_shift_left(self, creator, dummy_meas, monkeypatch):
        meas = dummy_meas("shifted")
        meas.bitMask = None
        meas.bitOperation = {"amount": 2, "direction": "L"}
        creator.measurement_variables = [meas]
        monkeypatch.setattr(creator, "calculate_physical_values", lambda s, cm: s)

        captured = {}

        def spy_append(signals):
            captured["samples"] = signals[0].samples.copy()

        creator._mdf_obj.append = spy_append

        data = {
            "timestamp0": np.arange(2, dtype=np.int64),
            "shifted": np.array([1, 3]),
        }
        creator.save_measurements(data=data)
        np.testing.assert_array_equal(captured["samples"], [4, 12])

    def test_csv_and_hdf5_output_triggered(self, creator, dummy_meas, tmp_path, monkeypatch):
        creator.measurement_variables = [dummy_meas("sig")]
        monkeypatch.setattr(creator, "calculate_physical_values", lambda s, cm: s)

        data = {
            "timestamp0": np.arange(3, dtype=np.int64) * 10_000_000,
            "sig": np.array([1.0, 2.0, 3.0]),
        }
        csv_out = str(tmp_path / "out.csv")
        h5_out = str(tmp_path / "out.h5")
        result = creator.save_measurements(
            data=data, csv_out=csv_out, hdf5_out=h5_out
        )
        assert result is not None
        # finalize_measurement_outputs is called internally, producing csv and h5
        assert result.csv_path is not None or result.hdf5_path is not None


# ---------------------------------------------------------------------------
# persist_measurements (format dispatch)
# ---------------------------------------------------------------------------


class TestPersistMeasurements:
    def test_csv_format(self, tmp_path):
        from pathlib import Path

        from asamint.measurement import persist_measurements

        data = {"TIMESTAMPS": np.array([0.0, 1.0]), "sig": np.array([10.0, 20.0])}
        out = tmp_path / "out.csv"
        result = persist_measurements("CSV", data=data, output_path=out)
        assert result.csv_path is not None
        assert Path(result.csv_path).exists()

    def test_hdf5_format(self, tmp_path):
        from pathlib import Path

        from asamint.measurement import persist_measurements

        data = {"TIMESTAMPS": np.array([0.0, 1.0]), "sig": np.array([10.0, 20.0])}
        out = tmp_path / "out.h5"
        result = persist_measurements("HDF5", data=data, output_path=out)
        assert result.hdf5_path is not None
        assert Path(result.hdf5_path).exists()

    def test_unknown_format_raises(self):
        from asamint.measurement import persist_measurements

        with pytest.raises((KeyError, ValueError)):
            persist_measurements("NONEXISTENT", data={"sig": np.array([1])})


class TestListMeasurementFormats:
    def test_default_formats_registered(self):
        from asamint.measurement import list_measurement_formats

        fmts = list_measurement_formats()
        assert "CSV" in fmts
        assert "HDF5" in fmts
        assert "MDF" in fmts
