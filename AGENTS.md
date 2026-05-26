# AGENTS.md — Codebase Guidance for AI Agents

This document accelerates productive AI agent work on **asamint**, a Python automotive calibration/ASAM integration library. Consult `.github/copilot-instructions.md` for detailed coding rules; this file focuses on architecture and workflow essentials.

## Quick Start

- **Setup:** `poetry install` (fallback: `pip install -r requirements_dev.txt`)
- **Test:** `poetry run pytest` (adds `-v --tb=short --junitxml=result.xml` automatically)
- **Lint:** `poetry run ruff check . && poetry run ruff format .` (line-length: 132)
- **Single test:** `poetry run pytest tests/test_calibration.py::TestName -v`
- **Python:** 3.10+ only; wheels built via `cibuildwheel` in CI

## Core Architecture

### **Adapter Boundary** (Critical for All Code)
**All** external library access (pyXCP, pya2l, objutils, asammdf) must route through **`asamint/adapters/`**—never import these directly elsewhere:
- `adapters.a2l`: A2L database, dtype/axis helpers (`asam_type_size`, `fix_axis_par`, ...)
- `adapters.xcp`: XCP master creation, DAQ configuration
- `adapters.objutils`: Binary image read/write over `_AddressMappedImage`
- `adapters.mdf`: MDF file I/O
- `adapters.measurement`: Format registry (plugins for HDF5, MDF, etc.)

Adapter modules **re-export** types for internal use; no transitive imports of wrapped libs.

### **Public API Surface** (`asamint/api.py`)
External users **always** import from here:
```python
from asamint.api import Calibration, ParameterCache, run, export_cdf
```
Re-exports core classes: `Calibration`, `OnlineCalibration`, `OfflineCalibration`, `ParameterCache`, `ExecutionPolicy`, `Status`, measurement/format functions, CDF/CVX/DCM I/O.

**Deprecation path:** when renaming/removing public names → add `_DEPRECATED_ALIASES` entry + test in `tests/test_api_stability.py` (see `CONTRIBUTING.rst` line 105-107).

### **Calibration System** (High-Level Flow)
```
User Code
  ↓
asamint.api.Calibration → asamint.calibration.api.Calibration
  ↓
CalibrationAdapter (Protocol: read_asam_*, write_asam_*)
  ↓
pya2l.DB (characteristics, axes from A2L)  +  objutils.Image (binary ECU dump)
  ↓
ParameterCache (caches CURVE/MAP/Value; enforces limits, readonly checks)
```
- **Offline mode:** reads/writes via `objutils` `read_asam_*/write_asam_*`
- **Online mode:** uses pyXCP `create_master` for hardware communication
- **CalibrationDB:** HDF5 backend for persistence; stores AXIS_PTS; COM_AXIS/RES_AXIS/CURVE_AXIS as soft-links

### **Configuration** (Traitlets-based)
- Entry: `create_application()` → `Asamint` Application (inherits `traitlets.Application`)
- File: `asamint_conf.py` in config directory (Python, not YAML)
- Access: `get_application()` for runtime; `snapshot_general_config()` / `snapshot_logging_config()` for snapshots
- XCP config auto-merged if external pyXCP config exists

### **Measurement & Data Formats**
- **Measurement:** `asamint.measurement` runs acquisition; formats registered via `register_measurement_format()`
  - Builders: `MDFCreator`, `HDF5Creator`; DAQ lists from characteristics+axes
  - Finalize: CSV→HDF5 conversion via `finalize_from_daq_csv()`
- **Data Import/Export:** CDF (XML), CVX, DCM (ANTLR-parsed); DAMOS walker for MSRSW
- **Exceptions:** Hierarchy from `asamint.core.exceptions`: `AsamIntError` → `ConfigurationError`, `AdapterError`, `CalibrationError` (→ `ReadOnlyError`, `RangeError`), `FileFormatError`

## Test Organization & Fixtures

**Test data in `tests/` is sacred—never move/rename:**
- `tests/*.a2l`, `tests/*.hex` — CDF20demo & ASAP2_Demo_V161 fixtures for offline calibration tests
- `tests/*.msrswdb` — legacy measurement database fixtures
- Generated `.a2ldb` files are read-only SQLite caches; auto-generated if missing

**Three-tier test strategy:**
1. **Core/Unit** (`asamint.core` tests): fast, parametrized, no external I/O
2. **Adapter tests**: use fakes/mocks; never hit real hardware/network
3. **Integration** (calibration/measurement): leverage `tests/*.a2l`/`.hex` fixtures; offline uses CDF20demo; measurement uses DAQ CSV synthesizers
4. **API surface** (`test_api_stability.py`): import only from `asamint.api`; validate public entrypoints

Commands:
```bash
poetry run pytest tests/test_calibration.py -v           # Single module
poetry run pytest tests/test_calibration.py::TestClass::test_method -v
poetry run pytest -k "test_load" --tb=short            # Keyword filter
```

## Coding Conventions (vs. Standard Python)

| Aspect | Rule | Example |
|--------|------|---------|
| **Imports** | Complete, no `from x import *`; re-export via adapter needed | `from asamint.adapters.a2l import AxisPts` |
| **Dataclasses** | Use for DTOs; always `slots=True`; full type hints | `@dataclass(slots=True)\nclass CalibValue: ...` |
| **Names** | snake_case (funcs/modules), PascalCase (classes) | `def read_asam_value(...)` vs. `class ParameterCache` |
| **Line length** | 132 chars (ruff config in `pyproject.toml`) | — |
| **Logging** | Never `print()`; use `asamint.core.logging.configure_logging()` | `logger = logging.getLogger(__name__)` |
| **Exceptions** | Raise from `asamint.core.exceptions`; catch specific types | `raise ConfigurationError("msg")` not `Exception` |
| **Spacing** | 4-space indent; 2 lines between classes, 1 between methods | — |
| **Typing** | Full annotations; `Optional[]` or `/None`, avoid `Any` | `def load(self, name: str) -> CalibrationValue:` |

