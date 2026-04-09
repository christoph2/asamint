#!/usr/bin/env python
"""CDF round-trip integration tests.

Tests the full cycle:  CDF XML → import (CDFImporter) → MSRSW DB → export (CDFExporter) → CDF XML.
Verifies that structure and values survive the round-trip.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lxml import etree

from asamint.calibration.msrsw_db import (
    Category,
    Msrsw,
    MSRSWDatabase,
    ShortName,
    SwInstance,
    SwValuesPhys,
    V,
)
from asamint.cdf import CdfIOResult, export_cdf, import_cdf
from asamint.cdf.exporter.cdf_exporter import CDFExporter
from asamint.cdf.importer.cdf_importer import CDFImporter, import_cdf_to_db

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "asamint" / "examples"


# ---------------------------------------------------------------------------
# Minimal CDF XML templates
# ---------------------------------------------------------------------------

_CDF_HEADER = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE MSRSW PUBLIC "-//ASAM//DTD CALIBRATION DATA FORMAT:V2.0.0:LAI:IAI:XML:CDF200.XSD//EN" "cdf_v2.0.0.sl.dtd">
"""

_SCALAR_CDF = _CDF_HEADER + """\
<MSRSW>
  <SHORT-NAME>RoundTrip</SHORT-NAME>
  <CATEGORY>CDF20</CATEGORY>
  <SW-SYSTEMS>
    <SW-SYSTEM>
      <SHORT-NAME>TestSystem</SHORT-NAME>
      <SW-INSTANCE-SPEC>
        <SW-INSTANCE-TREE>
          <SHORT-NAME>TestTree</SHORT-NAME>
          <CATEGORY>NO_VCD</CATEGORY>
          <SW-INSTANCE>
            <SHORT-NAME>ScalarParam</SHORT-NAME>
            <LONG-NAME>A scalar parameter</LONG-NAME>
            <CATEGORY>VALUE</CATEGORY>
            <SW-VALUE-CONT>
              <UNIT-DISPLAY-NAME>V</UNIT-DISPLAY-NAME>
              <SW-VALUES-PHYS>
                <V>42.5</V>
              </SW-VALUES-PHYS>
            </SW-VALUE-CONT>
          </SW-INSTANCE>
        </SW-INSTANCE-TREE>
      </SW-INSTANCE-SPEC>
    </SW-SYSTEM>
  </SW-SYSTEMS>
</MSRSW>
"""

