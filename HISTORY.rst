=======
History
=======

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
