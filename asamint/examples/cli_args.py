#!/usr/bin/env python
"""
Reusable command-line parser for example measurement scripts.

This component parses arguments specific to example measurement runs and can
remove its own recognized arguments from ``sys.argv`` so that downstream
argument processors (e.g., ``asamint.config.get_application()``) do not see
unrelated options.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from pyxcp.utils.cli import StrippingParser


class MeasurementArgsParser(StrippingParser):
    """Parser for measurement example arguments with argv stripping support.

    Usage:
        parser = MeasurementArgsParser()
        args = parser.parse_and_strip()  # parses and removes handled opts from sys.argv
    """

    def __init__(self, description: str = "Run asamint measurement example") -> None:
        parser = argparse.ArgumentParser(description=description, add_help=False)
        # We add our own -h/--help to avoid interfering with other parsers.
        parser.add_argument(
            "-h", "--help", action="store_true", help="show this help message and exit"
        )
        parser.add_argument(
            "--duration",
            type=float,
            default=60 * 2.0,
            help="Acquisition duration in seconds",
        )
        parser.add_argument(
            "--no-daq",
            action="store_true",
            help="Disable DAQ and use polling acquisition",
        )
        parser.add_argument(
            "--streaming",
            action="store_true",
            help="Enable DAQ streaming callbacks",
        )
        parser.add_argument(
            "--mdf-out",
            type=Path,
            default=None,
            help="Output MDF file path",
        )
        parser.add_argument(
            "--csv-out",
            type=Path,
            default=None,
            help="Optional CSV output path",
        )
        parser.add_argument(
            "--hdf5-out",
            type=Path,
            default=None,
            help="Optional HDF5 output path",
        )
        parser.add_argument(
            "--output-format",
            choices=["MDF", "HDF5"],
            default=None,
            help="Primary output format (overrides config)",
        )
        parser.add_argument(
            "--config",
            type=Path,
            default=None,
            help=(
                "Path to a JSON file containing full configuration for run(): groups, duration, use_daq, streaming, outputs, strict flags, etc. CLI flags override JSON where provided."
            ),
        )
        parser.add_argument(
            "--strict-mdf",
            action="store_true",
            help=(
                "Enable strict MDF writing: fail on any trimming/striding or synthetic timestamps"
            ),
        )
        parser.add_argument(
            "--strict-no-trim",
            action="store_true",
            help=(
                "Disallow timestamp trimming when downsampling (lenient otherwise unless --strict-mdf)"
            ),
        )
        parser.add_argument(
            "--strict-no-synth",
            action="store_true",
            help=(
                "Disallow synthetic timestamps when no compatible timeline is found (lenient otherwise unless --strict-mdf)"
            ),
        )
        super().__init__(parser)
