#!/usr/bin/env python
"""
Example: High-level measurement run using asamint.measurement

This example demonstrates how to acquire measurements based on A2L names
using pyXCP DAQ (streaming by default) and write MDF4 as primary output.
CSV will be written alongside MDF; HDF5 is optional.

Prerequisites:
- Configure asamint via asamint_conf.py (A2L path and pyXCP transport).
"""

import json
from pathlib import Path

from asamint.config import get_application
from asamint.examples.cli_args import MeasurementArgsParser
from asamint.measurement import run


def parse_args():
    """Parse example-specific arguments and strip them from sys.argv.

    Returns the parsed namespace. Any recognized options are removed from
    ``sys.argv`` so that subsequent consumers (e.g., ``get_application()``)
    don't see them.
    """
    parser = MeasurementArgsParser()
    return parser.parse_and_strip()


def main() -> None:
    args = parse_args()

    # Initialize application (reads asamint_conf.py)
    app = get_application()
    if args.output_format:
        app.general.output_format = args.output_format.upper()
    app.log.info("Starting measurement example")

    """
    name="pwm_stuff",
    event_num=2,
    stim=False,
    enable_timestamps=True,
    measurements=[
        ("channel1", 0x1BD004, 0, "F32"),
        ("period", 0x001C0028, 0, "F32"),
        ("channel2", 0x1BD008, 0, "F32"),
        ("PWMFiltered", 0x1BDDE2, 0, "U8"),
        ("PWM", 0x1BDDDF, 0, "U8"),
        ("Triangle", 0x1BDDDE, 0, "I8"),
    ],
    priority=0,
    prescaler=1
    """

    # Default groups if no JSON config is provided: mix of explicit variable names and A2L group expansion
    default_groups = [
        {
            "name": "pwm_stuff",
            "event_num": 2,
            "enable_timestamps": True,
            "group_name": "PWM_Signals",
            # "variables": [
            #    "channel1",
            #    "channel2",
            #    "period",
            #    "PWMFiltered",
            #    "PWM",
            #    "Triangle",
            # ],
        },
        {
            "name": "Example_Double",
            "group_name": "Example_Double",
            "event_num": 1,
            "enable_timestamps": True,
        },
    ]

    # If a JSON config is provided, load the full configuration for run()
    json_cfg: dict | None = None
    if getattr(args, "config", None):
        try:
            cfg_path = Path(args.config)
            with cfg_path.open("r", encoding="utf-8") as fh:
                json_cfg = json.load(fh)
            app.log.info(f"Loaded configuration from {cfg_path}")
        except Exception as e:
            app.log.warning(
                f"Failed to load config {args.config}: {e}. Falling back to CLI/defaults."
            )
            json_cfg = None

    # Helper to fetch a key from JSON config with fallback
    def _cfg(key: str, default):
        if json_cfg is not None and key in json_cfg and json_cfg[key] is not None:
            return json_cfg[key]
        return default

    effective_groups = _cfg("groups", default_groups)
    # Determine run() parameters with JSON taking precedence by default; allow some CLI overrides when provided
    # JSON can specify either duration (seconds) or samples (exclusive). If samples present in JSON, prefer it and ignore CLI duration.
    samples = None
    duration = _cfg("duration", args.duration)
    if (
        json_cfg is not None
        and "samples" in json_cfg
        and json_cfg["samples"] is not None
    ):
        try:
            samples = int(json_cfg["samples"])  # prefer JSON samples
            duration = None  # enforce exclusivity
        except Exception:
            app.log.warning("Invalid 'samples' in JSON config; ignoring.")
    # Optional polling period override from JSON for non-DAQ path
    period_s = None
    if (
        json_cfg is not None
        and "period_s" in json_cfg
        and json_cfg["period_s"] is not None
    ):
        try:
            period_s = float(
                json_cfg["period_s"]
            )  # used by polling path or DAQ CSV sleep
        except Exception:
            app.log.warning("Invalid 'period_s' in JSON config; ignoring.")
    use_daq = _cfg("use_daq", not args.no_daq)
    streaming = _cfg("streaming", args.streaming)
    mdf_out = _cfg("mdf_out", str(args.mdf_out) if args.mdf_out else None)
    csv_out = _cfg("csv_out", str(args.csv_out) if args.csv_out else None)
    hdf5_out = _cfg("hdf5_out", str(args.hdf5_out) if args.hdf5_out else None)
    strict_mdf = bool(_cfg("strict_mdf", bool(getattr(args, "strict_mdf", False))))
    strict_no_trim = bool(
        _cfg("strict_no_trim", bool(getattr(args, "strict_no_trim", False)))
    )
    strict_no_synth = bool(
        _cfg("strict_no_synth", bool(getattr(args, "strict_no_synth", False)))
    )

    result = run(
        groups=effective_groups,
        duration=duration,
        samples=samples,
        period_s=period_s,
        use_daq=use_daq,
        streaming=streaming,
        mdf_out=mdf_out,
        csv_out=csv_out,
        hdf5_out=hdf5_out,
        strict_mdf=strict_mdf,
        strict_no_trim=strict_no_trim,
        strict_no_synth=strict_no_synth,
    )

    if result.mdf_path:
        app.log.info(f"MDF:  {result.mdf_path}")
    if result.csv_path:
        app.log.info(f"CSV:  {result.csv_path}")
    if result.hdf5_path:
        app.log.info(f"HDF5: {result.hdf5_path}")


if __name__ == "__main__":
    main()
