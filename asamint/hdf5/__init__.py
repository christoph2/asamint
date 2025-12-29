#!/usr/bin/env python

from collections.abc import Iterable
from typing import Any

from pya2l.api import inspect

from asamint.asam import AsamMC
from asamint.hdf5.policy import Hdf5OnlinePolicy


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
        """Add measurement items by name using pya2l inspect.Measurement."""
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
