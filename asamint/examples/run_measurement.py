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

DEFAULT_GROUPS = [
    {
        "name": "pwm_stuff",
        "event_num": 2,
        "enable_timestamps": True,
        "group_name": "PWM_Signals",
    },
    {
        "name": "Example_Double",
        "group_name": "Example_Double",
        "event_num": 1,
        "enable_timestamps": True,
    },
]


def parse_args():
    """Parse example-specific arguments and strip them from sys.argv.

    Returns the parsed namespace. Any recognized options are removed from
    ``sys.argv`` so that subsequent consumers (e.g., ``get_application()``)
    don't see them.
    """
    parser = MeasurementArgsParser()
    return parser.parse_and_strip()


def _load_json_config(app, args) -> dict | None:
    if not getattr(args, "config", None):
        return None
    try:
        cfg_path = Path(args.config)
        with cfg_path.open("r", encoding="utf-8") as fh:
            config = json.load(fh)
        app.log.info(f"Loaded configuration from {cfg_path}")
        return config
    except Exception as e:
        app.log.warning(
            f"Failed to load config {args.config}: {e}. Falling back to CLI/defaults."
        )
        return None


def _cfg(json_cfg: dict | None, key: str, default):
    if json_cfg is not None and key in json_cfg and json_cfg[key] is not None:
        return json_cfg[key]
    return default


def _resolve_samples_and_duration(
    app, json_cfg: dict | None, args
) -> tuple[int | None, float | None]:
    samples = None
    duration = _cfg(json_cfg, "duration", args.duration)
    if json_cfg is None or "samples" not in json_cfg or json_cfg["samples"] is None:
        return samples, duration
    try:
        return int(json_cfg["samples"]), None
    except Exception:
        app.log.warning("Invalid 'samples' in JSON config; ignoring.")
        return None, duration


def _resolve_period_s(app, json_cfg: dict | None) -> float | None:
    period = _cfg(json_cfg, "period_s", None)
    if period is None:
        return None
    try:
        return float(period)
    except Exception:
        app.log.warning("Invalid 'period_s' in JSON config; ignoring.")
        return None


def _build_run_kwargs(app, args, json_cfg: dict | None) -> dict:
    samples, duration = _resolve_samples_and_duration(app, json_cfg, args)
    return {
        "groups": _cfg(json_cfg, "groups", DEFAULT_GROUPS),
        "duration": duration,
        "samples": samples,
        "period_s": _resolve_period_s(app, json_cfg),
        "use_daq": _cfg(json_cfg, "use_daq", not args.no_daq),
        "streaming": _cfg(json_cfg, "streaming", args.streaming),
        "mdf_out": _cfg(
            json_cfg, "mdf_out", str(args.mdf_out) if args.mdf_out else None
        ),
        "csv_out": _cfg(
            json_cfg, "csv_out", str(args.csv_out) if args.csv_out else None
        ),
        "hdf5_out": _cfg(
            json_cfg, "hdf5_out", str(args.hdf5_out) if args.hdf5_out else None
        ),
        "strict_mdf": bool(
            _cfg(json_cfg, "strict_mdf", bool(getattr(args, "strict_mdf", False)))
        ),
        "strict_no_trim": bool(
            _cfg(
                json_cfg, "strict_no_trim", bool(getattr(args, "strict_no_trim", False))
            )
        ),
        "strict_no_synth": bool(
            _cfg(
                json_cfg,
                "strict_no_synth",
                bool(getattr(args, "strict_no_synth", False)),
            )
        ),
    }


def _log_result_paths(app, result) -> None:
    if result.mdf_path:
        app.log.info(f"MDF:  {result.mdf_path}")
    if result.csv_path:
        app.log.info(f"CSV:  {result.csv_path}")
    if result.hdf5_path:
        app.log.info(f"HDF5: {result.hdf5_path}")


def main() -> None:
    args = parse_args()
    app = get_application()
    if args.output_format:
        app.general.output_format = args.output_format.upper()
    app.log.info("Starting measurement example")
    json_cfg = _load_json_config(app, args)
    result = run(**_build_run_kwargs(app, args, json_cfg))
    _log_result_paths(app, result)


if __name__ == "__main__":
    main()
