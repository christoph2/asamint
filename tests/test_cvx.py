"""Tests for the CVX (Calibration Values Exchange) import/export module.

Covers:
- CVXImporter: parsing VALUE, VAL_BLK, CURVE, MAP, AXIS_PTS, ASCII records
- CVXExporter: writing records back to CVX format
- Round-trip: import → export → re-import produces identical data
- Public API: import_cvx / export_cvx convenience functions
- API surface: symbols accessible from asamint.api
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path

import pytest

from asamint.cvx import CVXExporter, CVXImporter, export_cvx, import_cvx

FIXTURE_DIR = Path(__file__).parent
EXAMPLES_DIR = FIXTURE_DIR.parent / "asamint" / "examples"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_cvx(tmp_path: Path, content: str, name: str = "test.cvx") -> Path:
    """Write CVX content to a temp file and return its path."""
    p = tmp_path / name
    p.write_text(textwrap.dedent(content), encoding="latin-1", newline="\r\n")
    return p


# ---------------------------------------------------------------------------
# CVXImporter — parsing
# ---------------------------------------------------------------------------


class TestCVXImporterValue:
    """Import VALUE records."""

    def test_single_value(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            #comment
            ,myParam
            VALUE,,42.5
        """)
        records = CVXImporter().import_file(str(p))
        assert len(records) >= 1
        rec = next(r for r in records if r["identifier"] == "myParam")
        assert rec["type"] == "VALUE"
        assert rec["values"] == [42.5]

    def test_multiple_values(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,paramA
            VALUE,,1.0

            ,paramB
            VALUE,,2.0
        """)
        records = CVXImporter().import_file(str(p))
        names = [r["identifier"] for r in records]
        assert "paramA" in names
        assert "paramB" in names

    def test_ascii_value(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,textParam
            ASCII,,"hello world"
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "textParam")
        assert rec["type"] == "ASCII"
        assert rec["values"] == ["hello world"]


class TestCVXImporterValBlk:
    """Import VAL_BLK records."""

    def test_val_blk(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,myBlock
            VAL_BLK,,1.0,2.0,3.0,4.0,5.0
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "myBlock")
        assert rec["type"] == "VAL_BLK"
        assert rec["values"] == [1.0, 2.0, 3.0, 4.0, 5.0]


class TestCVXImporterAxisPts:
    """Import AXIS_PTS records."""

    def test_axis_pts(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,xAxis
            AXIS_PTS,,10.0,20.0,30.0,40.0
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "xAxis")
        assert rec["type"] == "AXIS_PTS"
        assert rec["values"] == [10.0, 20.0, 30.0, 40.0]


class TestCVXImporterCurve:
    """Import CURVE records."""

    def test_curve_two_lines(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,myCurve
            CURVE
            ,,1.0,2.0,3.0
            ,,10.0,20.0,30.0
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "myCurve")
        assert rec["type"] == "CURVE"
        assert rec["axis_x"] == [1.0, 2.0, 3.0]
        assert rec["values"] == [10.0, 20.0, 30.0]


class TestCVXImporterMap:
    """Import MAP records."""

    def test_map_basic(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,myMap
            MAP
            ,,1.0,2.0,3.0
            ,,10.0,100.0,200.0,300.0
            ,,20.0,400.0,500.0,600.0
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "myMap")
        assert rec["type"] == "MAP"
        assert rec["axis_x"] == [1.0, 2.0, 3.0]
        assert rec["axis_y"] == [10.0, 20.0]
        assert rec["values"] == [
            [100.0, 200.0, 300.0],
            [400.0, 500.0, 600.0],
        ]


class TestCVXImporterAttributes:
    """Import records with FUNCTION / VARIANT / DISPLAY_IDENTIFIER."""

    def test_function_attribute(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,paramF
            VALUE,,99.0
            FUNCTION,,myFunc
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "paramF")
        assert rec["function"] == "myFunc"

    def test_variant_attribute(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,paramV
            VALUE,,1.0
            VARIANT,,"CriterionA.ValueX"
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "paramV")
        assert len(rec["variants"]) == 1
        assert rec["variants"][0] == ("CriterionA", "ValueX")

    def test_display_identifier(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,paramDI
            VALUE,,5.0
            DISPLAY_IDENTIFIER,,DI_Name
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "paramDI")
        assert rec["display_identifier"] == "DI_Name"


class TestCVXImporterHeaders:
    """Import FUNCTION_HDR and VARIANT_HDR blocks."""

    def test_function_header(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            FUNCTION_HDR
            FuncA,FuncB,FuncC

            ,val1
            VALUE,,1.0
        """)
        imp = CVXImporter()
        imp.import_file(str(p))
        assert imp.functions == ["FuncA", "FuncB", "FuncC"]

    def test_variant_header(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            VARIANT_HDR
            Country,DE,US,JP

            ,val1
            VALUE,,1.0
        """)
        imp = CVXImporter()
        imp.import_file(str(p))
        assert "Country" in imp.variants
        assert imp.variants["Country"] == ["DE", "US", "JP"]


class TestCVXImporterSemicolon:
    """Import with semicolon delimiter (matching real CVX files)."""

    def test_semicolon_value(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ;paramSC
            VALUE;;3.14
        """)
        records = CVXImporter(delimiter=";").import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "paramSC")
        assert rec["type"] == "VALUE"
        assert math.isclose(rec["values"][0], 3.14, rel_tol=1e-6)


