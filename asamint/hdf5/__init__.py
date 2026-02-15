#!/usr/bin/env python

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Optional

from asamint.adapters.a2l import inspect
from asamint.asam import AsamMC


class HDF5Creator(AsamMC):
    """
    Create and save HDF5 files from ECU measurements,
    integrating with pya2l and pyxcp. Same interface as MDFCreator.
    """

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self.measurement_variables: list[Any] = []
        try:
            self._resolve_measurements_from_config()
        except Exception as e:
            self.logger.debug(
                f"HDF5Creator: could not resolve measurements from config: {e}"
            )

    def add_measurements(self, names: Iterable[str]) -> None:
        """Add measurement items by name using A2L inspect.Measurement."""
        for name in names:
            try:
                meas = inspect.Measurement.get(self.session, name)
                if meas is not None:
                    self.measurement_variables.append(meas)
            except Exception as e:
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
    ):
        """
        Persist measurement data into HDF5/CSV using finalize helpers.

        Args:
            data: Mapping of signal name to samples; may include ``TIMESTAMPS``.
            csv_out: Optional CSV output path.
            hdf5_out: Optional HDF5 output path; defaults to an auto-generated filename.
            project_meta: Optional metadata for embedding into outputs.
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
                signal_meta[meas.name] = {
                    "compu_method": getattr(meas.compuMethod, "name", None)
                }
            except Exception:
                units[meas.name] = None
                signal_meta[meas.name] = {"compu_method": None}

        target_h5 = hdf5_out or self.generate_filename(".h5")
        return measurement.finalize_measurement_outputs(
            data=data,
            units=units,
            project_meta=project_meta,
            csv_out=csv_out,
            hdf5_out=target_h5,
            signal_metadata=signal_meta,
        )
