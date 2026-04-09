#!/usr/bin/env python
"""Integration tests for DCM 2.0 import pipeline.

Tests the full parsing chain: DCM text → ANTLR lexer/parser → Dcm20Listener → dict.
Unit tests for individual exit* methods live in ``test_dcm_listener.py``.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from asamint.damos import import_dcm
from asamint.damos.dcm_listener import Dcm20Listener
from asamint.parserlib import ParserWrapper

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "asamint" / "examples"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse(text: str) -> dict:
    """Shortcut: parse DCM text and return the result dict."""
    return import_dcm(text)


def _rumpf(text: str) -> list:
    """Parse and return only the rumpf (body) entries."""
    return _parse(text).get("rumpf", [])


def _first(text: str, key: str):
    """Parse a single-entry DCM and return the given Kenngroesse key."""
    items = _rumpf(text)
    assert len(items) >= 1, "Expected at least one rumpf entry"
    return items[0][key]


# ---------------------------------------------------------------------------
# FESTWERT (scalar)
# ---------------------------------------------------------------------------

class TestFestwert:
    """Parse FESTWERT (scalar value) entries."""

    MINIMAL = """\
KONSERVIERUNG_FORMAT 2.0

FESTWERT MyParam
  EINHEIT_W "V"
  WERT 42.5
END
"""

    WITH_LANGNAME = """\
KONSERVIERUNG_FORMAT 2.0

FESTWERT Gain
  LANGNAME "Gain factor"
  EINHEIT_W "1/s"
  WERT 3.14
END
"""

    TEXT_VALUE = """\
KONSERVIERUNG_FORMAT 2.0

FESTWERT ModeSwitch
  EINHEIT_W "-"
  TEXT "ON"
END
"""

    def test_minimal_festwert(self) -> None:
        kw = _first(self.MINIMAL, "kw")
        assert kw is not None
        assert kw["name"] == "MyParam"
        assert kw["einheit_w"] == "V"
        assert kw["realzahl"] == Decimal("42.5")
        assert kw["category"] == "REAL"

    def test_festwert_with_langname(self) -> None:
        kw = _first(self.WITH_LANGNAME, "kw")
        assert kw["name"] == "Gain"
        assert kw["info"]["langname"] == "Gain factor"
        assert kw["einheit_w"] == "1/s"
        assert kw["realzahl"] == Decimal("3.14")

    def test_festwert_text(self) -> None:
        kw = _first(self.TEXT_VALUE, "kw")
        assert kw["category"] == "TEXT"
        assert kw["text"] == "ON"
        assert kw["realzahl"] is None


# ---------------------------------------------------------------------------
# FESTWERTEBLOCK (value block / array)
# ---------------------------------------------------------------------------

class TestFestwerteblock:
    """Parse FESTWERTEBLOCK entries."""

    BLOCK = """\
KONSERVIERUNG_FORMAT 2.0

FESTWERTEBLOCK MyBlock 4
  LANGNAME "Test Block"
  EINHEIT_W "V"
  WERT 10.0 20.0 30.0 40.0
END
"""

    def test_festwerteblock(self) -> None:
        kwb = _first(self.BLOCK, "kwb")
        assert kwb is not None
        assert kwb["name"] == "MyBlock"
        assert kwb["anzahl_x"] == 4
        assert kwb["info"]["langname"] == "Test Block"
        assert kwb["einheit_w"] == "V"
        wl = kwb["werteliste_kwb"]
        assert len(wl) == 1
        assert wl[0]["category"] == "WERT"
        assert wl[0]["rs"] == [Decimal("10.0"), Decimal("20.0"), Decimal("30.0"), Decimal("40.0")]


# ---------------------------------------------------------------------------
# KENNLINIE (curve)
# ---------------------------------------------------------------------------

class TestKennlinie:
    """Parse KENNLINIE entries."""

    CURVE = """\
KONSERVIERUNG_FORMAT 2.0

KENNLINIE MyCurve 3
  LANGNAME "Test Curve"
  EINHEIT_X "rpm"
  EINHEIT_W "V"
  ST/X 1000.0 2000.0 3000.0
  WERT 1.5 2.5 3.5
END
"""

    def test_kennlinie(self) -> None:
        kl = _first(self.CURVE, "kl")
        assert kl is not None
        assert kl["category"] == "KENNLINIE"
        assert kl["name"] == "MyCurve"
        assert kl["anzahl_x"] == 3
        assert kl["einheit_x"] == "rpm"
        assert kl["einheit_w"] == "V"
        sst = kl["sst_liste_x"]
        assert len(sst) == 1
        assert sst[0]["rs"] == [Decimal("1000.0"), Decimal("2000.0"), Decimal("3000.0")]
        wl = kl["werteliste"]
        assert len(wl) == 1
        assert wl[0] == [Decimal("1.5"), Decimal("2.5"), Decimal("3.5")]


# ---------------------------------------------------------------------------
# KENNFELD (map)
# ---------------------------------------------------------------------------

class TestKennfeld:
    """Parse KENNFELD entries."""

    MAP = """\
