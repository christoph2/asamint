from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class GeneralConfig:
    """Snapshot of general project settings."""

    author: str = ""
    company: str = ""
    department: str = ""
    project: str = ""
    shortname: str = ""
    pyxcp_config_file: str = "pyxcp_conf.py"
    a2l_file: str = ""
    a2l_encoding: str = "latin-1"
    a2l_dynamic: bool = False
    master_hexfile: str = ""
    master_hexfile_type: str = "ihex"
    mdf_version: str = "4.20"
    output_format: str = "MDF"
    experiments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LoggingConfig:
    """Snapshot of logging configuration."""

    level: int
    logfile: Path | None = None


@dataclass(slots=True)
class CalibrationLimits:
    """Lower/upper bounds for calibration values."""

    lower: float | None = None
    upper: float | None = None


@dataclass(slots=True)
class CalibrationValue:
    """Container for raw/physical calibration values."""

    name: str
    raw: float | int | bool | str
    phys: float | int | bool | str | None = None
    unit: str = ""
    read_only: bool = False
    limits: CalibrationLimits | None = None


@dataclass(slots=True)
class MeasurementChannel:
    """Descriptor for a measurement signal or channel."""

    name: str
    unit: str = ""
    sample_rate_hz: float | None = None
    path: Path | None = None
    description: str = ""
