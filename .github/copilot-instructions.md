# Copilot Project Instructions for asamint

## Grundsätze & Ausgabe-Regeln
- Immer vollständigen, lauffähigen, PEP8-konformen Python-3.10+ Code liefern; keine Fragmente, keine zusammengeklebten Zeilen, keine Ellipsen.
- Vollständige Typannotationen, `dataclasses` (mit `slots=True` für DTOs) für strukturierte Daten, keine Globals/Singletons; Namen: snake_case für Funktionen/Methoden/Module, PascalCase für Klassen.
- Imports vollständig angeben; Decorators direkt über Klassen/Methoden, Einrückung 4 Leerzeichen, 2 Leerzeilen zwischen Klassen, 1 zwischen Methoden.
- Nur `pathlib` statt `os.path`, Logging immer über `asamint.core.logging.configure_logging` (kein `print`).
- Code immer als ganzen Patch/Datei liefern, kein Mischtext mit Code.

## Build / Test / Lint
- Setup: `poetry install`; Fallback: `pip install -r requirements_dev.txt`.
- Tests: `poetry run pytest` (Addopts: `--verbose --tb=short --junitxml=result.xml`); Einzeltest: `poetry run pytest tests/test_calibration.py::test_value001`. Testdaten (`tests/*.a2l`, `tests/*.hex`, `tests/*.msrswdb`) dürfen nicht verschoben werden.
- Lint/Format: `poetry run ruff check .` und `poetry run ruff format .` (Line-Length 132, siehe `[tool.ruff]` in `pyproject.toml`).
- Packaging: CI baut Wheels/Sdist via `cibuildwheel` (siehe `.github/workflows/pythonapp.yml`).
- Hinweis: `pyproject.toml [tool.pytest]` setzt `testpaths = "asamint/tests"`, die aktiven Tests liegen aber unter `tests/` (Root). pytest findet sie über `setup.cfg [tool:pytest]` oder direkte Angabe.

## High-Level Architektur

### Public API (`asamint.api`)
Re-exportiert alle öffentlichen Symbole: `Calibration`, `OnlineCalibration`, `OfflineCalibration`, `ParameterCache`, `ExecutionPolicy`, `Status`, `generate_c_structs_from_log`, Measurement-Funktionen (`run`, `build_daq_lists`, `finalize_daq_csv`, ...), CDF I/O (`export_cdf`, `import_cdf`), und Config-Helfer. Externe Nutzungen importieren stets aus `asamint.api`, nicht aus tiefen Paketpfaden.

### Adapter-Schicht (`asamint.adapters`)
Kapselt **alle** Zugriffe auf externe Bibliotheken hinter schmalen Wrappern:
- `adapters.a2l` — pya2l-Modelle, `open_a2l_database`, A2L-Datentyp-Helfer (`asam_type_size`, `fix_axis_par`, ...)
- `adapters.objutils` — objutils `Image`/`Section`, `open_image`
- `adapters.xcp` — pyxcp `create_master`, `McObject`, DAQ-Helfer
- `adapters.mdf` — asammdf `open_mdf`/`save_mdf`/`mdf_channels`
- `adapters.measurement` — Format-Registry (`register_measurement_format`, `get_measurement_format`)
- `adapters.parsers` — ANTLR-Parser-Erzeugung

Kein anderer Code darf pyXCP, pya2l, objutils oder asammdf direkt importieren.

### Core (`asamint.core`)
- Byte-Order/Datentyp-Helfer: `ByteOrder` (IntEnum), `get_data_type`, `byte_order`, `ECUByteOrder.decode`
- Exceptions: `AsamIntError` (Basis) → `ConfigurationError`, `AdapterError`, `CalibrationError` → `ReadOnlyError`, `RangeError` → `LimitViolation`, `FileFormatError`
- Logging: `configure_logging(name, level, logfile)`
- ABCs/Protocols: `CalibrationAdapter` (Protocol für read/write_asam_*), `CalibrationContext` (ABC load/save/update), `SupportsLogging`
- DTOs: `GeneralConfig`, `LoggingConfig`, `CalibrationLimits`, `CalibrationValue`, `MeasurementChannel`

### Asam/XCP (`asamint.asam`)
`AsamMC` liest Konfiguration über `asamint.config` (traitlets-basiert, `asamint_conf.py`), erzeugt XCP-Master via `adapters.xcp`, hält A2L-DB/HEX/Experiment-Metadaten, nutzt `pya2l`-Modelle.

