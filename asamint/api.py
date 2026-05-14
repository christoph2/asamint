#!/usr/bin/env python
"""High-level ASAMint public API.

This module is the **single stable import surface** for external users.  It
exposes fine-grained convenience functions for every major asamint capability
alongside the lower-level class re-exports.

Convenience functions are organised into sections:

* **Project session** – ``open_project``
* **Offline calibration** – ``open_offline_calibration``, ``load_all_characteristics``
* **Data-format I/O** – ``export_to_cdf`` / ``import_from_cdf``,,
  ``export_to_cvx`` / ``import_from_cvx``,,
  ``export_to_dcm_file`` / ``import_from_dcm``
* **Measurement** – ``run_measurement``, ``finalize_daq``, …
* **Code generation** – ``generate_c_structs_from_log``

Deprecation policy
------------------
Symbols removed or renamed are first added to ``_DEPRECATED_ALIASES``.
Accessing a deprecated name emits a ``DeprecationWarning`` with the
replacement hint.  Aliases are kept until the removal version noted in
the map.

Examples
--------
Minimal CDF export (one call) ::

    from asamint.api import open_project, export_to_cdf

    with open_project() as mc:
        export_to_cdf(mc=mc)

Offline parameter inspection ::

    from asamint.api import open_project, load_all_characteristics

    with open_project() as mc:
        params = load_all_characteristics(mc)
        for name, val in params["VALUE"].items():
            print(f"{name} = {val.phys}")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Core class re-exports
# ---------------------------------------------------------------------------
from asamint.asam import AsamMC
from asamint.calibration import CalibrationData
from asamint.calibration.api import (
    Calibration,
    ExecutionPolicy,
    OfflineCalibration,
    OnlineCalibration,
    ParameterCache,
    Status,
)
from asamint.calibration.codegen import generate_c_structs_from_log
from asamint.cdf import CdfIOResult, export_cdf, import_cdf
from asamint.cmdline import finalize_daq_csv
from asamint.config import (
    create_application,
    get_application,
    snapshot_general_config,
    snapshot_logging_config,
)
from asamint.core.deprecation import DeprecatedAlias, deprecated_dir, deprecated_getattr
from asamint.core.exceptions import (
    AdapterError,
    AsamIntError,
    CalibrationError,
    ConfigurationError,
    FileFormatError,
    LimitViolation,
    RangeError,
    ReadOnlyError,
    VirtualWriteError,
)
from asamint.core.models import (
    CalibrationLimits,
    CalibrationValue,
    GeneralConfig,
    LoggingConfig,
    MeasurementChannel,
)
from asamint.cvx import CVXExporter, CVXImporter, export_cvx, import_cvx
from asamint.damos import DcmExporter, export_to_dcm, import_dcm
from asamint.measurement import (
    HDF5Creator,
    MDFCreator,
    RunResult,
    build_daq_lists,
    daq_list_from_group,
    daq_list_from_names,
    finalize_from_daq_csv,
    finalize_measurement_outputs,
    get_measurement_format,
    group_measurements,
    list_measurement_formats,
    persist_measurements,
    register_measurement_format,
    resolve_measurements_by_names,
    run,
)

# ---------------------------------------------------------------------------
# Deprecation map
# ---------------------------------------------------------------------------

_DEPRECATED_ALIASES: dict[str, DeprecatedAlias] = {
    "available_measurement_formats": DeprecatedAlias(
        target="asamint.measurement:available_measurement_formats",
        remove_in_version="0.10.0",
        replacement="list_measurement_formats",
    ),
}


def __getattr__(name: str) -> object:
    return deprecated_getattr(name, _DEPRECATED_ALIASES, globals(), __name__)


def __dir__() -> list[str]:
    return deprecated_dir(_DEPRECATED_ALIASES, globals())


# =========================================================================
# Convenience functions
# =========================================================================

# ---------------------------------------------------------------------------
# Project session
# ---------------------------------------------------------------------------


def open_project(
    config_file: str | Path = "asamint_conf.py",
) -> AsamMC:
    """Open an asamint project and return the :class:`AsamMC` session.

    The returned object is a context manager — use it with ``with`` to
    ensure all resources (A2L database, XCP master, …) are released on
    exit::

        with open_project("my_conf.py") as mc:
            print(mc.a2l_file)

    The function creates the global traitlets-based ``Asamint``
    application singleton (if it does not yet exist) and then constructs
    the ``AsamMC`` session on top of it.

    Args:
        config_file: Path to the Python configuration file
            (default ``asamint_conf.py``).

    Returns:
        Fully initialised :class:`AsamMC` session.

    Raises:
        FileNotFoundError: If *config_file* or the referenced A2L file
            does not exist.
        ConfigurationError: If the configuration is invalid.
    """
    create_application()
    return AsamMC()


# ---------------------------------------------------------------------------
# Offline calibration
# ---------------------------------------------------------------------------


def open_offline_calibration(
    a2l_path: str | Path | None = None,
    hex_path: str | Path | None = None,
    *,
    hex_type: str = "ihex",
) -> CalibrationData:
    """Open a hex file for offline calibration and return a ready-to-use session.

    This is a convenience wrapper that sets up the configuration
    singleton, creates an :class:`AsamMC` session, builds a
    :class:`CalibrationData` instance and loads the hex file — all in
    a single call.  The returned object is a context manager::

        with open_offline_calibration("demo.a2l", "demo.hex") as cal:
            cal.load_hex()

    Args:
        a2l_path: Path to the A2L description file.  ``None`` uses the
            config value.
        hex_path: Path to the Intel-HEX or S-Record file.  ``None``
            uses the config value.
        hex_type: ``"ihex"`` (default) or ``"srec"``.

    Returns:
        :class:`CalibrationData` with the image already loaded
        (``cal.image`` and ``cal.api`` are set).
    """
    create_application()
    mc = AsamMC()
    cdm = CalibrationData(mc)
    cdm.load_hex_file(hexfile=hex_path, hexfile_type=hex_type)
    return cdm


def load_all_characteristics(
    mc_or_cdm: AsamMC | CalibrationData,
    *,
    xcp_master: Any | None = None,
    hexfile: str | Path | None = None,
    hexfile_type: str = "ihex",
) -> dict[str, dict[str, Any]]:
    """Load **all** calibration parameters in one call.

    Processes axis points, values, ASCII strings, value blocks, curves,
    maps and cubes and returns the populated parameter dictionary keyed
    by category (``"VALUE"``, ``"CURVE"``, ``"MAP"``, …).

    Args:
        mc_or_cdm: Either an :class:`AsamMC` (a ``CalibrationData`` is
            created internally) or an already-constructed
            :class:`CalibrationData`.
        xcp_master: Optional XCP master — if given, data is fetched
            from the live ECU instead of a hex file.
        hexfile: Path to the hex file (``None`` uses the config default).
        hexfile_type: ``"ihex"`` or ``"srec"``.

    Returns:
        ``dict[category, dict[name, calibrated_object]]`` — the same
        object exposed by ``CalibrationData.parameters``.

    Example::

        with open_project() as mc:
            params = load_all_characteristics(mc)
            for name, v in params["VALUE"].items():
                print(f"{name} = {v.phys}")
    """
    if isinstance(mc_or_cdm, CalibrationData):
        cdm = mc_or_cdm
    else:
        cdm = CalibrationData(mc_or_cdm)
    cdm.load_characteristics(
        xcp_master=xcp_master,
        hexfile=hexfile,
        hexfile_type=hexfile_type,
    )
    return cdm.parameters


# ---------------------------------------------------------------------------
# Data-format I/O — CDF
# ---------------------------------------------------------------------------


def export_to_cdf(
    a2l_path: str | Path | None = None,
    hex_path: str | Path | None = None,
    output_path: str | Path | None = None,
    *,
    hex_type: str = "ihex",
    mc: AsamMC | None = None,
    parameters: dict[str, dict[str, Any]] | None = None,
) -> Path:
    """Export calibration parameters to an ASAM CDF20 XML file.

    When *parameters* are provided the HEX file is **not** re-read —
    this is the efficient path when :func:`load_all_characteristics`
    has already been called::

        with open_project() as mc:
            params = load_all_characteristics(mc)
            cdf_path = export_to_cdf(mc=mc, parameters=params)

    If *parameters* is ``None`` the function loads them from the HEX
    file itself (stand-alone one-shot usage)::

        with open_project() as mc:
            cdf_path = export_to_cdf(mc=mc)

    Args:
        a2l_path: Path to the A2L file.  ``None`` uses the config value.
        hex_path: Path to the hex file.  ``None`` uses the config value.
        output_path: Destination ``.cdfx`` path.  ``None`` auto-generates
            a filename in the ``parameters/`` sub-directory.
        hex_type: ``"ihex"`` (default) or ``"srec"``.
        mc: Pre-existing :class:`AsamMC` session.  If ``None`` a
            temporary one is created (and closed after export).
        parameters: Already-loaded parameter dict (as returned by
            :func:`load_all_characteristics` or
            ``CalibrationData.parameters``).  When given, the HEX file
            is **not** read again.

    Returns:
        Path to the written CDF XML file.
    """
    from asamint.cdf import CDFCreator

    own_mc: bool = mc is None
    session: AsamMC = mc if mc is not None else AsamMC()
    if own_mc:
        create_application()
        session = AsamMC()
    try:
        if parameters is None:
            cdm = CalibrationData(session)
            cdm.load_characteristics(hexfile=hex_path, hexfile_type=hex_type)
            parameters = cdm.parameters
        cdc = CDFCreator(parameters, asam_mc=session)
        cdc.save()
        written = session.sub_dir("parameters") / session.generate_filename(".cdfx")
        return written
    finally:
        if own_mc:
            session.close()


def import_from_cdf(
    xml_path: str | Path,
    db_path: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> CdfIOResult:
    """Import calibration parameters from a CDF20 XML into an MSRSW database.

    Thin wrapper around :func:`asamint.cdf.import_cdf` re-exported here
    for discoverability.

    Args:
        xml_path: Path to the ``.cdfx`` file.
        db_path: Destination ``.msrswdb`` path.
        logger: Optional logger.

    Returns:
        :class:`CdfIOResult` with the written paths.
    """
    return import_cdf(xml_path=xml_path, db_path=db_path, logger=logger)


# ---------------------------------------------------------------------------
# Data-format I/O — CVX
# ---------------------------------------------------------------------------


def export_to_cvx(
    file_path: str | Path,
    records: list[dict[str, Any]],
    *,
    functions: list[str] | None = None,
    variants: dict[str, list[str]] | None = None,
    delimiter: str = ";",
    float_format: str = "%.9g",
    logger: logging.Logger | None = None,
) -> Path:
    """Export calibration records to an ASAM CVX file.

    Args:
        file_path: Destination ``.cvx`` path.
        records: List of record dicts (as produced by :func:`import_from_cvx`).
        functions: Optional list of function names for the file header.
        variants: Optional mapping of variant criteria to value lists.
        delimiter: Field delimiter (default ``";"``).
        float_format: C-style format string for floats (default ``"%.9g"``).
        logger: Optional logger.

    Returns:
        Path to the written CVX file.
    """
    return export_cvx(
        file_path=file_path,
        records=records,
        functions=functions,
        variants=variants,
        delimiter=delimiter,
        float_format=float_format,
        logger=logger,
    )


def import_from_cvx(
    file_path: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Import calibration records from a CVX file.

    Args:
        file_path: Path to the ``.cvx`` file.
        logger: Optional logger.

    Returns:
        List of record dicts with keys *identifier*, *type*, *values*, etc.
    """
    return import_cvx(file_path=file_path, logger=logger)


