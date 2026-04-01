#!/usr/bin/env python
"""Tests for asamint.compu (CompuMethods, Measurement, getCM)."""
from __future__ import annotations

from unittest.mock import MagicMock

import pya2l.model as model
import pytest

from asamint.compu import CompuMethods, Measurement, getCM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_cm(name: str, conversion_type: str = "IDENTICAL"):
    cm = MagicMock()
    cm.name = name
    cm.conversionType = conversion_type
    return cm


def _make_session(cm_list: list, conversions=None):
    """Build a mock SQLAlchemy session.

    query(model.CompuMethod).filter(...).all()  → cm_list
    query(model.CompuMethod).all()              → cm_list
    query(model.Measurement.conversion).filter(...).distinct() → conversions
    query(model.Measurement).filter(...).first() → cm_list[0] if any
    """
    mock_session = MagicMock()

    def _query(arg):
        q = MagicMock()
        if arg is model.CompuMethod:
            q.filter.return_value.all.return_value = cm_list
            q.all.return_value = cm_list
        else:
            # Measurement.conversion or Measurement queries
            q.filter.return_value.distinct.return_value = conversions or []
            q.filter.return_value.first.return_value = cm_list[0] if cm_list else None
            q.order_by.return_value.all.return_value = cm_list
        return q

    mock_session.query.side_effect = _query
    return mock_session


# ---------------------------------------------------------------------------
# CompuMethods – referenced=False
# ---------------------------------------------------------------------------


def test_compu_methods_unreferenced_len(capsys) -> None:
    cms = CompuMethods(_make_session([_mock_cm("A"), _mock_cm("B")]), referenced=False)
    assert len(cms) == 2
    capsys.readouterr()  # suppress print output


def test_compu_methods_unreferenced_getitem(capsys) -> None:
    cm_a = _mock_cm("Alpha")
    cms = CompuMethods(_make_session([cm_a]), referenced=False)
    assert cms["Alpha"] is cm_a
    capsys.readouterr()


def test_compu_methods_unreferenced_missing_key_raises(capsys) -> None:
    cms = CompuMethods(_make_session([_mock_cm("X")]), referenced=False)
    capsys.readouterr()
    with pytest.raises(KeyError):
        _ = cms["MISSING"]


def test_compu_methods_unreferenced_iter(capsys) -> None:
    cms = CompuMethods(_make_session([_mock_cm("A"), _mock_cm("B")]), referenced=False)
    capsys.readouterr()
    assert sorted(cms) == ["A", "B"]


def test_compu_methods_unreferenced_keys(capsys) -> None:
    cms = CompuMethods(
        _make_session([_mock_cm("M1"), _mock_cm("M2")]), referenced=False
    )
    capsys.readouterr()
    assert set(cms.keys()) == {"M1", "M2"}


def test_compu_methods_unreferenced_values(capsys) -> None:
    cm_a, cm_b = _mock_cm("A"), _mock_cm("B")
    cms = CompuMethods(_make_session([cm_a, cm_b]), referenced=False)
    capsys.readouterr()
    assert set(cms.values()) == {cm_a, cm_b}


def test_compu_methods_unreferenced_items(capsys) -> None:
    cm_a = _mock_cm("A")
    cms = CompuMethods(_make_session([cm_a]), referenced=False)
    capsys.readouterr()
    assert list(cms.items()) == [("A", cm_a)]


def test_compu_methods_empty(capsys) -> None:
    cms = CompuMethods(_make_session([]), referenced=False)
    capsys.readouterr()
    assert len(cms) == 0
    assert list(cms) == []


# ---------------------------------------------------------------------------
# CompuMethods – referenced=True (default)
# ---------------------------------------------------------------------------


def test_compu_methods_referenced_default(capsys) -> None:
    cm_a = _mock_cm("A")
    cms = CompuMethods(_make_session([cm_a]))
    capsys.readouterr()
    assert len(cms) == 1
    assert cms["A"] is cm_a


def test_compu_methods_referenced_multiple(capsys) -> None:
    items = [_mock_cm(f"CM{i}") for i in range(3)]
    cms = CompuMethods(_make_session(items))
    capsys.readouterr()
    assert len(cms) == 3
    assert sorted(cms.keys()) == ["CM0", "CM1", "CM2"]


# ---------------------------------------------------------------------------
# CompuMethods – all conversionType branches (just no crash)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "conv_type",
    [
        "IDENTICAL",
        "FORM",
        "LINEAR",
        "RAT_FUNC",
        "TAB_INTP",
        "TAB_NOINTP",
        "TAB_VERB",
        "UNKNOWN",
    ],
)
def test_compu_methods_conversion_type_no_crash(conv_type: str, capsys) -> None:
    cms = CompuMethods(_make_session([_mock_cm("CM", conv_type)]), referenced=False)
    capsys.readouterr()
    assert len(cms) == 1


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def test_measurement_stores_session() -> None:
    session = _make_session([])
    meas = Measurement(session, "SomeName")
    assert meas.session is session


def test_measurement_queries_by_name() -> None:
    mock_meas = MagicMock()
    mock_meas.name = "RPM"
    session = _make_session([mock_meas])
    meas = Measurement(session, "RPM")
    assert meas._meas is mock_meas


def test_measurement_not_found_returns_none() -> None:
    session = _make_session([])
    meas = Measurement(session, "NONEXISTENT")
    assert meas._meas is None


# ---------------------------------------------------------------------------
# getCM
# ---------------------------------------------------------------------------


def test_get_cm_no_compu_method_returns_none() -> None:
    session = MagicMock()
    result = getCM(session, "NO_COMPU_METHOD")
    assert result is None
    session.query.assert_not_called()


def test_get_cm_valid_name_queries_session() -> None:
    mock_cm = _mock_cm("MyConversion")
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = mock_cm
    result = getCM(session, "MyConversion")
    assert result is mock_cm


def test_get_cm_name_not_found_returns_none() -> None:
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    result = getCM(session, "Unknown")
    assert result is None


def test_get_cm_calls_query_with_compu_method(monkeypatch) -> None:
    """Verify getCM queries model.CompuMethod (not some other model)."""
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    getCM(session, "SomeName")
    session.query.assert_called_once_with(model.CompuMethod)
