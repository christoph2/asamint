#!/usr/bin/env python
"""
High-level ASAMint API facade.

This module provides a stable import surface for calibration-related APIs,
re-exporting commonly used classes from subpackages to offer a consistent API.

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

from asamint.calibration.api import (
    Calibration,
    ExecutionPolicy,
    OfflineCalibration,
    OnlineCalibration,
    ParameterCache,
    Status,
)
from asamint.calibration.codegen import generate_c_structs_from_log
from asamint.hdf5 import HDF5Creator
from asamint.mdf import MDFCreator
from asamint.measurement import (
    RunResult,
    build_daq_lists,
    daq_list_from_group,
    daq_list_from_names,
    finalize_from_daq_csv,
    finalize_measurement_outputs,
    group_measurements,
    resolve_measurements_by_names,
    run,
)

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
    "finalize_measurement_outputs",
    "RunResult",
    "MDFCreator",
    "HDF5Creator",
]
