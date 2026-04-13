#!/usr/bin/env python
from pathlib import Path

import numpy as np
import pytest

from asamint import api


@pytest.fixture
def dummy_groups():
    return [
        {
            "name": "G1",
            "variables": [
                ("sig_a", 0x1000, 0, "U8"),
                ("sig_b", 0x1004, 0, "U16"),
            ],
            "event_num": 1,
        }
    ]


def test_run_returns_paths(tmp_path: Path, monkeypatch, dummy_groups):
    target_csv = tmp_path / "out.csv"
    target_hdf5 = tmp_path / "out.h5"
    monkeypatch.setenv("ASAMINT_OUTPUT_FORMAT", "MDF")

    def fake_run(groups, **kwargs):
        return api.RunResult(
            mdf_path=str(target_csv),
            csv_path=str(target_csv),
            hdf5_path=str(target_hdf5),
            signals={"sig_a": {}, "sig_b": {}},
        )

    monkeypatch.setattr(api, "run", fake_run)

    result = api.run(dummy_groups, duration=0.1, csv_out=str(target_csv), hdf5_out=str(target_hdf5))

    assert result.mdf_path == str(target_csv)
    assert result.csv_path == str(target_csv)
    assert result.hdf5_path == str(target_hdf5)
    assert set(result.signals.keys()) == {"sig_a", "sig_b"}


def test_build_daq_lists_uses_adapter(monkeypatch):
    built = []

    class DummyDaqList:
        def __init__(self, *args, **kwargs):
            built.append((args, kwargs))

    monkeypatch.setattr("asamint.measurement.DaqList", DummyDaqList)
    monkeypatch.setattr(
        "asamint.measurement.resolve_measurements_by_names",
        lambda *args, **kwargs: [("sig_a", 0x1000, 0, "U8")],
    )

    lists = api.build_daq_lists(
        None,
        [
            {
                "name": "G1",
                "variables": [
                    ("sig_a", 0x1000, 0, "U8"),
                    ("sig_b", 0x1004, 0, "U16"),
                ],
                "event_num": 1,
                "prescaler": 2,
                "priority": 0,
            }
        ],
    )

    assert len(lists) == 1
    assert built