# ---------------------------------------------------------------------------
# Data-format I/O — DCM (DAMOS)
# ---------------------------------------------------------------------------


def export_to_dcm_file(
    db_path: str | Path,
    output_path: str | Path,
    *,
    h5_path: str | Path | None = None,
) -> bool:
    """Export calibration data from an MSRSW database to a DAMOS DCM file.

    Args:
        db_path: Path to the ``.msrswdb`` source database.
        output_path: Destination ``.dcm`` path.
        h5_path: Optional path to an HDF5 CalibrationDB for axis data.
            When ``None`` a co-located ``.h5`` file is used if it exists.

    Returns:
        ``True`` if the export succeeded.
    """
    return export_to_dcm(db_path, output_path, h5_path)


def import_from_dcm(
    source: str | Path,
    *,
    encoding: str = "latin-1",
) -> dict[str, Any]:
    """Parse a DCM 2.0 file or string and return the structured data.

    Args:
        source: File path or raw DCM text string.
        encoding: Character encoding for file-based reads.

    Returns:
        Dict with keys ``"kopf"``, ``"rumpf"``, ``"version"``.
    """
    return import_dcm(source=source, encoding=encoding)


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


def run_measurement(
    *args: Any,
    **kwargs: Any,
) -> RunResult:
    """Run a measurement session.

    This is a convenience alias for :func:`asamint.measurement.run`
    with a clearer name.  All arguments are forwarded as-is.

    Returns:
        :class:`RunResult` with the output file paths and metadata.
    """
    return run(*args, **kwargs)


