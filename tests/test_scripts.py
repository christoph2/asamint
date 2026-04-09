#!/usr/bin/env python
"""Tests for asamint.scripts — xcp_log and a2ldb_address_updater."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# a2ldb_address_updater.symbol_address
# ---------------------------------------------------------------------------


class TestSymbolAddress:
    """Unit tests for the pure helper ``symbol_address``."""

    def test_returns_st_value_when_symbol_exists(self):
        from asamint.scripts.a2ldb_address_updater import symbol_address

        sym = SimpleNamespace(st_value=0xDEAD_BEEF)
        elf = SimpleNamespace(symbols={"myVar": sym})
        assert symbol_address(elf, "myVar") == 0xDEAD_BEEF

    def test_returns_none_for_missing_symbol(self):
        from asamint.scripts.a2ldb_address_updater import symbol_address

        elf = SimpleNamespace(symbols={})
        assert symbol_address(elf, "noSuchVar") is None

    def test_returns_none_when_symbol_is_none(self):
        from asamint.scripts.a2ldb_address_updater import symbol_address

        elf = SimpleNamespace(symbols={"nil": None})
        assert symbol_address(elf, "nil") is None

    def test_multiple_symbols(self):
        from asamint.scripts.a2ldb_address_updater import symbol_address

        syms = {
            "alpha": SimpleNamespace(st_value=1),
            "beta": SimpleNamespace(st_value=2),
        }
        elf = SimpleNamespace(symbols=syms)
        assert symbol_address(elf, "alpha") == 1
        assert symbol_address(elf, "beta") == 2
        assert symbol_address(elf, "gamma") is None

    def test_zero_address(self):
        from asamint.scripts.a2ldb_address_updater import symbol_address

        sym = SimpleNamespace(st_value=0)
        elf = SimpleNamespace(symbols={"zeroAddr": sym})
        # 0 is falsy but should still be returned via the symbol object
        # The function checks `if sym:` so a SimpleNamespace is always truthy
        assert symbol_address(elf, "zeroAddr") == 0


# ---------------------------------------------------------------------------
# xcp_log.main — argument parsing and CSV export (mocked XcpLogFileReader)
# ---------------------------------------------------------------------------


class TestXcpLogMain:
    """Tests for xcp_log.main() with mocked XcpLogFileReader."""

    @pytest.fixture()
    def mock_reader_cls(self, monkeypatch):
        """Patch sys.modules to avoid the broken asamint.xcp.reco import chain."""
        import sys

        reader = MagicMock()
        reader.num_containers = 5
        reader.total_record_count = 100
        reader.total_size_uncompressed = 2048
        reader.total_size_compressed = 512
        reader.compression_ratio = 4.0
        reader.frames = []

        fake_reco = MagicMock()
        fake_reco.XcpLogFileReader = MagicMock(return_value=reader)
        monkeypatch.setitem(sys.modules, "asamint.xcp", MagicMock())
        monkeypatch.setitem(sys.modules, "asamint.xcp.reco", fake_reco)

        # Force re-import of xcp_log so it picks up the fake module
        if "asamint.scripts.xcp_log" in sys.modules:
            del sys.modules["asamint.scripts.xcp_log"]

        yield fake_reco.XcpLogFileReader, reader

    def test_prints_statistics(self, mock_reader_cls, capsys):
        cls_mock, reader = mock_reader_cls
        with patch("sys.argv", ["xcp_log", "data.xmraw"]):
            from asamint.scripts.xcp_log import main

            main()

        out = capsys.readouterr().out
        assert "5" in out
        assert "100" in out
        assert "4.000" in out
        cls_mock.assert_called_once_with("data.xmraw")

    def test_csv_export(self, mock_reader_cls, tmp_path):
        import binascii

        cls_mock, reader = mock_reader_cls
        frame_data = MagicMock()
        frame_data.tobytes.return_value = b"\x01\x02\x03"
        reader.frames = [
            (1, 0, 1000, frame_data),
            (2, 1, 2000, frame_data),
        ]
        csv_out = str(tmp_path / "out.csv")
        with patch("sys.argv", ["xcp_log", "data.xmraw", "-c", csv_out]):
            from asamint.scripts.xcp_log import main

            main()

        content = (tmp_path / "out.csv").read_text()
        assert "010203" in content
        lines = [line for line in content.strip().split("\n") if line]
        assert len(lines) == 2

    def test_no_csv_when_flag_omitted(self, mock_reader_cls, tmp_path, capsys):
        cls_mock, reader = mock_reader_cls
        with patch("sys.argv", ["xcp_log", "data.xmraw"]):
            from asamint.scripts.xcp_log import main

            main()

        out = capsys.readouterr().out
        # Should print stats but no "Writing frames" message
        assert "Writing frames" not in out