_MULTI_CDF = _CDF_HEADER + """\
<MSRSW>
  <SHORT-NAME>MultiTest</SHORT-NAME>
  <CATEGORY>CDF20</CATEGORY>
  <SW-SYSTEMS>
    <SW-SYSTEM>
      <SHORT-NAME>Sys</SHORT-NAME>
      <SW-INSTANCE-SPEC>
        <SW-INSTANCE-TREE>
          <SHORT-NAME>Tree</SHORT-NAME>
          <CATEGORY>NO_VCD</CATEGORY>
          <SW-INSTANCE>
            <SHORT-NAME>Gain</SHORT-NAME>
            <CATEGORY>VALUE</CATEGORY>
            <SW-VALUE-CONT>
              <UNIT-DISPLAY-NAME>-</UNIT-DISPLAY-NAME>
              <SW-VALUES-PHYS>
                <V>3.14</V>
              </SW-VALUES-PHYS>
            </SW-VALUE-CONT>
          </SW-INSTANCE>
          <SW-INSTANCE>
            <SHORT-NAME>Label</SHORT-NAME>
            <CATEGORY>VALUE</CATEGORY>
            <SW-VALUE-CONT>
              <SW-VALUES-PHYS>
                <VT>Hello World</VT>
              </SW-VALUES-PHYS>
            </SW-VALUE-CONT>
          </SW-INSTANCE>
          <SW-INSTANCE>
            <SHORT-NAME>ArrayParam</SHORT-NAME>
            <CATEGORY>VAL_BLK</CATEGORY>
            <SW-VALUE-CONT>
              <UNIT-DISPLAY-NAME>rpm</UNIT-DISPLAY-NAME>
              <SW-ARRAYSIZE>
                <V>3</V>
              </SW-ARRAYSIZE>
              <SW-VALUES-PHYS>
                <V>10.0</V>
                <V>20.0</V>
                <V>30.0</V>
              </SW-VALUES-PHYS>
            </SW-VALUE-CONT>
          </SW-INSTANCE>
        </SW-INSTANCE-TREE>
      </SW-INSTANCE-SPEC>
    </SW-SYSTEM>
  </SW-SYSTEMS>
</MSRSW>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_xml(tmp_path: Path, name: str, content: str) -> Path:
    xml_file = tmp_path / name
    xml_file.write_text(content, encoding="utf-8")
    return xml_file


def _import_xml(xml_file: Path) -> Path:
    """Import a CDF XML and return the DB path."""
    db_path = xml_file.with_suffix(".msrswdb")
    success = import_cdf_to_db(xml_file, db_path)
    assert success, f"Import failed for {xml_file}"
    return db_path


def _query_instances(db_path: Path) -> list[dict[str, Any]]:
    """Open a DB and return SwInstance short-names and categories."""
    db = MSRSWDatabase(db_path)
    try:
        instances = db.session.query(SwInstance).all()
        result = []
        for inst in instances:
            name = inst.short_name.content if inst.short_name else None
            cat = inst.category.content if inst.category else None
            long_name = inst.long_name.content if inst.long_name else None
            result.append({"name": name, "category": cat, "long_name": long_name})
        return result
    finally:
        db.close()


def _export_xml(db_path: Path, output: Path) -> bool:
    """Export a DB to CDF XML (no H5 values)."""
    db = MSRSWDatabase(db_path)
    try:
        exporter = CDFExporter(db=db)
        return exporter.export(output)
    finally:
        db.close()


def _parse_xml(xml_file: Path) -> etree._Element:
    """Parse a CDF XML file, return root element."""
    parser = etree.XMLParser(recover=True)
    tree = etree.parse(str(xml_file), parser)
    return tree.getroot()


def _find_instances(root: etree._Element) -> list[etree._Element]:
    """Find all SW-INSTANCE elements in CDF XML."""
    return root.findall(".//{http://www.w3.org/1999/xhtml}SW-INSTANCE") or root.findall(
        ".//SW-INSTANCE"
    )


def _instance_map(root: etree._Element) -> dict[str, etree._Element]:
    """Map SHORT-NAME → SW-INSTANCE element."""
    result = {}
    for inst in _find_instances(root):
        sn = inst.find("SHORT-NAME")
        if sn is not None and sn.text:
            result[sn.text] = inst
    return result


# ---------------------------------------------------------------------------
# Import tests — XML → DB
# ---------------------------------------------------------------------------


class TestCdfImport:
    """Verify that CDF XML is correctly imported into the MSRSW database."""

    def test_scalar_import_creates_instance(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "scalar.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        instances = _query_instances(db_path)
        names = [i["name"] for i in instances]
        assert "ScalarParam" in names

    def test_scalar_import_category(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "scalar.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        instances = _query_instances(db_path)
        param = next(i for i in instances if i["name"] == "ScalarParam")
        assert param["category"] == "VALUE"

    def test_scalar_import_long_name(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "scalar.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        instances = _query_instances(db_path)
        param = next(i for i in instances if i["name"] == "ScalarParam")
        assert param["long_name"] == "A scalar parameter"

    def test_multi_import_instance_count(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "multi.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        instances = _query_instances(db_path)
        assert len(instances) == 3

    def test_multi_import_names(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "multi.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        instances = _query_instances(db_path)
        names = sorted(i["name"] for i in instances)
        assert names == ["ArrayParam", "Gain", "Label"]

    def test_multi_import_categories(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "multi.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        instances = _query_instances(db_path)
        cats = {i["name"]: i["category"] for i in instances}
        assert cats["Gain"] == "VALUE"
        assert cats["Label"] == "VALUE"
        assert cats["ArrayParam"] == "VAL_BLK"

    def test_import_stores_numeric_value_in_db(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "scalar.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        db = MSRSWDatabase(db_path)
        try:
            v_objs = db.session.query(V).all()
            values = [v.content for v in v_objs if v.content is not None]
            assert any("42.5" in str(v) for v in values), f"Expected 42.5 in {values}"
        finally:
            db.close()

    def test_import_result_type(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "scalar.cdfx", _SCALAR_CDF)
        db_path = tmp_path / "out.msrswdb"
        result = import_cdf(xml_path=xml_file, db_path=db_path)
        assert isinstance(result, CdfIOResult)
        assert result.output_path == xml_file
        assert result.db_path == db_path


# ---------------------------------------------------------------------------
# Export tests — DB → XML
# ---------------------------------------------------------------------------


class TestCdfExport:
    """Verify that an imported MSRSW database exports back to valid CDF XML."""

    def test_export_creates_file(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "exported.cdfx"
        assert _export_xml(db_path, out) is True
        assert out.exists()

    def test_export_contains_doctype(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "exported.cdfx"
        _export_xml(db_path, out)
        text = out.read_text(encoding="utf-8")
        assert "cdf_v2.0.0.sl.dtd" in text

    def test_export_contains_msrsw_root(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "exported.cdfx"
        _export_xml(db_path, out)
        root = _parse_xml(out)
        assert root.tag == "MSRSW"


# ---------------------------------------------------------------------------
# Round-trip tests — XML → DB → XML
# ---------------------------------------------------------------------------


class TestCdfRoundTrip:
    """Full round-trip: CDF XML → import to DB → export back to XML."""

    def test_scalar_round_trip_preserves_name(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        assert "ScalarParam" in imap

    def test_scalar_round_trip_preserves_category(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        cat = imap["ScalarParam"].find("CATEGORY")
        assert cat is not None
        assert cat.text == "VALUE"

    def test_scalar_round_trip_preserves_long_name(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        ln = imap["ScalarParam"].find("LONG-NAME")
        assert ln is not None
        assert ln.text == "A scalar parameter"

    def test_scalar_round_trip_preserves_value(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        values_phys = imap["ScalarParam"].find(".//SW-VALUES-PHYS")
        assert values_phys is not None
        v_elem = values_phys.find("V")
        assert v_elem is not None
        assert v_elem.text == "42.5"

    def test_scalar_round_trip_preserves_unit(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        unit = imap["ScalarParam"].find(".//UNIT-DISPLAY-NAME")
        assert unit is not None
        assert unit.text == "V"

    def test_multi_round_trip_preserves_all_names(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        assert "Gain" in imap
        assert "Label" in imap
        assert "ArrayParam" in imap

    def test_multi_round_trip_numeric_value(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        v_elem = imap["Gain"].find(".//SW-VALUES-PHYS/V")
        assert v_elem is not None
        assert v_elem.text == "3.14"

    def test_multi_round_trip_text_value(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        vt_elem = imap["Label"].find(".//SW-VALUES-PHYS/VT")
        assert vt_elem is not None
        assert vt_elem.text == "Hello World"

    def test_multi_round_trip_val_blk_category(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        cat = imap["ArrayParam"].find("CATEGORY")
        assert cat is not None
        assert cat.text == "VAL_BLK"

    def test_multi_round_trip_val_blk_array_size(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        arr_size = imap["ArrayParam"].find(".//SW-ARRAYSIZE/V")
        assert arr_size is not None
        assert arr_size.text == "3"

    def test_multi_round_trip_val_blk_values(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _MULTI_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        imap = _instance_map(_parse_xml(out))
        v_elems = imap["ArrayParam"].findall(".//SW-VALUES-PHYS/V")
        values = [v.text for v in v_elems]
        assert "10.0" in values
        assert "20.0" in values
        assert "30.0" in values

    def test_msrsw_short_name_preserved(self, tmp_path: Path) -> None:
        xml_file = _write_xml(tmp_path, "in.cdfx", _SCALAR_CDF)
        db_path = _import_xml(xml_file)
        out = tmp_path / "out.cdfx"
        _export_xml(db_path, out)
        root = _parse_xml(out)
        sn = root.find("SHORT-NAME")
        assert sn is not None
        assert sn.text == "RoundTrip"


# ---------------------------------------------------------------------------
# Real example file round-trip
# ---------------------------------------------------------------------------


class TestExampleRoundTrip:
    """Round-trip with real example CDF files from the repo."""

    CDF_EXAMPLE = EXAMPLES_DIR / "CDF20demo.cdfx"

    @pytest.mark.skipif(
        not (EXAMPLES_DIR / "CDF20demo.cdfx").exists(),
        reason="CDF20demo.cdfx not found",
    )
    def test_cdf20demo_import_export_cycle(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cdf20demo.msrswdb"
        success = import_cdf_to_db(self.CDF_EXAMPLE, db_path)
        assert success

        out = tmp_path / "cdf20demo_export.cdfx"
        assert _export_xml(db_path, out) is True
        assert out.exists()

        root = _parse_xml(out)
        assert root.tag == "MSRSW"

        imap = _instance_map(root)
        assert len(imap) > 0, "Expected at least one SW-INSTANCE in exported XML"

    @pytest.mark.skipif(
        not (EXAMPLES_DIR / "CDF20demo.cdfx").exists(),
        reason="CDF20demo.cdfx not found",
    )
    def test_cdf20demo_preserves_instance_names(self, tmp_path: Path) -> None:
        db_path = tmp_path / "cdf20demo.msrswdb"
        import_cdf_to_db(self.CDF_EXAMPLE, db_path)

        original_root = _parse_xml(self.CDF_EXAMPLE)
        original_names = set(_instance_map(original_root).keys())

        out = tmp_path / "cdf20demo_export.cdfx"
        _export_xml(db_path, out)

        exported_root = _parse_xml(out)
        exported_names = set(_instance_map(exported_root).keys())

        assert original_names == exported_names, (
            f"Instance names differ: "
            f"missing={original_names - exported_names}, "
            f"extra={exported_names - original_names}"
        )


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


class TestApiSurface:
    """Verify public CDF API symbols."""

    def test_export_cdf_callable(self) -> None:
        from asamint.api import export_cdf as fn

        assert callable(fn)

    def test_import_cdf_callable(self) -> None:
        from asamint.api import import_cdf as fn

        assert callable(fn)

    def test_cdf_io_result_importable(self) -> None:
        from asamint.api import CdfIOResult

        assert CdfIOResult is not None
