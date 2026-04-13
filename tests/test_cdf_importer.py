#!/usr/bin/env python
"""Tests for asamint.cdf.importer.cdf_importer."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from asamint.cdf.importer.cdf_importer import CDFImporter, import_cdf_to_db

_MODULE = "asamint.cdf.importer.cdf_importer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(closed: bool = False) -> MagicMock:
    db = MagicMock()
    db._closed = closed
    return db


# ---------------------------------------------------------------------------
# import_cdf_to_db – success path
# ---------------------------------------------------------------------------


def test_import_returns_true_on_success() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        result = import_cdf_to_db("file.xml", "file.msrswdb")
    assert result is True


def test_import_creates_db_with_given_path() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db) as MockDB, patch(f"{_MODULE}.Parser"):
        import_cdf_to_db("data.xml", "out.msrswdb")
    MockDB.assert_called_once_with("out.msrswdb")


def test_import_calls_begin_transaction() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        import_cdf_to_db("x.xml", "x.db")
    db.begin_transaction.assert_called_once()


def test_import_creates_parser_with_xml_path() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser") as MockParser:
        import_cdf_to_db("path/to/file.xml", "out.db")
    MockParser.assert_called_once_with("path/to/file.xml", db)


def test_import_closes_db_after_success() -> None:
    db = _make_db(closed=False)
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        import_cdf_to_db("x.xml", "x.db")
    db.close.assert_called_once()


def test_import_does_not_close_already_closed_db() -> None:
    db = _make_db(closed=True)
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        import_cdf_to_db("x.xml", "x.db")
    db.close.assert_not_called()


def test_import_accepts_path_objects() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        result = import_cdf_to_db(Path("file.xml"), Path("file.db"))
    assert result is True


def test_import_uses_default_logger_when_none() -> None:
    db = _make_db()
    with (
        patch(f"{_MODULE}.MSRSWDatabase", return_value=db),
        patch(f"{_MODULE}.Parser"),
        patch(f"{_MODULE}.logging") as mock_logging,
    ):
        mock_logging.getLogger.return_value = MagicMock()
        import_cdf_to_db("x.xml", "x.db", logger=None)
    mock_logging.getLogger.assert_called_once_with(_MODULE)


def test_import_uses_provided_logger() -> None:
    db = _make_db()
    custom_logger = MagicMock(spec=logging.Logger)
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        import_cdf_to_db("x.xml", "x.db", logger=custom_logger)
    custom_logger.info.assert_called()


# ---------------------------------------------------------------------------
# import_cdf_to_db – failure path
# ---------------------------------------------------------------------------


def test_import_returns_false_on_parser_error() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser", side_effect=RuntimeError("parse error")):
        result = import_cdf_to_db("bad.xml", "out.db")
    assert result is False


def test_import_rolls_back_on_exception() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser", side_effect=ValueError("corrupt")):
        import_cdf_to_db("bad.xml", "out.db")
    db.rollback_transaction.assert_called_once()


def test_import_logs_error_on_exception() -> None:
    db = _make_db()
    custom_logger = MagicMock(spec=logging.Logger)
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser", side_effect=RuntimeError("oops")):
        import_cdf_to_db("bad.xml", "out.db", logger=custom_logger)
    custom_logger.error.assert_called_once()
    assert "oops" in custom_logger.error.call_args[0][0]


def test_import_closes_db_after_failure() -> None:
    db = _make_db(closed=False)
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser", side_effect=RuntimeError("fail")):
        import_cdf_to_db("bad.xml", "out.db")
    db.close.assert_called_once()


def test_import_no_rollback_on_success() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser"):
        import_cdf_to_db("x.xml", "x.db")
    db.rollback_transaction.assert_not_called()


def test_import_db_error_also_handled() -> None:
    db = _make_db()
    with patch(f"{_MODULE}.MSRSWDatabase", return_value=db), patch(f"{_MODULE}.Parser", side_effect=Exception("db error")):
        result = import_cdf_to_db("x.xml", "x.db")
    assert result is False


# ---------------------------------------------------------------------------
# CDFImporter
# ---------------------------------------------------------------------------


@pytest.fixture
def importer() -> CDFImporter:
    return CDFImporter()


def test_cdf_importer_default_logger(importer: CDFImporter) -> None:
    assert importer.logger is not None


def test_cdf_importer_custom_logger() -> None:
    custom = MagicMock(spec=logging.Logger)
    imp = CDFImporter(logger=custom)
    assert imp.logger is custom


def test_cdf_importer_import_file_delegates() -> None:
    imp = CDFImporter()
    with patch(f"{_MODULE}.import_cdf_to_db", return_value=True) as mock_fn:
        result = imp.import_file("file.xml", "file.db")
    mock_fn.assert_called_once_with("file.xml", "file.db", imp.logger)
    assert result is True


def test_cdf_importer_import_file_failure_propagates() -> None:
    imp = CDFImporter()
    with patch(f"{_MODULE}.import_cdf_to_db", return_value=False):
        result = imp.import_file("bad.xml", "out.db")
    assert result is False


def test_cdf_importer_import_file_path_objects() -> None:
    imp = CDFImporter()
    with patch(f"{_MODULE}.import_cdf_to_db", return_value=True) as mock_fn:
        imp.import_file(Path("a.xml"), Path("a.db"))
    mock_fn.assert_called_once_with(Path("a.xml"), Path("a.db"), imp.logger)
