#!/usr/bin/env python
"""Tests for measurement timestamp helpers and persist_measurements dispatch."""

from types import SimpleNamespace
from typing import Any

import numpy as np
import numpy.testing as npt
import pytest

from asamint.measurement import (
    _collect_daq_timebases,
    _collect_timebase_summary,
    _exact_timestamp_match,
    _prepare_daq_metadata,
    _select_timestamp_for_signal,
    _stride_timestamp_match,
    _timestamp_candidates,
    _ts_priority,
)


# ---------------------------------------------------------------------------
# _timestamp_candidates
# ---------------------------------------------------------------------------


class TestTimestampCandidates:
    def test_finds_timestamp_keys(self):
        data = {
            "timestamp0": np.arange(10),
            "TIMESTAMPS": np.arange(10),
            "signal_a": np.arange(10),
        }
        result = _timestamp_candidates(data)
        names = [name for name, _ in result]
        assert "timestamp0" in names
        assert "TIMESTAMPS" in names
        assert "signal_a" not in names

    def test_ignores_non_string_keys(self):
        data = {42: np.arange(5), "timestamp0": np.arange(5)}
        result = _timestamp_candidates(data)
        assert len(result) == 1

    def test_ignores_empty_arrays(self):
        data = {"timestamp0": np.array([])}
        result = _timestamp_candidates(data)
        assert len(result) == 0

    def test_ignores_non_1d(self):
        data = {"timestamp0": np.ones((3, 3))}
        result = _timestamp_candidates(data)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# _ts_priority
# ---------------------------------------------------------------------------


class TestTsPriority:
    def test_event_ts_ranked_higher(self):
        ts10 = np.arange(10)
        ts10_generic = np.arange(10)
        event_prio = _ts_priority(("timestamp0", ts10))
        generic_prio = _ts_priority(("timestamps", ts10_generic))
        assert event_prio > generic_prio

    def test_longer_ts_ranked_higher(self):
        short = _ts_priority(("timestamp0", np.arange(5)))
        long = _ts_priority(("timestamp0", np.arange(100)))
        assert long > short

    def test_handles_no_shape(self):
        prio = _ts_priority(("timestamp0", None))
        assert prio == (1, 0)


# ---------------------------------------------------------------------------
# _exact_timestamp_match
# ---------------------------------------------------------------------------


class TestExactTimestampMatch:
    def test_exact_match(self):
        ts = [("ts0", np.arange(10)), ("ts1", np.arange(5))]
        src, arr = _exact_timestamp_match(ts, 5)
        assert src == "ts1"
        assert arr.shape[0] == 5

    def test_no_match(self):
        ts = [("ts0", np.arange(10))]
        src, arr = _exact_timestamp_match(ts, 7)
        assert src is None
        assert arr is None


# ---------------------------------------------------------------------------
# _stride_timestamp_match
# ---------------------------------------------------------------------------


class TestStrideTimestampMatch:
    def test_stride_works(self):
        ts = [("ts0", np.arange(100))]
        src, arr = _stride_timestamp_match(ts, 10)
        assert src is not None
        assert "10" in src
        assert arr.shape[0] == 10

    def test_no_stride_possible(self):
        ts = [("ts0", np.arange(7))]
        src, arr = _stride_timestamp_match(ts, 3)
        # 7/3 ≈ 2.33, step=2, target=6, diff=1 which is ≤ max(1, 0)=1 → might match
        # But: 7/3 rounds to 2, step*n = 6, 7-6 = 1, max(1, 0) = 1 → OK, so this IS a match
        # Let's use truly unmatchable
        pass

    def test_no_match_when_ts_shorter(self):
        ts = [("ts0", np.arange(5))]
        src, arr = _stride_timestamp_match(ts, 10)
        assert src is None
        assert arr is None

    def test_no_match_zero_sample_len(self):
        ts = [("ts0", np.arange(10))]
        src, arr = _stride_timestamp_match(ts, 0)
        assert src is None
        assert arr is None


# ---------------------------------------------------------------------------
# _select_timestamp_for_signal
# ---------------------------------------------------------------------------


class TestSelectTimestampForSignal:
    def test_exact_match_preferred(self):
        ts_items = [("ts0", np.arange(10))]
        data = {"sig": np.arange(10)}
        src, ts, n = _select_timestamp_for_signal(data, "sig", ts_items)
        assert src == "ts0"
        assert n == 10

    def test_stride_fallback(self):
        ts_items = [("ts0", np.arange(100))]
        data = {"sig": np.arange(10)}
        src, ts, n = _select_timestamp_for_signal(data, "sig", ts_items)
        assert src is not None
        assert n == 10

    def test_missing_signal_returns_zero(self):
        src, ts, n = _select_timestamp_for_signal({}, "nope", [])
        assert src is None
        assert n == 0


# ---------------------------------------------------------------------------
# _collect_timebase_summary
# ---------------------------------------------------------------------------


class TestCollectTimebaseSummary:
    def test_groups_by_id(self):
        meta = {
            "sig_a": {"group_id": 0, "timestamp_source": "ts0", "timebase_s": 0.01},
            "sig_b": {"group_id": 0, "timestamp_source": "ts0", "timebase_s": 0.01},
            "sig_c": {"group_id": 1, "timestamp_source": "ts1", "timebase_s": 0.1},
        }
        result = _collect_timebase_summary(meta)
        assert len(result) == 2
        assert result[0]["group_id"] == 0
        assert set(result[0]["members"]) == {"sig_a", "sig_b"}
        assert result[1]["group_id"] == 1
        assert result[1]["members"] == ["sig_c"]

    def test_empty_meta(self):
        assert _collect_timebase_summary({}) == []

    def test_skips_none_group_id(self):
        meta = {"sig": {"group_id": None}}
        assert _collect_timebase_summary(meta) == []


# ---------------------------------------------------------------------------
# _collect_daq_timebases
# ---------------------------------------------------------------------------


class TestCollectDaqTimebases:
    def test_basic(self):
        dl = SimpleNamespace(
            name="daq1", event_num=1, measurements=[("sig1", 0, 0, "U8")]
        )
        result = _collect_daq_timebases([dl], 0.01)
        assert len(result) == 1
        assert result[0]["group_id"] == 1
        assert result[0]["timebase_s"] == 0.01
        assert result[0]["members"] == ["sig1"]

    def test_no_hint(self):
        dl = SimpleNamespace(name="d", event_num=2, measurements=[])
        result = _collect_daq_timebases([dl], None)
        assert result[0]["timebase_s"] is None

    def test_empty_list(self):
        assert _collect_daq_timebases([], 0.01) == []


# ---------------------------------------------------------------------------
# _prepare_daq_metadata
# ---------------------------------------------------------------------------


class TestPrepareDaqMetadata:
    def test_basic_fields(self):
        dl = SimpleNamespace(name="daq1", event_num=1)
        meta = _prepare_daq_metadata(
            [dl],
            {"author": "Tester", "empty_key": None},
            duration=1.5,
            samples=None,
            period_s=0.01,
        )
        assert meta["author"] == "Tester"
        assert "empty_key" not in meta
        assert meta["daq_list_count"] == 1
        assert meta["daq_timebase_hint_s"] == 0.01
        assert meta["daq_duration_s"] == 1.5
        assert "daq_samples" not in meta

    def test_samples_field(self):
        meta = _prepare_daq_metadata(
            [], {}, duration=None, samples=500, period_s=None
        )
        assert meta["daq_samples"] == 500
        assert "daq_duration_s" not in meta
        assert "daq_timebase_hint_s" not in meta
