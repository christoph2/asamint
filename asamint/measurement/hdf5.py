#!/usr/bin/env python

import warnings
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from asamint.adapters.a2l import inspect
from asamint.asam import AsamMC
from asamint.core.logging import configure_logging

logger = configure_logging(__name__)

if TYPE_CHECKING:
    from asamint.measurement import RunResult


class HDF5Creator(AsamMC):
    """
    Create and save HDF5 files from ECU measurements,
    integrating with pya2l and pyxcp. Same interface as MDFCreator.
    """

    def on_init(self, config, *args, **kws) -> None:
        self.measurement_variables: list[Any] = []
        try:
            self._resolve_measurements_from_config()
        except (AttributeError, ValueError, KeyError) as e:
            self.logger.debug(f"HDF5Creator: could not resolve measurements from config: {e}")

    def add_measurements(self, names: Iterable[str]) -> None:
        """Add measurement items by name using A2L inspect.Measurement."""
        for name in names:
            try:
                meas = inspect.Measurement.get(self.session, name)
                if meas is not None:
                    self.measurement_variables.append(meas)
            except (AttributeError, ValueError, KeyError) as e:
                self.logger.warning(f"Unknown measurement '{name}': {e}")

    def _resolve_measurements_from_config(self) -> None:
        """Resolve measurements from experiment_config (MEASUREMENTS only)."""
        names = self.experiment_config.get("MEASUREMENTS") or []
        if names:
            self.add_measurements(names)

    def save_measurements(
        self,
        data: dict[str, Any],
        *,
        csv_out: str | Path | None = None,
        hdf5_out: str | Path | None = None,
        project_meta: Optional[dict[str, Any]] = None,
        hdf5_only: bool = False,
    ) -> "RunResult":
        """
        Persist measurement data into HDF5/CSV using finalize helpers.

        Args:
            data: Mapping of signal name to samples; may include ``TIMESTAMPS``.
            csv_out: Optional CSV output path.
            hdf5_out: Optional HDF5 output path; defaults to an auto-generated filename.
            project_meta: Optional metadata for embedding into outputs.
            hdf5_only: Skip CSV writing even if ``csv_out`` is provided.
        """

        if not data:
            from asamint.measurement import RunResult

            return RunResult(
                mdf_path=None,
                csv_path=None,
                hdf5_path=None,
                signals={},
                timebases=None,
            )

        from asamint import measurement

        project_meta = project_meta or {
            "author": self.config.general.author,
            "company": self.config.general.company,
            "department": self.config.general.department,
            "project": self.config.general.project,
            "shortname": self.experiment_config.get("SHORTNAME"),
            "subject": self.experiment_config.get("SUBJECT"),
            "time_source": self.experiment_config.get("TIME_SOURCE"),
        }

        units: dict[str, Any] = {}
        signal_meta: dict[str, dict[str, Any]] = {}
        for meas in getattr(self, "measurement_variables", []):
            try:
                units[meas.name] = getattr(meas.compuMethod, "unit", None)
                signal_meta[meas.name] = {"compu_method": getattr(meas.compuMethod, "name", None)}
            except AttributeError:
                units[meas.name] = None
                signal_meta[meas.name] = {"compu_method": None}

        target_h5 = hdf5_out or self.generate_filename(".h5")
        return measurement.finalize_measurement_outputs(
            data=data,
            units=units,
            project_meta=project_meta,
            csv_out=None if hdf5_only else csv_out,
            hdf5_out=target_h5,
            signal_metadata=signal_meta,
            hdf5_only=hdf5_only,
        )


