#!/usr/bin/env python
"""
High-level ASAMint API facade.

This module provides a stable import surface for calibration-related APIs,
re-exporting commonly used classes from subpackages to offer a consistent API.

Deprecation policy:
- Symbols removed or renamed are first added to `_DEPRECATED_ALIASES`.
- Accessing a deprecated name emits a DeprecationWarning with a replacement.
- Deprecated aliases are kept until the removal version noted in the map.

Examples
--------
from asamint import AsamMC
from asamint.api import Calibration, ParameterCache

mc = AsamMC()
api = Calibration(mc, image, ParameterCache(), logger)
val = api.load("SomeCharacteristic")
val.phys *= 2
api.save("SomeCharacteristic", val)
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Dict
from warnings import warn

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


@dataclass(frozen=True)
class DeprecatedAlias:
    """Descriptor for deprecated names re-exported by this module."""

    target: str
    remove_in_version: str
    replacement: str | None = None


_DEPRECATED_ALIASES: dict[str, DeprecatedAlias] = {
    "available_measurement_formats": DeprecatedAlias(
        target="asamint.measurement:available_measurement_formats",
        remove_in_version="0.10.0",
        replacement="list_measurement_formats",
    ),
}


def __getattr__(name: str) -> object:
    alias = _DEPRECATED_ALIASES.get(name)
    if alias is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    replacement = alias.replacement or alias.target
    warn(
        (
            f"{name!r} is deprecated. Use {replacement!r} instead. "
            f"It will be removed in {alias.remove_in_version}."
        ),
        category=DeprecationWarning,
        stacklevel=2,
    )
    return _resolve_deprecated_target(alias.target)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_DEPRECATED_ALIASES))


def _resolve_deprecated_target(target: str) -> object:
    if ":" in target:
        module_name, attr_name = target.split(":", 1)
        module = import_module(module_name)
        return getattr(module, attr_name)

    return globals()[target]


__all__ = [
    "Calibration",
    "OnlineCalibration",
    "OfflineCalibration",
    "ParameterCache",
    "ExecutionPolicy",
    "Status",
    "generate_c_structs_from_log",
    "group_measurements",
    "resolve_measurements_by_names",
    "daq_list_from_names",
    "daq_list_from_group",
    "build_daq_lists",
    "run",
    "finalize_from_daq_csv",
    "finalize_daq_csv",
    "finalize_measurement_outputs",
    "RunResult",
    "persist_measurements",
    "list_measurement_formats",
    "register_measurement_format",
    "get_measurement_format",
    "MDFCreator",
    "HDF5Creator",
    "export_cdf",
    "import_cdf",
    "CdfIOResult",
    "create_application",
    "get_application",
    "snapshot_general_config",
    "snapshot_logging_config",
]