KONSERVIERUNG_FORMAT 2.0

KENNFELD MyMap 3 2
  LANGNAME "Test Map"
  EINHEIT_X "rpm"
  EINHEIT_Y "load"
  EINHEIT_W "V"
  ST/X 1000.0 2000.0 3000.0
  ST/Y 10.0
  WERT 1.0 2.0 3.0
  ST/Y 20.0
  WERT 4.0 5.0 6.0
END
"""

    def test_kennfeld(self) -> None:
        kf = _first(self.MAP, "kf")
        assert kf is not None
        assert kf["category"] == "KENNFELD"
        assert kf["name"] == "MyMap"
        assert kf["anzahl_x"] == 3
        assert kf["anzahl_y"] == 2
        assert kf["einheit_x"] == "rpm"
        assert kf["einheit_y"] == "load"
        assert kf["einheit_w"] == "V"
        sst = kf["sst_liste_x"]
        assert len(sst) == 1
        assert sst[0]["rs"] == [Decimal("1000.0"), Decimal("2000.0"), Decimal("3000.0")]
        rows = kf["kf_zeile_liste"]
        assert rows["category"] == "REAL"
        assert len(rows["rs"]) == 2


# ---------------------------------------------------------------------------
# STUETZSTELLENVERTEILUNG (shared axis / group breakpoints)
# ---------------------------------------------------------------------------

class TestGruppenstuetzstellen:
    """Parse STUETZSTELLENVERTEILUNG entries."""

    GST = """\
KONSERVIERUNG_FORMAT 2.0

STUETZSTELLENVERTEILUNG MyAxis 5
  LANGNAME "RPM Axis"
  EINHEIT_X "rpm"
  ST/X 500.0 1000.0 2000.0 3000.0 5000.0
END
"""

    def test_gruppenstuetzstellen(self) -> None:
        gst = _first(self.GST, "gst")
        assert gst is not None
        assert gst["name"] == "MyAxis"
        assert gst["anzahl_x"] == 5
        assert gst["einheit_x"] == "rpm"
        sst = gst["sst_liste_x"]
        assert len(sst) == 1
        assert sst[0]["rs"] == [
            Decimal("500.0"),
            Decimal("1000.0"),
            Decimal("2000.0"),
            Decimal("3000.0"),
            Decimal("5000.0"),
        ]


# ---------------------------------------------------------------------------
# TEXTSTRING
# ---------------------------------------------------------------------------

class TestTextstring:
    """Parse TEXTSTRING entries."""

    TXT = """\
KONSERVIERUNG_FORMAT 2.0

TEXTSTRING MyText
  LANGNAME "Description"
  TEXT "Hello World"
END
"""

    def test_textstring(self) -> None:
        kt = _first(self.TXT, "kt")
        assert kt is not None
        assert kt["name"] == "MyText"
        assert kt["text"] == "Hello World"
        assert kt["info"]["langname"] == "Description"


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------

class TestTopLevel:
    """Top-level parse result structure."""

    FULL = """\
KONSERVIERUNG_FORMAT 2.0

FUNKTIONEN
  FKT Func1 "" "Function One"
END

FESTWERT A
  EINHEIT_W "V"
  WERT 1.0
END

FESTWERT B
  EINHEIT_W "A"
  WERT 2.0
END
"""

    def test_version(self) -> None:
        result = _parse(self.FULL)
        assert result["version"] == 2.0

    def test_kopf_func_def(self) -> None:
        result = _parse(self.FULL)
        func_def = result["kopf"]["func_def"]
        assert func_def is not None
        assert len(func_def) == 1
        assert func_def[0]["name"] == "Func1"

    def test_rumpf_count(self) -> None:
        result = _parse(self.FULL)
        assert len(result["rumpf"]) == 2

    def test_empty_body(self) -> None:
        result = _parse("KONSERVIERUNG_FORMAT 2.0\n")
        assert result["version"] == 2.0
        assert result["rumpf"] == []


# ---------------------------------------------------------------------------
# Multiple entry types in one file
# ---------------------------------------------------------------------------

class TestMixedEntries:
    """Parse files with multiple entry types."""

    MIXED = """\
KONSERVIERUNG_FORMAT 2.0

FESTWERT ScalarParam
  EINHEIT_W "V"
  WERT 99.0
END

STUETZSTELLENVERTEILUNG SharedAxis 3
  EINHEIT_X "rpm"
  ST/X 100.0 200.0 300.0
END

KENNLINIE MyCurve 3
  EINHEIT_X "rpm"
  EINHEIT_W "Nm"
  ST/X 100.0 200.0 300.0
  WERT 10.0 20.0 30.0
END

TEXTSTRING MyLabel
  TEXT "calibration v1"
