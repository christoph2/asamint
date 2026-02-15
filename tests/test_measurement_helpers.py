#!/usr/bin/env python
from pathlib import Path

import numpy as np
import numpy.testing as npt

from asamint.measurement import (
    _median_timebase,
    _merge_daq_csv_results,
    _parse_daq_csv,
    _prepare_daq_groups,
    _stride_for_ratio,
    _unique_names_from_groups,
)


def test_prepare_daq_groups_defaults_applied():
    groups = [{"name": "G1"}, {"name": "G2", "priority": 5}]
    result = _prepare_daq_groups(groups)
    assert result[0]["priority"] == 0
    assert result[0]["prescaler"] == 1
    assert result[1]["priority"] == 5
    assert result[1]["prescaler"] == 1


def test_unique_names_from_groups_de_duplicates():
    groups = [
        {"variables": ["a", "b", "a"]},
        {"variables": ["b", "c"]},
    ]
    assert _unique_names_from_groups(groups) == ["a", "b", "c"]


def test_stride_for_ratio_handles_near_match():
    assert _stride_for_ratio(100, 10) == 10
    assert _stride_for_ratio(101, 10) == 10
    assert _stride_for_ratio(0, 10) is None


def test_median_timebase_handles_timestamp_ns():
    ts = np.array([0, 1_000_000_000, 2_000_000_000], dtype=np.int64)
    assert _median_timebase("timestamp[ns]", ts) == 1_000_000_000.0
    assert _median_timebase("timestamp", ts) == 1_000_000_000.0


def test_merge_daq_csv_results_prefers_first_timestamps(tmp_path: Path):
    file1 = tmp_path / "a.csv"
    file1.write_text("timestamp,sig_a\n0,1\n1,2\n", encoding="utf-8")
    file2 = tmp_path / "b.csv"
    file2.write_text("timestamp,sig_b\n0,3\n1,4\n", encoding="utf-8")

    merged = _merge_daq_csv_results([file1, file2])

    npt.assert_array_equal(merged["TIMESTAMPS"], np.array([0.0, 1.0]))
    npt.assert_array_equal(merged["sig_a"], np.array([1.0, 2.0]))
    npt.assert_array_equal(merged["sig_b"], np.array([3.0, 4.0]))


def test_merge_daq_csv_results_synthesizes_timestamps(tmp_path: Path):
    file1 = tmp_path / "a.csv"
    file1.write_text("sig_a\n1\n2\n3\n", encoding="utf-8")

    merged = _merge_daq_csv_results([file1])

    npt.assert_array_equal(merged["TIMESTAMPS"], np.array([0.0, 1.0, 2.0]))
    npt.assert_array_equal(merged["sig_a"], np.array([1.0, 2.0, 3.0]))


def test_parse_daq_csv_handles_timestamps(tmp_path: Path):
    csv_file = tmp_path / "daq.csv"
    csv_file.write_text("timestamp,sig_a\n0,1\n1,2\n", encoding="utf-8")

    parsed = _parse_daq_csv(csv_file)

    npt.assert_array_equal(parsed["TIMESTAMPS"], np.array([0.0, 1.0]))
    npt.assert_array_equal(parsed["sig_a"], np.array([1.0, 2.0]))


def test_parse_daq_csv_handles_missing_timestamp(tmp_path: Path):
    csv_file = tmp_path / "daq_no_ts.csv"
    csv_file.write_text("sig_a\n1\n2\n", encoding="utf-8")

    parsed = _parse_daq_csv(csv_file)

    assert "TIMESTAMPS" not in parsed
    npt.assert_array_equal(parsed["sig_a"], np.array([1.0, 2.0]))
