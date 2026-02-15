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

__all__ = [
    "Calibration",
    "OnlineCalibration",
    "OfflineCalibration",
    "ParameterCache",
    "ExecutionPolicy",
    "Status",
    "generate_c_structs_from_log",
]