def _write_hdf5(
    h5_path: Path,
    data: dict[str, Any],
    meta: dict[str, dict[str, Any]],
    project_meta: dict[str, Any],
) -> None:
    """
    Write converted values to HDF5 with per-signal datasets and metadata attributes.
    This uses h5py if available; otherwise a warning is emitted and the file is not written.
    """
    try:
        import h5py
        import numpy as np  # ensure numpy available
    except ImportError as e:  # pragma: no cover
        warnings.warn(
            f"HDF5 export requested but h5py is not available: {e}. Skipping HDF5 write.",
            RuntimeWarning,
            stacklevel=2,
        )
        return

    with h5py.File(str(h5_path), "w") as hf:
        for k, v in project_meta.items():
            try:
                hf.attrs[k] = v if v is not None else ""
            except (TypeError, ValueError) as exc:
                logger.debug("Skipping HDF5 root attr %s: %s", k, exc)
        ts = data.get("TIMESTAMPS")
        if ts is not None:
            dset_ts = hf.create_dataset("timestamps", data=ts)
            dset_ts.attrs["description"] = "Relative timestamps in seconds"
        for name, values in data.items():
            if name == "TIMESTAMPS":
                continue
            dset = hf.create_dataset(name, data=values)
            m = meta.get(name, {})
            if m.get("units"):
                dset.attrs["units"] = m["units"]
            if m.get("compu_method"):
                dset.attrs["compu_method"] = m["compu_method"]
            if m.get("sample_count") is not None:
                dset.attrs["sample_count"] = int(m["sample_count"])


def _annotate_hdf5_root(h5_path: Path, project_meta: dict[str, Any]) -> None:
    try:
        import h5py
    except ImportError:
        return
    if not h5_path.exists():
        return
    try:
        with h5py.File(str(h5_path), "a") as hf:
            for k, v in project_meta.items():
                try:
                    hf.attrs[k] = v if v is not None else ""
                except (TypeError, ValueError) as exc:
                    logger.debug("Skipping HDF5 root attr %s: %s", k, exc)
    except OSError as exc:  # pragma: no cover - best-effort
        logger.debug("Failed to annotate HDF5 file %s: %s", h5_path, exc)


def _annotate_daq_hdf5_metadata(
    h5_path: Path,
    daq_lists: list[Any],
    project_meta: dict[str, Any],
    timebase_hint_s: Optional[float] = None,
) -> None:
    try:
        import json

        import h5py
    except ImportError:
        return
    if not h5_path.exists():
        return
    try:
        with h5py.File(str(h5_path), "a") as hf:
            config = _serialize_daq_lists(daq_lists)
            _write_daq_hdf5_metadata(hf, h5_path, project_meta, json.dumps(config), timebase_hint_s)
    except OSError as exc:  # pragma: no cover - best-effort
        logger.debug("Failed to annotate DAQ HDF5 file %s: %s", h5_path, exc)


def _serialize_daq_lists(daq_lists: list[Any]) -> list[dict[str, Any]]:
    config: list[dict[str, Any]] = []
    for daq_list in daq_lists:
        try:
            config.append(
                {
                    "name": daq_list.name,
                    "event_num": daq_list.event_num,
                    "stim": bool(getattr(daq_list, "stim", False)),
                    "enable_timestamps": bool(getattr(daq_list, "enable_timestamps", False)),
                    "measurements": [measurement[0] for measurement in getattr(daq_list, "measurements", [])],
                }
            )
        except (AttributeError, TypeError, IndexError) as exc:
            logger.debug(
                "Failed to serialize DAQ list %s: %s",
                getattr(daq_list, "name", "?"),
                exc,
            )
    return config


def _write_daq_hdf5_metadata(
    hf: Any,
    h5_path: Path,
    project_meta: dict[str, Any],
    daq_config_json: str,
    timebase_hint_s: Optional[float],
) -> None:
    _annotate_hdf5_root(h5_path, project_meta)
    try:
        hf.attrs["daq_config"] = daq_config_json
    except (TypeError, ValueError) as exc:
        logger.debug("Failed to write daq_config attribute: %s", exc)
    if project_meta.get("time_source"):
        try:
            hf.attrs["time_source_hint"] = project_meta["time_source"]
        except (TypeError, ValueError) as exc:
            logger.debug("Failed to write time_source_hint attribute: %s", exc)
    if timebase_hint_s is not None:
        try:
            hf.attrs["daq_timebase_hint_s"] = float(timebase_hint_s)
        except (ValueError, TypeError):
            logger.debug("Failed to write daq_timebase_hint_s attribute", exc_info=True)
