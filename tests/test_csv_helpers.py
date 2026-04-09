#!/usr/bin/env python
"""Tests for asamint.measurement.csv helper functions."""

from pathlib import Path

import numpy as np
import numpy.testing as npt
import pytest

from asamint.measurement.csv import (
    _csv_fieldnames,
    _fast_parse_daq_csv,
    _iter_csv_rows,
    _parse_daq_csv_python,
    _read_daq_csv_rows,
    _timestamp_index,
    _write_metadata_headers,
)


# ---------------------------------------------------------------------------
# _csv_fieldnames
# ---------------------------------------------------------------------------


class TestCsvFieldnames:
    def test_sorted_keys_with_timestamp_first(self):
        data = {"TIMESTAMPS": [1, 2], "z_sig": [0], "a_sig": [0]}
        assert _csv_fieldnames(data) == ["timestamp", "a_sig", "z_sig"]

    def test_empty_data(self):
        assert _csv_fieldnames({}) == ["timestamp"]

    def test_only_timestamps(self):
        assert _csv_fieldnames({"TIMESTAMPS": [1]}) == ["timestamp"]


# ---------------------------------------------------------------------------
# _write_metadata_headers
# ---------------------------------------------------------------------------


class TestWriteMetadataHeaders:
    def test_basic_header(self, tmp_path: Path):
        from io import StringIO

        fh = StringIO()
        _write_metadata_headers(fh, {"sig1": "V"}, None, None)
        text = fh.getvalue()
        assert "# asamint measurement" in text
        assert "# sig1 [V]" in text

    def test_project_meta_in_header(self):
        from io import StringIO

        fh = StringIO()
        meta = {"author": "Tester", "company": "ACME", "bogus": "ignored_key"}
        _write_metadata_headers(fh, {}, meta, None)
        text = fh.getvalue()
        assert "# author: Tester" in text
        assert "# company: ACME" in text
        # bogus is not in the accepted keys list
        assert "bogus" not in text

    def test_signal_metadata_in_header(self):
        from io import StringIO

        fh = StringIO()
        signal_meta = {"sig1": {"timebase_s": 0.01, "timestamp_source": "ts0", "group_id": 0}}
        _write_metadata_headers(fh, {"sig1": None}, None, signal_meta)
        text = fh.getvalue()
        assert "timebase:" in text
        assert "sig1" in text

    def test_unit_none_shows_bare_name(self):
        from io import StringIO

        fh = StringIO()
        _write_metadata_headers(fh, {"bare_sig": None}, None, None)
        text = fh.getvalue()
        assert "# bare_sig\n" in text

    def test_skips_empty_project_meta_values(self):
        from io import StringIO

        fh = StringIO()
        _write_metadata_headers(fh, {}, {"author": "", "company": None}, None)
        text = fh.getvalue()
        assert "author" not in text
        assert "company" not in text


# ---------------------------------------------------------------------------
# _iter_csv_rows
# ---------------------------------------------------------------------------


class TestIterCsvRows:
    def test_basic_iteration(self):
        ts = [0.0, 1.0, 2.0]
        data = {"a": [10, 20, 30], "b": [40, 50, 60]}
        rows = list(_iter_csv_rows(ts, ["a", "b"], data))
        assert len(rows) == 3
        assert rows[0] == [0.0, 10, 40]
        assert rows[2] == [2.0, 30, 60]

    def test_handles_index_error(self):
        ts = [0.0, 1.0, 2.0]
        data = {"short": [10]}  # only 1 element
        rows = list(_iter_csv_rows(ts, ["short"], data))
        assert rows[0] == [0.0, 10]
        assert rows[1] == [1.0, ""]  # IndexError → ""
        assert rows[2] == [2.0, ""]

    def test_handles_missing_key(self):
        ts = [0.0]
        rows = list(_iter_csv_rows(ts, ["missing"], {}))
        assert rows[0] == [0.0, ""]  # TypeError on None[0] → ""


# ---------------------------------------------------------------------------
# _read_daq_csv_rows
# ---------------------------------------------------------------------------


