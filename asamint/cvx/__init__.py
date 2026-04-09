"""Calibration Values Exchange (CVX) format import/export.

CVX is an ASAM CSV-based format for exchanging calibration data between
MC systems.  This package provides :class:`CVXImporter` for reading CVX
files and :class:`CVXExporter` for writing them.

Convenience helpers :func:`import_cvx` and :func:`export_cvx` cover the
most common use-cases.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .exporter import CVXExporter
from .importer import CVXImporter
from asamint.core.deprecation import DeprecatedAlias, deprecated_dir, deprecated_getattr

__all__ = [
    "CVXExporter",
    "CVXImporter",
    "export_cvx",
    "import_cvx",
]

_DEPRECATED_ALIASES: dict[str, DeprecatedAlias] = {}


def __getattr__(name: str) -> object:
    return deprecated_getattr(name, _DEPRECATED_ALIASES, globals(), __name__)


def __dir__() -> list[str]:
    return deprecated_dir(_DEPRECATED_ALIASES, globals())


def import_cvx(
    file_path: str | Path,
    *,
    logger: logging.Logger | None = None,
) -> list[dict[str, Any]]:
    """Import calibration records from a CVX file.

    Args:
        file_path: Path to the ``.cvx`` file.
        logger: Optional logger instance.

    Returns:
        List of record dicts with keys *identifier*, *type*, *values*,
        *axis_x*, *axis_y*, *variants*, *function*, *display_identifier*.
    """
    if logger:
        logger.info("Importing CVX from %s", file_path)
    importer = CVXImporter()
    return importer.import_file(str(file_path))


def export_cvx(
    file_path: str | Path,
    records: list[dict[str, Any]],
    *,
    functions: list[str] | None = None,
    variants: dict[str, list[str]] | None = None,
    delimiter: str = ";",
    float_format: str = "%.9g",
    logger: logging.Logger | None = None,
) -> Path:
    """Export calibration records to a CVX file.

    Args:
        file_path: Destination path for the ``.cvx`` file.
        records: List of record dicts (same schema as :func:`import_cvx` output).
        functions: Optional list of function names for the file header.
        variants: Optional mapping of variant criteria to value lists.
        delimiter: Field delimiter (default ``";"``)
        float_format: C-style format string for floats (default ``"%.9g"``).
        logger: Optional logger instance.

    Returns:
        The resolved output :class:`~pathlib.Path`.
    """
    out = Path(file_path)
    if logger:
        logger.info("Exporting CVX to %s", out)
    exporter = CVXExporter(
        delimiter=delimiter,
        float_format=float_format,
        logger=logger or logging.getLogger(__name__),
    )
    exporter.export_file(str(out), records, functions=functions, variants=variants)
    return out