## Key File Locations

| Path | Purpose |
|------|---------|
| `asamint/api.py` | Public API façade — all external imports route here |
| `asamint/calibration/api.py` | Core `Calibration` implementation (2500+ lines) |
| `asamint/calibration/db.py` | HDF5-based persistence layer |
| `asamint/adapters/` | Wrapper gates for pyXCP, pya2l, objutils, asammdf |
| `asamint/core/exceptions.py` | Exception hierarchy |
| `asamint/core/models.py` | DTOs: `GeneralConfig`, `CalibrationLimits`, `CalibrationValue` |
| `asamint/measurement/` | Acquisition, DAQ list building, format plugins |
| `asamint/config/` | Traitlets config system; `create/get_application()` |
| `tests/test_*.py` | Unit/integration tests; fixtures under `tests/` directory |
| `.github/copilot-instructions.md` | Detailed coding standards |

## Critical Gotchas

1. **Adapter Imports**: If you see a direct `import pyxcp` or `import pya2l` outside `adapters/`, flag it—breaks the boundary.
2. **Test Data**: `.a2ldb` SQLite files are auto-generated caches on first use; `.a2l` and `.hex` must exist. Never delete without regenerating.
3. **Deprecated Names**: When renaming public API, must add `_DEPRECATED_ALIASES` entry **and** test—else old code silently breaks.
4. **CalibrationDB Soft-Links**: HDF5 groups storing COM_AXIS/RES_AXIS/CURVE_AXIS must point to AXIS_PTS; mismatched links cause load failures.
5. **Config Search Path**: `asamint_conf.py` searched in current dir, home, config dirs (OS-specific). Test env isolation critical.
6. **Calibration Value Limits**: After `.phys` modification, must call `api.save()` on same `Calibration` instance to apply readonly/range checks. Direct `.raw` edits bypass validation.

## Cross-Component Data Flows

### Offline Calibration Read
```
Calibration.load("CharName")
  ↓ (query A2L via pya2l.DB)
  ↓ (find address in ASAM metadata)
  ↓ (objutils.Image.read_asam_*(...dtype, byteOrder from A2L...))
  ↓ (apply CompuMethod if present)
  ↓ (return CalibrationValue with .phys, .raw)
```

### Measurement Run
```
run(daq_list, acquisition_func, ...)
  ↓ (build XCP DAQ from characteristics + axes via pyXCP)
  ↓ (start/stop hardware measurements)
  ↓ (convert raw samples → channels via timestamps, CompuMethod)
  ↓ (write MDF or HDF5 via asammdf / h5py)
  ↓ (persist DAQ CSV metadata)
```

### CDF Round-Trip
```
import_cdf(cdf_xml) → Calibration cache (HDF5: values, axes, metadata)
  ↓ (MSRSW walker; CompuMethod eval)
  ↓ (.load()/.save() methods read/write to HDF5)
export_cdf(hdf5) → XML (reverse walk, rebuild CDF structure)
```

## Extending asamint

### Adding a Measurement Format
1. Create `MyFormatCreator(MeasurementCreator)` in `asamint/measurement/` submodule
2. Implement `create(...)` → writes dialect-specific file
3. Register in tests via `register_measurement_format("myformat", MyFormatCreator)`
4. Re-export in `asamint/api.py` if user-facing

### Adding an Adapter for New External Library
1. Create `asamint/adapters/mylib.py` with wrapper class/functions
2. **Never** import the external lib outside this module
3. Re-export types needed by core logic (e.g., `from mylib import SomeType`)
4. Document expected interface (Protocol or ABC in `asamint.core.abc`)
5. Mock in tests; never hit real instance

### Adding a Deprecated API Name
1. Rename the symbol; update all internal calls
2. Add entry to `asamint/api._DEPRECATED_ALIASES`: `"old_name": DeprecatedAlias(target="...", remove_in_version="0.x.0", replacement="new_name")`
3. Write test in `tests/test_api_stability.py` to catch the deprecation warning

## Debugging Tips

- **A2L lookup fails:** Check `pya2l.DB.find_characteristic(name)` returns non-None; validate ASAM datatypes via `adapters.a2l.asam_type_size()`
- **Calibration read returns garbage:** Verify `Image.read_asam_*()` address is aligned; check endianness via `byte_order()` from `asamint.core`
- **Measurement DAQ doesn't run:** Inspect XCP `daq_list` structure; ensure `create_master()` initialized client; check `ExecutionPolicy` (EXCEPT vs. RETURN_ERROR)
- **HDF5 group not found:** CalibrationDB must pre-create axis groups; validate soft-links via `h5py` `.get(..., default=None)`
- **Test flakes on CI but not local:** Config file (`asamint_conf.py`) may be stale; use `snapshot_general_config()` in tests to isolate

## References

- **Automotive standards:** A2L (ASAM 2.1), XCP protocol (ASAM 3.x), AUTOSAR (comments only)
- **Dependencies:** Poetry for packaging; `pyproject.toml` declares all; dev extras in `[tool.poetry.group.dev.dependencies]`
- **CI/CD:** GitHub Actions (`.github/workflows/pythonapp.yml`); builds wheels via `cibuildwheel` for 3.10–3.13 on Linux/Windows/macOS
- **Docs:** ReStructuredText in `docs/`; generated via Sphinx (see `docs/conf.py`)