END
"""

    def test_mixed_entry_count(self) -> None:
        items = _rumpf(self.MIXED)
        assert len(items) == 4

    def test_mixed_types(self) -> None:
        items = _rumpf(self.MIXED)
        assert items[0]["kw"] is not None  # FESTWERT
        assert items[1]["gst"] is not None  # STUETZSTELLENVERTEILUNG
        assert items[2]["kl"] is not None  # KENNLINIE
        assert items[3]["kt"] is not None  # TEXTSTRING


# ---------------------------------------------------------------------------
# ParserWrapper.result attribute
# ---------------------------------------------------------------------------

class TestParserWrapperResult:
    """Verify that ParserWrapper stores result on listener."""

    def test_listener_has_result_attribute(self) -> None:
        parser = ParserWrapper("dcm20", "konservierung", Dcm20Listener)
        listener = parser.parseFromString("KONSERVIERUNG_FORMAT 2.0\n")
        assert hasattr(listener, "result")
        assert isinstance(listener.result, dict)
        assert "version" in listener.result

    def test_result_matches_tree_phys(self) -> None:
        parser = ParserWrapper("dcm20", "konservierung", Dcm20Listener)
        text = """\
KONSERVIERUNG_FORMAT 2.0

FESTWERT X
  EINHEIT_W "-"
  WERT 7.0
END
"""
        listener = parser.parseFromString(text)
        assert listener.result["version"] == 2.0
        assert len(listener.result["rumpf"]) == 1
        assert listener.result["rumpf"][0]["kw"]["name"] == "X"


# ---------------------------------------------------------------------------
# import_dcm convenience function
# ---------------------------------------------------------------------------

class TestImportDcm:
    """Test the import_dcm() convenience function."""

    def test_import_from_string(self) -> None:
        result = import_dcm("KONSERVIERUNG_FORMAT 2.0\n")
        assert result["version"] == 2.0

    def test_import_from_file(self, tmp_path: Path) -> None:
        dcm_file = tmp_path / "test.dcm"
        dcm_file.write_text(
            "KONSERVIERUNG_FORMAT 2.0\n\nFESTWERT P\n  EINHEIT_W \"-\"\n  WERT 5.0\nEND\n",
            encoding="latin-1",
        )
        result = import_dcm(dcm_file)
        assert result["version"] == 2.0
        assert len(result["rumpf"]) == 1
        assert result["rumpf"][0]["kw"]["name"] == "P"

    def test_import_from_string_path(self, tmp_path: Path) -> None:
        dcm_file = tmp_path / "demo.dcm"
        dcm_file.write_text(
            "KONSERVIERUNG_FORMAT 2.0\n\nFESTWERT Q\n  EINHEIT_W \"A\"\n  WERT 8.0\nEND\n",
            encoding="latin-1",
        )
        result = import_dcm(str(dcm_file))
        assert result["rumpf"][0]["kw"]["realzahl"] == Decimal("8.0")


# ---------------------------------------------------------------------------
# Real example file parsing
# ---------------------------------------------------------------------------

class TestExampleFiles:
    """Parse real example DCM files from the repository."""

    @pytest.mark.skipif(
        not (EXAMPLES_DIR / "CDF20demo_CalData_27122020_151654.dcm").exists(),
        reason="CDF20demo DCM not found",
    )
    def test_cdf20demo_dcm(self) -> None:
        result = import_dcm(EXAMPLES_DIR / "CDF20demo_CalData_27122020_151654.dcm")
        assert result["version"] == 2.0
        rumpf = result["rumpf"]
        assert len(rumpf) > 0
        # Should contain STUETZSTELLENVERTEILUNG, FESTWERT, KENNLINIE, KENNFELD, etc.
        has_gst = any(item["gst"] is not None for item in rumpf)
        has_kw = any(item["kw"] is not None for item in rumpf)
        has_kl = any(item["kl"] is not None for item in rumpf)
        assert has_gst, "Expected STUETZSTELLENVERTEILUNG entries"
        assert has_kw, "Expected FESTWERT entries"
        assert has_kl, "Expected KENNLINIE entries"

    @pytest.mark.skipif(
        not (EXAMPLES_DIR / "xcpsim2" / "XCPsim.dcm").exists(),
        reason="XCPsim DCM not found",
    )
    def test_xcpsim_dcm_parses_without_exception(self) -> None:
        result = import_dcm(EXAMPLES_DIR / "xcpsim2" / "XCPsim.dcm")
        assert result["version"] == 2.0
        assert len(result["rumpf"]) > 0


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------

class TestAPISurface:
    """Verify import_dcm is accessible from asamint.api."""

    def test_import_dcm_in_api(self) -> None:
        from asamint.api import import_dcm as api_import_dcm

        assert callable(api_import_dcm)

    def test_export_to_dcm_in_api(self) -> None:
        from asamint.api import export_to_dcm as api_export

        assert callable(api_export)

    def test_dcm_exporter_in_api(self) -> None:
        from asamint.api import DcmExporter as ApiExporter

        assert ApiExporter is not None