### Konfiguration (`asamint.config`)
Traitlets-basiertes System (`Asamint` Application → `General`, `XCP` Configurable). Konfigurationsdatei: `asamint_conf.py` (Python). Externe pyXCP-Config wird optional gemergt. Zugriff über `create_application()` / `get_application()`, Snapshots über `snapshot_general_config()` / `snapshot_logging_config()`.

### Calibration (`asamint.calibration`)
- `calibration.api`: Hauptklassen `Calibration`/`OnlineCalibration`/`OfflineCalibration`, arbeiten gegen `pya2l.DB` + `objutils.Image` via `CalibrationAdapter`. `ParameterCache` für CURVE/MAP/Value, Limit-/ReadOnly-Prüfungen, `ExecutionPolicy`/`Status`.
- `calibration.db` (`CalibrationDB`): HDF5-basierte Persistenz; speichert COM_AXIS/RES_AXIS/CURVE_AXIS als Soft-Links auf AXIS_PTS-Einträge.
- `calibration.codegen`: C-Struct-Generierung aus Kalibrierlogs.
- Offline-Kalibrierwertezugriff nutzt `objutils` `read_asam_*`/`write_asam_*` über `_AddressMappedImage`.

### Datenformate
- `cdf`: CDF-XML Import/Export, MSRSW-Walker
- `cvx`: CVX Import/Export
- `damos`: DCM-Export/Import (ANTLR-Parser unter `damos/parsers`)
- `mdf`/`measurement`/`hdf5`: MDF- und HDF5-Verarbeitung, DAQ-CSV-Konvertierung

### Utilities
- `asamint.utils`: Daten-Helfer, Template-Engine (`utils.templates`), XML-Utilities (`utils.xml`)
- `asamint.compu`: Computation-Method-Auswertung
- `asamint.parserlib`: Parser-Hilfsfunktionen
- `asamint.data`: Jinja2-Templates und DTDs

## Schlüsselkonventionen
- **Adapter-Grenze**: Keine direkten Imports von pyXCP, pyA2L, objutils, asammdf außerhalb `asamint.adapters` und des jeweils zuständigen Pakets. Alle externen Typen werden über Adapter re-exportiert.
- **Exceptions**: Immer projektweite Exceptions aus `asamint.core.exceptions` verwenden; keine nackten `except`. Exception-Hierarchie: `AsamIntError` als Basis.
- **Wertezugriff**: Bevorzugt über `Calibration.load_*`/`save_*` und `ParameterCache`, nicht über rohe pya2l-DB-Calls.
- **API-Stabilität**: Externe Nutzungen über `asamint.api` importieren. Bei Umbenennung/Entfernung öffentlicher Namen: deprecated Alias in `asamint.api._DEPRECATED_ALIASES` eintragen und Test in `tests/test_api_stability.py` ergänzen (siehe `CONTRIBUTING.rst` Abschnitt "Pull Request Guidelines").
- **Calibration I/O**: Offline-Zugriff auf Skalare/Strings über `objutils` `read_asam_*/write_asam_*` via `_AddressMappedImage`; ASAM-dtype und byteOrder direkt aus A2L durchreichen.
- **CalibrationDB**: HDF5-Soft-Links für COM_AXIS, RES_AXIS und CURVE_AXIS auf AXIS_PTS; Load muss alle drei Kategorien auflösen.

## Test-Strategie
- **Core/Unit**: `asamint.core`-Helfer und DTOs; kein externer I/O. Schnelle, parametrisierte Tests bevorzugen.
- **Adapter**: Fakes/Fixtures nutzen; kein echter Hardware-/Netzwerkzugriff. Externe Libs hinter Adapter-Grenzen halten.
- **Calibration/Measurement-Integration**: Fixtures unter `tests/*.a2l`/`*.hex`/`*.msrswdb` wiederverwenden und nicht verschieben. Offline-Calibration nutzt CDF20demo A2L/HEX; Measurement/HDF5 nutzt DAQ-CSV/HDF5-Synthesizer.
- **API-Oberfläche**: Entrypoints über öffentliche `asamint.api`-Exports validieren, ohne tiefe Interna zu importieren.
- Keine Netzwerkaufrufe in Tests; `pathlib` statt `os.path`; Projekt-Exceptions statt `Exception`.