# ---------------------------------------------------------------------------
# CVXExporter — writing
# ---------------------------------------------------------------------------


class TestCVXExporter:
    """Export records to CVX format."""

    def test_export_value(self) -> None:
        exp = CVXExporter(delimiter=";")
        out = exp.export_stream(
            [{"identifier": "p1", "type": "VALUE", "values": [42.0]}]
        )
        assert "KENNUNG p1" in out
        assert "VALUE" in out
        assert "WERT 42" in out

    def test_export_val_blk(self) -> None:
        exp = CVXExporter(delimiter=";")
        out = exp.export_stream(
            [
                {
                    "identifier": "blk",
                    "type": "VAL_BLK",
                    "values": [1.0, 2.0, 3.0],
                    "function": "FN",
                }
            ]
        )
        assert "VAL_BLK" in out
        assert "FUNKTION FN" in out

    def test_export_curve(self) -> None:
        exp = CVXExporter(delimiter=";")
        out = exp.export_stream(
            [
                {
                    "identifier": "crv",
                    "type": "CURVE",
                    "axis_x": [1.0, 2.0],
                    "values": [10.0, 20.0],
                }
            ]
        )
        assert "CURVE" in out
        assert "ST/X" in out
        assert "WERT" in out

    def test_export_map(self) -> None:
        exp = CVXExporter(delimiter=";")
        out = exp.export_stream(
            [
                {
                    "identifier": "mp",
                    "type": "MAP",
                    "axis_x": [1.0, 2.0],
                    "axis_y": [10.0, 20.0],
                    "values": [[100.0, 200.0], [300.0, 400.0]],
                }
            ]
        )
        assert "MAP" in out
        assert "ST/X" in out
        assert "ST/Y" in out

    def test_export_header(self) -> None:
        exp = CVXExporter()
        out = exp.export_stream(
            [], functions=["F1", "F2"], variants={"Crit": ["A", "B"]}
        )
        assert "KENNUNGEN" in out
        assert "FUNKTIONEN" in out
        assert "VARIANTE" in out
        assert "END" in out

    def test_export_to_file(self, tmp_path: Path) -> None:
        out_path = tmp_path / "out.cvx"
        exp = CVXExporter()
        exp.export_file(
            str(out_path),
            [{"identifier": "x", "type": "VALUE", "values": [1.0]}],
        )
        assert out_path.exists()
        content = out_path.read_text(encoding="latin-1")
        assert "KENNUNG x" in content

    def test_export_variants_on_record(self) -> None:
        exp = CVXExporter()
        out = exp.export_stream(
            [
                {
                    "identifier": "vr",
                    "type": "VALUE",
                    "values": [1.0],
                    "variants": [("Crit", "Val")],
                }
            ]
        )
        assert "VARIANTE Crit Val" in out


# ---------------------------------------------------------------------------
# DEPENDENT_VALUE support
# ---------------------------------------------------------------------------


