from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(slots=True)
class GeneralConfig:
    """Snapshot of general project settings."""

    author: str = field(default="")
    company: str = field(default="")
    department: str = field(default="")
    project: str = field(default="")
    shortname: str = field(default="")
    pyxcp_config_file: str = field(default="pyxcp_conf.py")
    a2l_file: str = field(default="")
    a2l_encoding: str = field(default="latin-1")
    a2l_dynamic: bool = field(default=False)
    master_hexfile: str = field(default="")
    master_hexfile_type: str = field(default="ihex")
    mdf_version: str = field(default="4.20")
    output_format: str = field(default="MDF")
    experiments: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LoggingConfig:
    """Snapshot of logging configuration."""

    level: int
    logfile: Path | None = field(default=None)


@dataclass(slots=True)
class CalibrationLimits:
    """Lower/upper bounds for calibration values."""

    lower: float | None = field(default=None)
    upper: float | None = field(default=None)


@dataclass(slots=True)
class CalibrationValue:
    """Container for raw/physical calibration values."""

    name: str
    raw: float | int | bool | str
    phys: float | int | bool | str | None = field(default=None)
    unit: str = field(default="")
    read_only: bool = field(default=False)
    limits: CalibrationLimits | None = field(default=None)


@dataclass(slots=True)
class MeasurementChannel:
    """Descriptor for a measurement signal or channel."""

    name: str
    unit: str = field(default="")
    sample_rate_hz: float | None = field(default=None)
    path: Path | None = field(default=None)
    description: str = field(default="")
