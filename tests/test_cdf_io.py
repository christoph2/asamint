from pathlib import Path
from types import SimpleNamespace

import pytest

from asamint import cdf


def test_export_cdf_invokes_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: dict[str, object] = {"db_closed": False, "h5_closed": False}
    dummy_logger = SimpleNamespace()
    monkeypatch.setattr(cdf, "configure_logging", lambda _: dummy_logger)

    class DummyDB:
        def __init__(self, file_name: str | Path) -> None:
            calls["db_path"] = Path(file_name)

        def close(self) -> None:
            calls["db_closed"] = True

    class DummyH5:
        def __init__(
            self, file_name: str | Path, mode: str = "r", logger: object | None = None
        ) -> None:
            calls["h5_path"] = Path(file_name)
            calls["h5_logger"] = logger

        def close(self) -> None:
            calls["h5_closed"] = True

    class DummyExporter:
        def __init__(
            self,
            db: DummyDB,
            h5_db: DummyH5 | None = None,
            variant_coding: bool = False,
            logger: object | None = None,
        ) -> None:
            calls["exporter_logger"] = logger
            calls["variant_coding"] = variant_coding
            calls["h5_db"] = h5_db
            calls["db"] = db

        def export(self, target: str | Path) -> bool:
            calls["export_path"] = Path(target)
            return True

    monkeypatch.setattr(cdf, "MSRSWDatabase", DummyDB)
    monkeypatch.setattr(cdf, "CalibrationDB", DummyH5)
    monkeypatch.setattr(cdf, "CDFExporter", DummyExporter)

    output = tmp_path / "out.cdfx"
    db_path = tmp_path / "source.msrswdb"
    h5_path = tmp_path / "values.h5"

    result = cdf.export_cdf(
        db_path=db_path,
        output_path=output,
        h5_db_path=h5_path,
        variant_coding=True,
    )

    assert result.output_path == output
    assert result.db_path == db_path
    assert calls["export_path"] == output
    assert calls["variant_coding"] is True
    assert calls["db_closed"] is True
    assert calls["h5_closed"] is True
    assert calls["exporter_logger"] is dummy_logger
    assert calls["h5_logger"] is dummy_logger


def test_import_cdf_invokes_importer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: dict[str, object] = {}
    dummy_logger = SimpleNamespace()
    monkeypatch.setattr(cdf, "configure_logging", lambda _: dummy_logger)

    class DummyImporter:
        def __init__(self, logger: object | None = None) -> None:
            calls["logger"] = logger

        def import_file(self, xml_path: str | Path, db_path: str | Path) -> bool:
            calls["paths"] = (Path(xml_path), Path(db_path))
            return True

    monkeypatch.setattr(cdf, "CDFImporter", DummyImporter)

    xml = tmp_path / "input.cdfx"
    db = tmp_path / "db.msrswdb"

    result = cdf.import_cdf(xml_path=xml, db_path=db)

    assert result.output_path == xml
    assert result.db_path == db
    assert calls["paths"] == (xml, db)
    assert calls["logger"] is dummy_logger
