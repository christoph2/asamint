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
from collections.abc import Sequence
from pathlib import Path
from typing import List, Optional, Tuple


class MeasurementArgsParser:
    """Parser for measurement example arguments with argv stripping support.

    Usage:
        parser = MeasurementArgsParser()
        args = parser.parse_and_strip()  # parses and removes handled opts from sys.argv
    """

    def __init__(self, description: str = "Run asamint measurement example") -> None:
        self._parser = argparse.ArgumentParser(description=description, add_help=False)
        # We add our own -h/--help to avoid interfering with other parsers.
        self._parser.add_argument(
            "-h", "--help", action="store_true", help="show this help message and exit"
        )
        self._parser.add_argument(
            "--duration",
            type=float,
            default=60 * 2.0,
            help="Acquisition duration in seconds",
        )
        self._parser.add_argument(
            "--no-daq",
            action="store_true",
            help="Disable DAQ and use polling acquisition",
        )
        self._parser.add_argument(
            "--streaming",
            action="store_true",
            help="Enable DAQ streaming callbacks",
        )
        self._parser.add_argument(
            "--mdf-out",
            type=Path,
            default=None,
            help="Output MDF file path",
        )
        self._parser.add_argument(
            "--csv-out",
            type=Path,
            default=None,
            help="Optional CSV output path",
        )
        self._parser.add_argument(
            "--hdf5-out",
            type=Path,
            default=None,
            help="Optional HDF5 output path",
        )
        self._parser.add_argument(
            "--output-format",
            choices=["MDF", "HDF5"],
            default=None,
            help="Primary output format (overrides config)",
        )
        self._parser.add_argument(
            "--config",
            type=Path,
            default=None,
            help=(
                "Path to a JSON file containing full configuration for run(): groups, duration, use_daq, streaming, outputs, strict flags, etc. CLI flags override JSON where provided."
            ),
        )
        self._parser.add_argument(
            "--strict-mdf",
            action="store_true",
            help=(
                "Enable strict MDF writing: fail on any trimming/striding or synthetic timestamps"
            ),
        )
        self._parser.add_argument(
            "--strict-no-trim",
            action="store_true",
            help=(
                "Disallow timestamp trimming when downsampling (lenient otherwise unless --strict-mdf)"
            ),
        )
        self._parser.add_argument(
            "--strict-no-synth",
            action="store_true",
            help=(
                "Disallow synthetic timestamps when no compatible timeline is found (lenient otherwise unless --strict-mdf)"
            ),
        )

    def parse_known(
        self, argv: Sequence[str] | None = None
    ) -> tuple[argparse.Namespace, list[str]]:
        """Parse known args from ``argv`` and return (namespace, remaining).

        Does not mutate ``sys.argv``.
        """
        if argv is None:
            argv = sys.argv[1:]
        ns, remaining = self._parser.parse_known_args(argv)
        # Emulate standard -h/--help behavior
        if getattr(ns, "help", False):
            # Print help and exit similarly to ArgumentParser
            # We need a temporary full parser to render standard help including program name
            full = argparse.ArgumentParser(description=self._parser.description)
            for action in self._parser._actions:
                if action.option_strings and action.dest == "help":
                    continue
                full._add_action(action)
            full.print_help()
            sys.exit(0)
        return ns, list(remaining)

    def strip_from_argv(self, argv: list[str] | None = None) -> None:
        """Remove this parser's recognized options from ``sys.argv`` in-place.

        If ``argv`` is provided, it is treated as a mutable list whose content
        will be replaced with the stripped version (first element preserved as
        program name). If omitted, ``sys.argv`` is modified.
        """
        arg_list = argv if argv is not None else sys.argv
        if not arg_list:
            return
        ns, remaining = self.parse_known(
            arg_list[1:]
        )  # noqa: F841 (ns is intentionally not used here)
        # Rebuild argv with program name + remaining
        prog = arg_list[0]
        arg_list[:] = [prog] + remaining

    def parse_and_strip(self, argv: list[str] | None = None) -> argparse.Namespace:
        """Parse options and strip them from argv; returns the parsed namespace."""
        arg_list = argv if argv is not None else sys.argv
        ns, remaining = self.parse_known(arg_list[1:])
        # mutate
        prog = arg_list[0]
        arg_list[:] = [prog] + remaining
        return ns
