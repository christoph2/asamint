# Copilot Project Instructions for asamint

## Grundsätze & Ausgabe-Regeln
- Immer vollständigen, lauffähigen, PEP8-konformen Python-3.11+ Code liefern; keine Fragmente, keine zusammengeklebten Zeilen, keine Ellipsen.
- Vollständige Typannotationen, `dataclasses` für strukturierte Daten, keine Globals/Singletons; Namen: snake_case für Funktionen/Methoden/Module, PascalCase für Klassen.
- Imports vollständig angeben; Decorators direkt über Klassen/Methoden, Einrückung 4 Leerzeichen, 2 Leerzeilen zwischen Klassen, 1 zwischen Methoden.
- Nur `pathlib` statt `os.path`, Logging immer über `asamint.core.logging.configure_logging` (kein `print`).
- Code immer als ganzen Patch/Datei liefern, kein Mischtext mit Code.

## Build / Test / Lint
- Setup: `poetry install`; Fallback: `pip install -r requirements_dev.txt`.
- Tests: `poetry run pytest` (Addopts: `--verbose --tb=short --junitxml=result.xml`); Einzeltest: `poetry run pytest tests/test_calibration.py::test_value001`. Testdaten (`tests/*.a2l`, `tests/*.hex`) dürfen nicht verschoben werden.
- Lint/Format: `poetry run ruff check .` und `poetry run ruff format .` (Line-Length 132, siehe `[tool.ruff]`). Legacy: `flake8`/`black` aus `setup.cfg`, `tox` (`py.test --basetemp`).
- Packaging: `python setup.py sdist bdist_wheel` oder `make dist`; CI baut Wheels/Sdist via `cibuildwheel` (siehe `.github/workflows/pythonapp.yml`).

## High-Level Architektur
- Öffentliche Fläche: `asamint.api` re-exportiert `Calibration`, `OnlineCalibration`, `OfflineCalibration`, `ParameterCache`, `ExecutionPolicy`, `Status`, `generate_c_structs_from_log`.
- Core (`asamint.core`): Byte-Order/Datentyp-Helfer (`ByteOrder`, `get_data_type`, `byte_order`), Exceptions (`AdapterError`, `CalibrationError`, ...), Logging (`configure_logging`), ABCs (`CalibrationAdapter`, `CalibrationContext`, `SupportsLogging`).
- Asam/XCP: `asamint.asam.AsamMC` liest Konfiguration (`asamint.config`), erzeugt XCP-Master (`pyxcp`), hält A2L/HEX/Experiment-Metadaten und nutzt `pya2l`-Modelle.
- Calibration: `asamint.calibration.api` arbeitet gegen `pya2l.DB` und `objutils.Image`, kapselt Parameterzugriff über `ParameterCache` (CURVE/MAP/Value), Limit-/ReadOnly-Prüfungen und Policies (`ExecutionPolicy`, `Status`).
- Datenformate/Adapter: Pakete `a2l`, `cdf` (MSRSW-Walker -> `MSRSWDatabase`), `cvx`/`damos` (DCM/ASAP2 Konverter), `mdf`/`measurement`/`hdf5` (MDF/HDF5 Verarbeitung, z. B. `measurement.convert.VectorAutosar`), Utilities (`asamint.utils`, `compu`, `parserlib`, Templates in `data`).
- Tests/Beispiele: Fixtures liegen unter `tests/`; Beispielskripte und Artefakte unter `asamint/examples`.

## Schlüsselkonventionen
- Keine direkten Zugriffe auf pyXCP, pyA2L, AsamMDF außerhalb der Adapter/entsprechenden Pakete; zentrale Datentypen aus `asamint.core`.
- Fehler immer mit projektweiten Exceptions (`asamint.core.exceptions`); keine nackten `except`.
- Wertezugriff bevorzugt über `Calibration.load_*`/`save_*` und `ParameterCache`, nicht über rohe DB-Calls.
- API-Stabilität sichern: Externe Nutzungen über `asamint.api` importieren statt tiefer Paketpfade.