class TestReadDaqCsvRows:
    def test_reads_columns_and_data(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("timestamp,sig1\n0,1.5\n1,2.5\n", encoding="utf-8")
        cols, rows = _read_daq_csv_rows(f)
        assert cols == ["timestamp", "sig1"]
        assert len(rows) == 2
        assert rows[0] == ["0", "1.5"]

    def test_skips_comment_lines(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("# comment\n# another\ntimestamp,s\n0,1\n", encoding="utf-8")
        cols, rows = _read_daq_csv_rows(f)
        assert cols == ["timestamp", "s"]
        assert len(rows) == 1

    def test_skips_empty_lines(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("\n\ntimestamp,s\n\n0,1\n\n", encoding="utf-8")
        cols, rows = _read_daq_csv_rows(f)
        assert cols == ["timestamp", "s"]
        assert len(rows) == 1

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        cols, rows = _read_daq_csv_rows(f)
        assert cols == []
        assert rows == []


# ---------------------------------------------------------------------------
# _timestamp_index
# ---------------------------------------------------------------------------


class TestTimestampIndex:
    def test_finds_lowercase(self):
        assert _timestamp_index(["timestamp", "sig"]) == 0

    def test_finds_uppercase(self):
        assert _timestamp_index(["SIG", "TIMESTAMP"]) == 1

    def test_returns_none_for_no_match(self):
        assert _timestamp_index(["sig_a", "sig_b"]) is None

    def test_finds_time(self):
        assert _timestamp_index(["time", "val"]) == 0

    def test_finds_TIME(self):
        assert _timestamp_index(["val", "TIME"]) == 1


# ---------------------------------------------------------------------------
# _fast_parse_daq_csv
# ---------------------------------------------------------------------------


class TestFastParseDaqCsv:
    def test_parses_simple_csv(self, tmp_path: Path):
        f = tmp_path / "fast.csv"
        f.write_text("timestamp,sig\n0,1.0\n1,2.0\n2,3.0\n", encoding="utf-8")
        result = _fast_parse_daq_csv(f)
        assert result is not None
        assert "TIMESTAMPS" in result
        assert "sig" in result
        npt.assert_array_equal(result["sig"], [1.0, 2.0, 3.0])

    def test_returns_none_for_comment_prefixed(self, tmp_path: Path):
        f = tmp_path / "commented.csv"
        f.write_text("# asamint\ntimestamp,sig\n0,1\n", encoding="utf-8")
        assert _fast_parse_daq_csv(f) is None

    def test_returns_empty_for_empty_data(self, tmp_path: Path):
        f = tmp_path / "hdr_only.csv"
        f.write_text("timestamp,sig\n", encoding="utf-8")
        result = _fast_parse_daq_csv(f)
        # numpy.genfromtxt with no data rows → empty array
        assert result is not None
        assert result == {}


# ---------------------------------------------------------------------------
# _parse_daq_csv_python (fallback parser)
# ---------------------------------------------------------------------------


class TestParseDaqCsvPython:
    def test_parses_with_comments(self, tmp_path: Path):
        f = tmp_path / "commented.csv"
        f.write_text("# comment\ntimestamp,sig\n0,10\n1,20\n", encoding="utf-8")
        result = _parse_daq_csv_python(f)
        assert "TIMESTAMPS" in result
        npt.assert_array_equal(result["TIMESTAMPS"], [0.0, 1.0])
        npt.assert_array_equal(result["sig"], [10.0, 20.0])

    def test_returns_empty_for_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.csv"
        f.write_text("", encoding="utf-8")
        assert _parse_daq_csv_python(f) == {}

    def test_skips_non_numeric_values(self, tmp_path: Path):
        f = tmp_path / "mixed.csv"
        f.write_text("sig\n1.0\nnot_a_number\n3.0\n", encoding="utf-8")
        result = _parse_daq_csv_python(f)
        # non-numeric skipped, so only 2 values
        npt.assert_array_equal(result["sig"], [1.0, 3.0])

    def test_no_timestamp_column(self, tmp_path: Path):
        f = tmp_path / "no_ts.csv"
        f.write_text("sig_a,sig_b\n1,2\n3,4\n", encoding="utf-8")
        result = _parse_daq_csv_python(f)
        assert "TIMESTAMPS" not in result
        npt.assert_array_equal(result["sig_a"], [1.0, 3.0])
        npt.assert_array_equal(result["sig_b"], [2.0, 4.0])