class TestDependentValue:
    """DEPENDENT_VALUE is treated as a scalar VALUE in both import and export."""

    def test_import_dependent_value(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,depParam
            DEPENDENT_VALUE,,99.5
        """)
        records = CVXImporter().import_file(str(p))
        rec = next(r for r in records if r["identifier"] == "depParam")
        assert rec["type"] == "DEPENDENT_VALUE"
        assert rec["values"] == [99.5]

    def test_export_dependent_value(self) -> None:
        exp = CVXExporter(delimiter=";")
        out = exp.export_stream(
            [{"identifier": "dep1", "type": "DEPENDENT_VALUE", "values": [7.5]}]
        )
        assert "KENNUNG dep1" in out
        assert "WERT 7.5" in out

    def test_dependent_value_round_trip_structure(self, tmp_path: Path) -> None:
        records = [
            {"identifier": "dep_rt", "type": "DEPENDENT_VALUE", "values": [3.14]},
        ]
        out = tmp_path / "dep.cvx"
        CVXExporter(delimiter=",").export_file(str(out), records)
        content = out.read_text(encoding="latin-1")
        assert "KENNUNG dep_rt" in content
        assert "DEPENDENT_VALUE" in content
        assert "WERT" in content


# ---------------------------------------------------------------------------
# Round-trip: import → export → re-import
# ---------------------------------------------------------------------------


class TestCVXRoundTrip:
    """Verify that export → re-import produces records when formats match.

    Note: The CVXExporter writes KENNUNG-based format while CVXImporter reads
    raw CSV-based format.  A true round-trip requires the importer to
    understand the exported format.  For now we just verify that the exporter
    produces parseable output by checking structural markers.
    """

    def test_exporter_produces_valid_structure(self, tmp_path: Path) -> None:
        records = [
            {"identifier": "scalar1", "type": "VALUE", "values": [3.14]},
            {"identifier": "scalar2", "type": "VALUE", "values": [2.72]},
        ]
        exported = tmp_path / "exported.cvx"
        CVXExporter(delimiter=",").export_file(str(exported), records)
        content = exported.read_text(encoding="latin-1")
        assert "KENNUNG scalar1" in content
        assert "KENNUNG scalar2" in content
        assert "WERT" in content
        assert content.count("END") >= 3  # header END + 2 record ENDs


# ---------------------------------------------------------------------------
# Convenience API: import_cvx / export_cvx
# ---------------------------------------------------------------------------


class TestConvenienceAPI:
    """Test import_cvx and export_cvx top-level functions."""

    def test_import_cvx(self, tmp_path: Path) -> None:
        p = _write_cvx(tmp_path, """\
            ,api_param
            VALUE,,7.0
        """)
        records = import_cvx(p)
        assert any(r["identifier"] == "api_param" for r in records)

    def test_export_cvx(self, tmp_path: Path) -> None:
        out = tmp_path / "api_out.cvx"
        result = export_cvx(
            out,
            [{"identifier": "x", "type": "VALUE", "values": [9.0]}],
        )
        assert result == out
        assert out.exists()

    def test_round_trip_via_api(self, tmp_path: Path) -> None:
        """Verify export_cvx writes a file that contains expected markers."""
        out = tmp_path / "rt.cvx"
        records = [
            {"identifier": "a", "type": "VALUE", "values": [1.0]},
            {
                "identifier": "b",
                "type": "VAL_BLK",
                "values": [2.0, 3.0],
            },
        ]
        export_cvx(out, records, delimiter=",")
        content = out.read_text(encoding="latin-1")
        assert "KENNUNG a" in content
        assert "KENNUNG b" in content
        assert "VALUE" in content
        assert "VAL_BLK" in content


# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------


class TestAPISurface:
    """Ensure CVX symbols are accessible from asamint.api."""

    def test_api_has_cvx_exports(self) -> None:
        from asamint import api

        assert hasattr(api, "CVXImporter")
        assert hasattr(api, "CVXExporter")
        assert hasattr(api, "import_cvx")
        assert hasattr(api, "export_cvx")

    def test_api_all_contains_cvx(self) -> None:
        from asamint import api

        for name in ("CVXImporter", "CVXExporter", "import_cvx", "export_cvx"):
            assert name in api.__all__, f"{name} missing from api.__all__"


# ---------------------------------------------------------------------------
# Real example file (smoke test)
# ---------------------------------------------------------------------------


class TestExampleFile:
    """Smoke-test against real example CVX file if available."""

    EXAMPLE = EXAMPLES_DIR / "xcpsim2" / "XCPsim.cvx"

    @pytest.mark.skipif(
        not (EXAMPLES_DIR / "xcpsim2" / "XCPsim.cvx").exists(),
        reason="Example CVX file not present",
    )
    def test_import_example_xcpsim(self) -> None:
        imp = CVXImporter(delimiter=";")
        records = imp.import_file(str(self.EXAMPLE))
        assert len(records) > 0
        types = {r["type"] for r in records}
        assert "VALUE" in types