def finalize_daq(
    csv_files: Any,
    *,
    csv_out: str | Path | None = None,
    hdf5_out: str | Path | None = None,
    units: dict[str, str | None] | None = None,
    project_meta: dict[str, Any] | None = None,
) -> Any:
    """Finalize DAQ CSV outputs into merged CSV/HDF5 with metadata.

    Convenience alias for :func:`asamint.cmdline.finalize_daq_csv`.

    Args:
        csv_files: Iterable of DAQ CSV file paths.
        csv_out: Optional merged CSV output path.
        hdf5_out: Optional HDF5 output path.
        units: Optional unit mapping ``{channel: unit}``.
        project_meta: Optional project metadata dict.

    Returns:
        Result of the finalization (format-dependent).
    """
    return finalize_daq_csv(
        csv_files,
        csv_out=csv_out,
        hdf5_out=hdf5_out,
        units=units,
        project_meta=project_meta,
    )


# =========================================================================
# __all__
# =========================================================================

__all__ = [
    # -- Project session ---------------------------------------------------
    "open_project",
    "AsamMC",
    # -- Calibration classes -----------------------------------------------
    "Calibration",
    "OnlineCalibration",
    "OfflineCalibration",
    "ParameterCache",
    "CalibrationData",
    "ExecutionPolicy",
    "Status",
    # -- Calibration convenience -------------------------------------------
    "open_offline_calibration",
    "load_all_characteristics",
    # -- Data-format I/O: CDF ----------------------------------------------
    "export_to_cdf",
    "import_from_cdf",
    "export_cdf",
    "import_cdf",
    "CdfIOResult",
    # -- Data-format I/O: CVX ----------------------------------------------
    "export_to_cvx",
    "import_from_cvx",
    "export_cvx",
    "import_cvx",
    "CVXImporter",
    "CVXExporter",
    # -- Data-format I/O: DCM ----------------------------------------------
    "export_to_dcm_file",
    "import_from_dcm",
    "export_to_dcm",
    "import_dcm",
    "DcmExporter",
    # -- Measurement -------------------------------------------------------
    "run_measurement",
    "finalize_daq",
    "run",
    "finalize_from_daq_csv",
    "finalize_daq_csv",
    "finalize_measurement_outputs",
    "group_measurements",
    "resolve_measurements_by_names",
    "daq_list_from_names",
    "daq_list_from_group",
    "build_daq_lists",
    "persist_measurements",
    "RunResult",
    "list_measurement_formats",
    "register_measurement_format",
    "get_measurement_format",
    "MDFCreator",
    "HDF5Creator",
    # -- Code generation ---------------------------------------------------
    "generate_c_structs_from_log",
    # -- Configuration -----------------------------------------------------
    "create_application",
    "get_application",
    "snapshot_general_config",
    "snapshot_logging_config",
    # -- DTOs & models -----------------------------------------------------
    "GeneralConfig",
    "LoggingConfig",
    "CalibrationLimits",
    "CalibrationValue",
    "MeasurementChannel",
    # -- Exceptions --------------------------------------------------------
    "AsamIntError",
    "ConfigurationError",
    "AdapterError",
    "CalibrationError",
    "ReadOnlyError",
    "VirtualWriteError",
    "RangeError",
    "LimitViolation",
    "FileFormatError",
    # -- Deprecation helpers -----------------------------------------------
    "DeprecatedAlias",
]
