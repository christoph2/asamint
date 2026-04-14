#!/usr/bin/env python
"""Tests for asamint.damos.dcm_listener – BaseListener helpers and Dcm20Listener.exit* methods."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from asamint.damos.dcm_listener import BaseListener, Dcm20Listener

# ---------------------------------------------------------------------------
# Helpers – build listener instances without full ANTLR setup
# ---------------------------------------------------------------------------


class _BL(BaseListener):
    """BaseListener with minimal initialisation for unit tests."""

    def __init__(self) -> None:  # noqa: D107
        # Skip super().__init__() to avoid Logger setup; set logger manually
        self.logger = MagicMock()


class _DL(Dcm20Listener):
    """Dcm20Listener with minimal initialisation for unit tests."""

    def __init__(self) -> None:  # noqa: D107
        self.logger = MagicMock()


@pytest.fixture
def bl() -> _BL:
    return _BL()


@pytest.fixture
def dl() -> _DL:
    return _DL()


def _ns(**kw):
    return SimpleNamespace(**kw)


def _phys(v):
    return SimpleNamespace(phys=v)


# ---------------------------------------------------------------------------
# BaseListener.getList
# ---------------------------------------------------------------------------


def test_getlist_none_returns_empty(bl: _BL) -> None:
    assert bl.getList(None) == []


def test_getlist_empty_list(bl: _BL) -> None:
    assert bl.getList([]) == []


def test_getlist_extracts_phys(bl: _BL) -> None:
    items = [_phys(1), _phys(2), _phys(3)]
    assert bl.getList(items) == [1, 2, 3]


def test_getlist_string_phys(bl: _BL) -> None:
    assert bl.getList([_phys("a"), _phys("b")]) == ["a", "b"]


# ---------------------------------------------------------------------------
# BaseListener.getTerminal
# ---------------------------------------------------------------------------


def test_getterminal_callable_returns_text(bl: _BL) -> None:
    tok = MagicMock()
    tok.getText.return_value = "hello"
    # attr must be a callable that returns the token object
    assert bl.getTerminal(lambda: tok) == "hello"


def test_getterminal_none_callable_returns_empty(bl: _BL) -> None:
    assert bl.getTerminal(lambda: None) == ""


# ---------------------------------------------------------------------------
# BaseListener.getText
# ---------------------------------------------------------------------------


def test_gettext_with_attr(bl: _BL) -> None:
    assert bl.getText(_ns(text="world")) == "world"


def test_gettext_none_returns_empty(bl: _BL) -> None:
    assert bl.getText(None) == ""


# ---------------------------------------------------------------------------
# BaseListener.getNT
# ---------------------------------------------------------------------------


def test_getnt_returns_phys(bl: _BL) -> None:
    assert bl.getNT(_phys(42)) == 42


def test_getnt_none_returns_none(bl: _BL) -> None:
    assert bl.getNT(None) is None


def test_getnt_zero_phys(bl: _BL) -> None:
    assert bl.getNT(_phys(0)) == 0


# ---------------------------------------------------------------------------
# BaseListener.exitIntegerValue
# ---------------------------------------------------------------------------


def test_exit_integer_value(bl: _BL) -> None:
    ctx = _ns(i=_ns(text="42"))
    bl.exitIntegerValue(ctx)
    assert ctx.phys == 42


def test_exit_integer_value_negative(bl: _BL) -> None:
    ctx = _ns(i=_ns(text="-7"))
    bl.exitIntegerValue(ctx)
    assert ctx.phys == -7


# ---------------------------------------------------------------------------
# BaseListener.exitRealzahl
# ---------------------------------------------------------------------------


def test_exit_realzahl_float_branch(bl: _BL) -> None:
    ctx = _ns(f=_ns(text="3.14"), i=None)
    bl.exitRealzahl(ctx)
    assert ctx.phys == Decimal("3.14")


def test_exit_realzahl_integer_branch(bl: _BL) -> None:
    ctx = _ns(f=None, i=_ns(text="7"))
    bl.exitRealzahl(ctx)
    assert ctx.phys == Decimal("7")


def test_exit_realzahl_neither_none(bl: _BL) -> None:
    ctx = _ns(f=None, i=None)
    bl.exitRealzahl(ctx)
    assert ctx.phys is None


def test_exit_realzahl_negative_decimal(bl: _BL) -> None:
    ctx = _ns(f=_ns(text="-1.5"), i=None)
    bl.exitRealzahl(ctx)
    assert ctx.phys == Decimal("-1.5")


# ---------------------------------------------------------------------------
# BaseListener.exitTextValue
# ---------------------------------------------------------------------------


def test_exit_text_value_strips_quotes(bl: _BL) -> None:
    ctx = _ns(t=_ns(text='"hello"'))
    bl.exitTextValue(ctx)
    assert ctx.phys == "hello"


def test_exit_text_value_none_t(bl: _BL) -> None:
    ctx = _ns(t=None)
    bl.exitTextValue(ctx)
    assert ctx.phys is None


def test_exit_text_value_no_quotes(bl: _BL) -> None:
    ctx = _ns(t=_ns(text="bare"))
    bl.exitTextValue(ctx)
    assert ctx.phys == "bare"


# ---------------------------------------------------------------------------
# BaseListener.exitNameValue
# ---------------------------------------------------------------------------


def test_exit_name_value(bl: _BL) -> None:
    ctx = _ns(n=_ns(text="MyName"))
    bl.exitNameValue(ctx)
    assert ctx.phys == "MyName"


def test_exit_name_value_none(bl: _BL) -> None:
    ctx = _ns(n=None)
    bl.exitNameValue(ctx)
    assert ctx.phys is None


# ---------------------------------------------------------------------------
# BaseListener._formatMessage
# ---------------------------------------------------------------------------


def test_format_message(bl: _BL) -> None:
    loc = _ns(start=_ns(line=5, column=2))
    result = bl._formatMessage("something went wrong", loc)
    assert result == "[5:3] something went wrong"


# ---------------------------------------------------------------------------
# Dcm20Listener.exitFile_format
# ---------------------------------------------------------------------------


def test_exit_file_format_with_version(dl: _DL) -> None:
    ctx = _ns(version=_ns(text="2.0"))
    dl.exitFile_format(ctx)
    assert ctx.phys == 2.0


def test_exit_file_format_none_version(dl: _DL) -> None:
    ctx = _ns(version=None)
    dl.exitFile_format(ctx)
    assert ctx.phys == {}


# ---------------------------------------------------------------------------
# Dcm20Listener.exitMod_zeile
# ---------------------------------------------------------------------------


def test_exit_mod_zeile(dl: _DL) -> None:
    ctx = _ns(anf=_phys("start"), fort=[_phys("a"), _phys("b")])
    dl.exitMod_zeile(ctx)
    assert ctx.phys == {"anf": "start", "fort": ["a", "b"]}


def test_exit_mod_zeile_empty_fort(dl: _DL) -> None:
    ctx = _ns(anf=_phys("x"), fort=None)
    dl.exitMod_zeile(ctx)
    assert ctx.phys["fort"] == []


# ---------------------------------------------------------------------------
# Dcm20Listener.exitMod_anf_zeile
# ---------------------------------------------------------------------------


def test_exit_mod_anf_zeile(dl: _DL) -> None:
    ctx = _ns(n=_phys("KEY"), w=_phys("VALUE"))
    dl.exitMod_anf_zeile(ctx)
    assert ctx.phys == {"name": "KEY", "wert": "VALUE"}


# ---------------------------------------------------------------------------
# Dcm20Listener.exitMod_fort_zeile
# ---------------------------------------------------------------------------


def test_exit_mod_fort_zeile(dl: _DL) -> None:
    ctx = _ns(w=_phys("continuation"))
    dl.exitMod_fort_zeile(ctx)
    assert ctx.phys == "continuation"


# ---------------------------------------------------------------------------
# Dcm20Listener.exitFunktionszeile
# ---------------------------------------------------------------------------


def test_exit_funktionszeile(dl: _DL) -> None:
    ctx = _ns(n=_phys("FuncA"), v=_phys("1.0"), l=_phys("Long Name"))
    dl.exitFunktionszeile(ctx)
    assert ctx.phys == {"name": "FuncA", "version": "1.0", "langname": "Long Name"}


def test_exit_funktionszeile_missing_optional(dl: _DL) -> None:
    ctx = _ns(n=_phys("FuncB"), v=None, l=None)
    dl.exitFunktionszeile(ctx)
    assert ctx.phys["name"] == "FuncB"
    assert ctx.phys["version"] is None
    assert ctx.phys["langname"] is None


# ---------------------------------------------------------------------------
# Dcm20Listener.exitVariantenkrit
# ---------------------------------------------------------------------------


def test_exit_variantenkrit(dl: _DL) -> None:
    ctx = _ns(n=_phys("Kriterium1"), w=[_phys("v1"), _phys("v2")])
    dl.exitVariantenkrit(ctx)
    assert ctx.phys == {"name": "Kriterium1", "werte": ["v1", "v2"]}


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKennwert (REAL and TEXT)
# ---------------------------------------------------------------------------


def test_exit_kennwert_real(dl: _DL) -> None:
    ctx = _ns(
        r=_phys(Decimal("3.14")),
        t=None,
        n=_phys("Param1"),
        info=_phys({"langname": "My Param"}),
        ew=_phys("rpm"),
    )
    dl.exitKennwert(ctx)
    assert ctx.phys["category"] == "REAL"
    assert ctx.phys["name"] == "Param1"
    assert ctx.phys["realzahl"] == Decimal("3.14")
    assert ctx.phys["einheit_w"] == "rpm"


def test_exit_kennwert_text(dl: _DL) -> None:
    ctx = _ns(r=None, t=_phys("hello"), n=_phys("TxtParam"), info=None, ew=None)
    dl.exitKennwert(ctx)
    assert ctx.phys["category"] == "TEXT"
    assert ctx.phys["text"] == "hello"


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKennwerteblock
# ---------------------------------------------------------------------------


def test_exit_kennwerteblock(dl: _DL) -> None:
    ctx = _ns(
        n=_phys("BLK1"),
        ax=_phys(4),
        ay=None,
        info=None,
        ew=_phys("V"),
        w=[_phys({"category": "WERT", "rs": [1.0], "ts": []})],
    )
    dl.exitKennwerteblock(ctx)
    assert ctx.phys["name"] == "BLK1"
    assert ctx.phys["anzahl_x"] == 4
    assert ctx.phys["anzahl_y"] == 0  # None → 0
    assert ctx.phys["einheit_w"] == "V"
    assert len(ctx.phys["werteliste_kwb"]) == 1


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKennlinie
# ---------------------------------------------------------------------------


def test_exit_kennlinie(dl: _DL) -> None:
    ctx = _ns(
        cat=_ns(text="KENNLINIE"),
        n=_phys("KL1"),
        ax=_phys(3),
        info=None,
        ex=_phys("rpm"),
        ew=_phys("Nm"),
        sst=[_phys(Decimal("0")), _phys(Decimal("1")), _phys(Decimal("2"))],
        wl=[_phys(Decimal("10")), _phys(Decimal("20")), _phys(Decimal("30"))],
    )
    dl.exitKennlinie(ctx)
    assert ctx.phys["category"] == "KENNLINIE"
    assert ctx.phys["name"] == "KL1"
    assert ctx.phys["anzahl_x"] == 3
    assert ctx.phys["einheit_x"] == "rpm"
    assert len(ctx.phys["sst_liste_x"]) == 3
    assert len(ctx.phys["werteliste"]) == 3


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKennfeld
# ---------------------------------------------------------------------------


def test_exit_kennfeld(dl: _DL) -> None:
    ctx = _ns(
        cat=_ns(text="KENNFELD"),
        n=_phys("KF1"),
        ax=_phys(2),
        ay=_phys(3),
        info=None,
        ex=_phys("rpm"),
        ey=_phys("bar"),
        ew=_phys("Nm"),
        sst=[_phys(Decimal("0")), _phys(Decimal("1"))],
        kf=_phys({"category": "REAL", "rs": [], "ts": []}),
    )
    dl.exitKennfeld(ctx)
    assert ctx.phys["category"] == "KENNFELD"
    assert ctx.phys["name"] == "KF1"
    assert ctx.phys["anzahl_x"] == 2
    assert ctx.phys["anzahl_y"] == 3
    assert ctx.phys["einheit_y"] == "bar"
    assert ctx.phys["kf_zeile_liste"] == {"category": "REAL", "rs": [], "ts": []}


# ---------------------------------------------------------------------------
# Dcm20Listener.exitGruppenstuetzstellen
# ---------------------------------------------------------------------------


def test_exit_gruppenstuetzstellen(dl: _DL) -> None:
    ctx = _ns(
        n=_phys("GST1"),
        nx=_phys(3),
        info=None,
        ex=_phys("rpm"),
        sl=[_phys(Decimal("0")), _phys(Decimal("500")), _phys(Decimal("1000"))],
    )
    dl.exitGruppenstuetzstellen(ctx)
    assert ctx.phys["name"] == "GST1"
    assert ctx.phys["anzahl_x"] == 3
    assert ctx.phys["einheit_x"] == "rpm"
    assert len(ctx.phys["sst_liste_x"]) == 3


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKenntext
# ---------------------------------------------------------------------------


def test_exit_kenntext(dl: _DL) -> None:
    ctx = _ns(n=_phys("TXT1"), info=None, t=_phys("some text"))
    dl.exitKenntext(ctx)
    assert ctx.phys == {"name": "TXT1", "info": None, "text": "some text"}


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKgr_info
# ---------------------------------------------------------------------------


def test_exit_kgr_info(dl: _DL) -> None:
    ctx = _ns(
        lname=_phys("Long Name"),
        dname=_phys("Display"),
        var=_phys(["v1"]),
        fkt=_phys(["f1"]),
    )
    dl.exitKgr_info(ctx)
    assert ctx.phys["langname"] == "Long Name"
    assert ctx.phys["displayname"] == "Display"
    assert ctx.phys["var_abhangigkeiten"] == ["v1"]
    assert ctx.phys["funktionszugehorigkeit"] == ["f1"]


# ---------------------------------------------------------------------------
# Dcm20Listener.exitDisplayname
# ---------------------------------------------------------------------------


def test_exit_displayname_name(dl: _DL) -> None:
    ctx = _ns(t=None, n=_phys("DISP_NAME"))
    dl.exitDisplayname(ctx)
    assert ctx.phys == {"name_value": "DISP_NAME", "text_value": None}


def test_exit_displayname_text(dl: _DL) -> None:
    ctx = _ns(t=_phys("My Label"), n=None)
    dl.exitDisplayname(ctx)
    assert ctx.phys == {"name_value": None, "text_value": "My Label"}


# ---------------------------------------------------------------------------
# Dcm20Listener.exitWerteliste_kwb
# ---------------------------------------------------------------------------


def test_exit_werteliste_kwb_wert_category(dl: _DL) -> None:
    ctx = _ns(r=[_phys(Decimal("1.0")), _phys(Decimal("2.0"))], t=None)
    dl.exitWerteliste_kwb(ctx)
    assert ctx.phys["category"] == "WERT"
    assert ctx.phys["rs"] == [Decimal("1.0"), Decimal("2.0")]


def test_exit_werteliste_kwb_text_category(dl: _DL) -> None:
    ctx = _ns(r=None, t=[_phys("low"), _phys("high")])
    dl.exitWerteliste_kwb(ctx)
    assert ctx.phys["category"] == "TEXT"
    assert ctx.phys["ts"] == ["low", "high"]


def test_exit_werteliste_kwb_empty_both(dl: _DL) -> None:
    ctx = _ns(r=[], t=[])
    dl.exitWerteliste_kwb(ctx)
    assert ctx.phys["category"] == "TEXT"  # empty rs → TEXT


# ---------------------------------------------------------------------------
# Dcm20Listener.exitSst_liste_x
# ---------------------------------------------------------------------------


def test_exit_sst_liste_x_real(dl: _DL) -> None:
    ctx = _ns(r=[_phys(Decimal("0")), _phys(Decimal("1"))], t=None)
    dl.exitSst_liste_x(ctx)
    assert ctx.phys["category"] == "REAL"
    assert len(ctx.phys["rs"]) == 2


def test_exit_sst_liste_x_text(dl: _DL) -> None:
    ctx = _ns(r=None, t=[_phys("lo"), _phys("hi")])
    dl.exitSst_liste_x(ctx)
    assert ctx.phys["category"] == "TEXT"
    assert ctx.phys["ts"] == ["lo", "hi"]


# ---------------------------------------------------------------------------
# Dcm20Listener.exitKf_zeile_liste / exitKf_zeile_liste_r / _tx
# ---------------------------------------------------------------------------


def test_exit_kf_zeile_liste_real(dl: _DL) -> None:
    ctx = _ns(r=[_phys(Decimal("3.0"))], t=[])
    dl.exitKf_zeile_liste(ctx)
    assert ctx.phys["category"] == "REAL"


def test_exit_kf_zeile_liste_text(dl: _DL) -> None:
    ctx = _ns(r=[], t=[_phys("a")])
    dl.exitKf_zeile_liste(ctx)
    assert ctx.phys["category"] == "TEXT"


def test_exit_kf_zeile_liste_r(dl: _DL) -> None:
    ctx = _ns(
        r=_phys(Decimal("5.0")),
        w=[_phys(Decimal("1.0")), _phys(Decimal("2.0"))],
    )
    dl.exitKf_zeile_liste_r(ctx)
    assert ctx.phys["realzahl"] == Decimal("5.0")
    assert ctx.phys["werteliste"] == [Decimal("1.0"), Decimal("2.0")]


def test_exit_kf_zeile_liste_tx(dl: _DL) -> None:
    ctx = _ns(t=_phys("row_label"), w=[_phys(Decimal("10.0"))])
    dl.exitKf_zeile_liste_tx(ctx)
    assert ctx.phys["text"] == "row_label"
    assert ctx.phys["werteliste"] == [Decimal("10.0")]


# ---------------------------------------------------------------------------
# Dcm20Listener.exitAnzahl_x / exitAnzahl_y
# ---------------------------------------------------------------------------


def test_exit_anzahl_x(dl: _DL) -> None:
    ctx = _ns(i=_phys(5))
    dl.exitAnzahl_x(ctx)
    assert ctx.phys == 5


def test_exit_anzahl_y(dl: _DL) -> None:
    ctx = _ns(i=_phys(3))
    dl.exitAnzahl_y(ctx)
    assert ctx.phys == 3


# ---------------------------------------------------------------------------
# Dcm20Listener.exitWerteliste
# ---------------------------------------------------------------------------


def test_exit_werteliste(dl: _DL) -> None:
    ctx = _ns(r=[_phys(Decimal("1.0")), _phys(Decimal("2.0")), _phys(Decimal("3.0"))])
    dl.exitWerteliste(ctx)
    assert ctx.phys == [Decimal("1.0"), Decimal("2.0"), Decimal("3.0")]


def test_exit_werteliste_empty(dl: _DL) -> None:
    ctx = _ns(r=None)
    dl.exitWerteliste(ctx)
    assert ctx.phys == []


# ---------------------------------------------------------------------------
# Dcm20Listener.exitEinheit_x / _y / _w
# ---------------------------------------------------------------------------


def test_exit_einheit_x(dl: _DL) -> None:
    ctx = _ns(t=_phys("rpm"))
    dl.exitEinheit_x(ctx)
    assert ctx.phys == "rpm"


def test_exit_einheit_y(dl: _DL) -> None:
    ctx = _ns(t=_phys("bar"))
    dl.exitEinheit_y(ctx)
    assert ctx.phys == "bar"


def test_exit_einheit_w(dl: _DL) -> None:
    ctx = _ns(t=_phys("Nm"))
    dl.exitEinheit_w(ctx)
    assert ctx.phys == "Nm"


# ---------------------------------------------------------------------------
# Dcm20Listener.exitLangname
# ---------------------------------------------------------------------------


def test_exit_langname(dl: _DL) -> None:
    ctx = _ns(t=_phys("Long description"))
    dl.exitLangname(ctx)
    assert ctx.phys == "Long description"


# ---------------------------------------------------------------------------
# Dcm20Listener.exitVar_abh / exitFunktionszugehorigkeit
# ---------------------------------------------------------------------------


def test_exit_var_abh(dl: _DL) -> None:
    ctx = _ns(n=_phys("Criterion_A"))
    dl.exitVar_abh(ctx)
    assert ctx.phys == "Criterion_A"


def test_exit_funktionszugehorigkeit(dl: _DL) -> None:
    ctx = _ns(n=[_phys("FuncA"), _phys("FuncB")])
    dl.exitFunktionszugehorigkeit(ctx)
    assert ctx.phys == ["FuncA", "FuncB"]


def test_exit_funktionszugehorigkeit_empty(dl: _DL) -> None:
    ctx = _ns(n=None)
    dl.exitFunktionszugehorigkeit(ctx)
    assert ctx.phys == []
