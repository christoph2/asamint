#!/usr/bin/env python
from pathlib import Path
from typing import Any

import pytest

from asamint import measurement


class DummyCreator:
    def __init__(self, exp_cfg: dict[str, Any]) -> None:
        self.exp_cfg = exp_cfg
        self.session = object()
        self.measurement_variables: list[str] = []
        self.closed = False

    def add_measurements(self, names: list[str]) -> None:
        self.measurement_variables.extend(names)

    def close(self) -> None:
        self.closed = True


def test_run_validates_duration_vs_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(measurement, "get_application", lambda: None)
    with pytest.raises(ValueError):
        measurement.run([], duration=None, samples=None)
    with pytest.raises(ValueError):
        measurement.run([], duration=1.0, samples=1)


def test_run_uses_creator_and_daq_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = {}

    class DummyApp:
        class general:
            shortname = "TEST"
            output_format = "HDF5"

    def fake_build_daq_lists(session: Any, groups: list[dict[str, Any]]) -> list[str]:
        captured["groups"] = groups
        captured["session"] = session
        return ["daq_list"]

    def fake_execute_daq_capture(**kwargs: Any) -> str:
        captured["capture_kwargs"] = kwargs
        return str(tmp_path / "captured.h5")

    monkeypatch.setattr(measurement, "get_application", lambda: DummyApp())
    monkeypatch.setattr(measurement, "HDF5Creator", DummyCreator)
    monkeypatch.setattr(measurement, "MDFCreator", DummyCreator)
    monkeypatch.setattr(measurement, "build_daq_lists", fake_build_daq_lists)
    monkeypatch.setattr(measurement, "_execute_daq_capture", fake_execute_daq_capture)
    monkeypatch.setattr(measurement, "names_from_group", lambda *args, **kwargs: [])

    groups = [{"name": "G1", "event_num": 1, "variables": ["sig1"]}]
    result = measurement.run(
        groups,
        duration=0.5,
        samples=None,
        hdf5_out=str(tmp_path / "out.h5"),
    )

    assert result.hdf5_path == str(tmp_path / "captured.h5")
    assert captured["groups"][0]["name"] == "G1"
    assert captured["capture_kwargs"]["duration"] == 0.5
    assert captured["capture_kwargs"]["hdf5_out"] == str(tmp_path / "out.h5")
    assert captured["capture_kwargs"]["daq_lists"] == ["daq_list"]
