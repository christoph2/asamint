=======
History
=======

0.2.2 (2026-04-09)
-------------------

- Calibration I/O: Switched to ASAM objutils ``read_asam_*``/``write_asam_*`` helpers for all scalar, string, CURVE, and MAP access; byte order and data type are passed directly from A2L metadata.
- Calibration DB: Fixed axis soft-link loading so COM_AXIS, RES_AXIS, and CURVE_AXIS are all resolved correctly from HDF5 soft links.
- Calibration DB: Fixed VAL_BLK matrix dimensions; normalized declarative defaults.
- Calibration: Preserved axis reversal metadata through DB round-trips.
- Calibration: Added warning when physical value cast would lose precision.
- Calibration: Improved CURVE/MAP limit and dimension validation; complete save-policy handling; handle invalid write addresses gracefully.
- Calibration: Implemented DEPENDENT_CHARACTERISTIC and VIRTUAL_CHARACTERISTIC engine (ASAM Appendix G).
- Calibration: Implemented OnlineCalibration with live XCP write-back and dirty-region flushing.
- Calibration: Implemented CURVE_AXIS normalization per ASAM MCD-2MC Appendix B.
- CDF: Added DTD validation on import/export; normalized ASCII and CDF shapes; added CDF API tests.
- CDF/DCM/CVX: Added DEPENDENT_VALUE support in exports; CVX repair and round-trip tests.
- DCM: Implemented ``import_dcm()`` API with ANTLR parser and integration tests.
- Paging: XCP segment/page information now read from A2L ``IF_DATA XCP`` SEGMENT/PAGE entries (attribute-based access).
- API stability: Added ``DeprecatedAlias`` mechanism to ``asamint.api``; shared deprecation hooks across all subpackages.
- Code quality: Cleared Ruff backlog; removed dead code and unused stubs; ``print()`` → ``logging`` migration across all production code.
- Type annotations: Added return types to all library methods; replaced ``Any`` with concrete types across public API; added docstrings to all public functions.
- Tooling: Added mypy configuration (310-error baseline); added ``py.typed`` marker (PEP 561).
- Packaging: Modernized CI — added test matrix (Python 3.10–3.13 × Ubuntu/Windows), tag-gated PyPI publish, updated all action versions.
- Packaging: Removed 7 legacy files (``tox.ini``, ``setup.cfg``, ``appveyor.yml``, ``MANIFEST.in``, ``requirements_*.txt``).
- Pre-commit: Replaced 17 obsolete local hooks with 2 official repos (``pre-commit-hooks`` + ``ruff-pre-commit``).
- Docs: Modernized Sphinx config, fixed module imports, added napoleon/intersphinx, wrote real usage guide and API reference.
- Version: aligned ``pyproject.toml`` version with HISTORY (was stuck at 0.1.5).

0.2.1 (2025-12-16)
-------------------

- Mixed-rate MDF writing: separate channel groups per timebase; tolerant stride selection with optional tail trim.
- Timebase metadata: per-signal `tb≈<seconds>` and `src` surfaced in MDF comments, CSV headers, and HDF5 attrs; `timestamp*` treated as nanoseconds.
- Streaming DAQ: emits per-event timestamp arrays (`timestamp0`, `timestamp1`, …, ns) alongside a seconds `TIMESTAMPS` column.
- Validator CLI: added `tools/validate_mf4.py` to summarize MF4 and cross-check CSV/HDF5; supports `--details` for per-signal checks.
- Strict modes: `MDFCreator.save_measurements` gains `strict`, `strict_no_trim`, and `strict_no_synth`; example CLI flags `--strict-mdf`, `--strict-no-trim`, `--strict-no-synth`.

0.2.0 (2025-12-14)
-------------------

- Measurement API: added high-level `asamint.measurement.run()`
  - Supports three acquisition paths: DAQ streaming via callbacks, DAQ non-streaming via `DaqToCsv`, and polling fallback.
  - MDF4 is the primary output; optional CSV and HDF5 exports of converted values.
  - Preserves metadata (author, company, department, project, shortname, subject, time_source) in CSV/HDF5.
- MDF/COMPU_METHODs:
  - Hardened `MDFCreator.ccblock()` to cover IDENTICAL, FORM, LINEAR, RAT_FUNC, TAB_INTP, TAB_NOINTP, TAB_VERB (with and without ranges).
  - Defensive handling for missing/rare conversion types to avoid breaking MDF writing.
- Examples:
  - Updated `asamint/examples/run_measurement.py` to demonstrate DAQ streaming and MDF/CSV/HDF5 outputs using grouped variable names resolved from A2L.

0.1.0 (2020-06-25)
-------------------

* First release on PyPI.
