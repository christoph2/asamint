#!/usr/bin/env python
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import numpy.testing as npt
import pytest

import asamint.measurement as measurement
from asamint.measurement import (
    _compute_timebase_metadata,
    _median_timebase,
    _merge_daq_csv_results,
    _parse_daq_csv,
    _prepare_daq_groups,
    _stride_for_ratio,
    _unique_names_from_groups,
    _write_hdf5,
)


def test_prepare_daq_groups_defaults_applied():
    groups = [{"name": "G1"}, {"name": "G2", "priority": 5}]
    result = _prepare_daq_groups(groups)
    assert result[0]["priority"] == 0
    assert result[0]["prescaler"] == 1
    assert result[1]["priority"] == 5
    assert result[1]["prescaler"] == 1


def test_unique_names_from_groups_de_duplicates():
    groups = [
        {"variables": ["a", "b", "a"]},
        {"variables": ["b", "c"]},
    ]
    assert _unique_names_from_groups(groups) == ["a", "b", "c"]


def test_stride_for_ratio_handles_near_match():
    assert _stride_for_ratio(100, 10) == 10
    assert _stride_for_ratio(101, 10) == 10
    assert _stride_for_ratio(0, 10) is None


def test_median_timebase_handles_timestamp_ns():
    ts = np.array([0, 1_000_000_000, 2_000_000_000], dtype=np.int64)
    assert _median_timebase("timestamp[ns]", ts) == 1_000_000_000.0
    assert _median_timebase("timestamp", ts) == 1_000_000_000.0


def test_merge_daq_csv_results_prefers_first_timestamps(tmp_path: Path):
    file1 = tmp_path / "a.csv"
    file1.write_text("timestamp,sig_a\n0,1\n1,2\n", encoding="utf-8")
    file2 = tmp_path / "b.csv"
    file2.write_text("timestamp,sig_b\n0,3\n1,4\n", encoding="utf-8")

    merged = _merge_daq_csv_results([file1, file2])

    npt.assert_array_equal(merged["TIMESTAMPS"], np.array([0.0, 1.0]))
    npt.assert_array_equal(merged["sig_a"], np.array([1.0, 2.0]))
    npt.assert_array_equal(merged["sig_b"], np.array([3.0, 4.0]))


def test_merge_daq_csv_results_synthesizes_timestamps(tmp_path: Path):
    file1 = tmp_path / "a.csv"
    file1.write_text("sig_a\n1\n2\n3\n", encoding="utf-8")

    merged = _merge_daq_csv_results([file1])

    npt.assert_array_equal(merged["TIMESTAMPS"], np.array([0.0, 1.0, 2.0]))
    npt.assert_array_equal(merged["sig_a"], np.array([1.0, 2.0, 3.0]))


def test_parse_daq_csv_handles_timestamps(tmp_path: Path):
    csv_file = tmp_path / "daq.csv"
    csv_file.write_text("timestamp,sig_a\n0,1\n1,2\n", encoding="utf-8")

    parsed = _parse_daq_csv(csv_file)

    npt.assert_array_equal(parsed["TIMESTAMPS"], np.array([0.0, 1.0]))
    npt.assert_array_equal(parsed["sig_a"], np.array([1.0, 2.0]))


def test_parse_daq_csv_handles_missing_timestamp(tmp_path: Path):
    csv_file = tmp_path / "daq_no_ts.csv"
    csv_file.write_text("sig_a\n1\n2\n", encoding="utf-8")

    parsed = _parse_daq_csv(csv_file)

    assert "TIMESTAMPS" not in parsed
    npt.assert_array_equal(parsed["sig_a"], np.array([1.0, 2.0]))


class _Field:
    def __init__(self, attr: str) -> None:
        self.attr = attr

    def __eq__(self, other: object) -> tuple[str, str, object]:
        return ("eq", self.attr, other)


class _FakeMeasurement:
    name = _Field("name")

    def __init__(
        self,
        name: str,
        address: int,
        extension: int | None,
        datatype: str,
    ) -> None:
        self.name = name
        self.ecu_address = SimpleNamespace(address=address)
        self.ecu_address_extension = (
            SimpleNamespace(extension=extension) if extension is not None else None
        )
        self.datatype = datatype


class _FakeGroup:
    groupName = _Field("groupName")

    def __init__(self, name: str, identifiers: list[str]) -> None:
        self.groupName = name
        self.ref_measurement = SimpleNamespace(identifier=list(identifiers))


class _FakeQuery:
    def __init__(self, store: dict[str, object]) -> None:
        self.store = store
        self.key: str | None = None

    def filter(self, condition: object) -> "_FakeQuery":
        if isinstance(condition, tuple) and len(condition) >= 3:
            self.key = condition[2]
        elif isinstance(condition, str):
            self.key = condition
        return self

    def first(self) -> object | None:
        if self.key is None:
            return None
        return self.store.get(self.key)


class _FakeSession:
    def __init__(self, groups: list[_FakeGroup], meas: list[_FakeMeasurement]) -> None:
        self.groups = {g.groupName: g for g in groups}
        self.measurements = {m.name: m for m in meas}

    def query(self, model_cls: type) -> _FakeQuery:
        if model_cls is _FakeGroup:
            return _FakeQuery(self.groups)
        if model_cls is _FakeMeasurement:
            return _FakeQuery(self.measurements)
        msg = f"Unexpected model {model_cls!r}"
        raise AssertionError(msg)


def _install_fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = SimpleNamespace(Group=_FakeGroup, Measurement=_FakeMeasurement)
    monkeypatch.setattr(measurement, "model", fake_model)


def test_group_measurements_resolves_and_excludes(monkeypatch: pytest.MonkeyPatch):
    _install_fake_model(monkeypatch)
    session = _FakeSession(
        groups=[_FakeGroup("G1", ["a", "b"])],
        meas=[
            _FakeMeasurement("a", 0x10, 1, "UBYTE"),
            _FakeMeasurement("b", 0x20, None, "FLOAT32_IEEE"),
        ],
    )

    result = measurement.group_measurements(session, "G1", exclude={"b"})

    assert result == [("a", 0x10, 1, "U8")]


def test_resolve_measurements_by_names_handles_unknown_type(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_model(monkeypatch)
    session = _FakeSession(
        groups=[],
        meas=[
            _FakeMeasurement("a", 0x1, 0, "UNKNOWN"),
            _FakeMeasurement("b", 0x2, 0, "SBYTE"),
        ],
    )

    result = measurement.resolve_measurements_by_names(
        session, ["a", "missing", "b"], exclude={"missing"}
    )

    assert ("a", 0x1, 0, "U32") in result
    assert ("b", 0x2, 0, "I8") in result


def test_build_daq_lists_supports_variables_and_groups(monkeypatch: pytest.MonkeyPatch):
    _install_fake_model(monkeypatch)
    created: list[dict[str, object]] = []

    class _FakeDaqList:
        def __init__(self, **kwargs: object) -> None:
            created.append(kwargs)

    monkeypatch.setattr(measurement, "DaqList", _FakeDaqList)

    session = _FakeSession(
        groups=[_FakeGroup("grp", ["b"])],
        meas=[
            _FakeMeasurement("a", 0x1, 0, "UBYTE"),
            _FakeMeasurement("b", 0x2, 0, "SBYTE"),
        ],
    )

    groups = [
        {
            "name": "explicit",
            "event_num": 1,
            "variables": ["a"],
            "enable_timestamps": True,
        },
        {
            "name": "from_group",
            "event_num": 2,
            "group_name": "grp",
            "enable_timestamps": False,
        },
    ]

    lists = measurement.build_daq_lists(session, groups)

    assert len(lists) == 2
    assert created[0]["measurements"][0] == ("a", 0x1, 0, "U8")
    assert created[1]["measurements"][0] == ("b", 0x2, 0, "I8")
    assert created[1]["enable_timestamps"] is False


def test_compute_timebase_metadata_groups_shared_source():
    data = {
        "TIMESTAMPS": np.array([0.0, 0.5, 1.0]),
        "sig_a": np.array([1.0, 2.0, 3.0]),
        "sig_b": np.array([4.0, 5.0, 6.0]),
    }

    meta = _compute_timebase_metadata(data, ["sig_a", "sig_b"])

    assert meta["sig_a"]["timestamp_source"] == "TIMESTAMPS"
    assert meta["sig_a"]["timebase_s"] == pytest.approx(0.5)
    assert meta["sig_a"]["group_id"] == 0
    assert meta["sig_b"]["group_id"] == 0
    assert meta["sig_b"]["sample_count"] == 3


def test_compute_timebase_metadata_prefers_event_and_strides():
    data = {
        "timestamp_event0": np.array(
            [
                0,
                1_000_000_000,
                2_000_000_000,
                3_000_000_000,
                4_000_000_000,
                5_000_000_000,
            ],
            dtype=np.int64,
        ),
        "sig_event": np.array([10.0, 11.0, 12.0]),
    }

    meta = _compute_timebase_metadata(data, ["sig_event"])

    assert meta["sig_event"]["timestamp_source"].startswith("timestamp_event0")
    assert meta["sig_event"]["timebase_s"] == pytest.approx(2.0)
    assert meta["sig_event"]["sample_count"] == 3


def test_write_hdf5_persists_data_and_metadata(tmp_path: Path):
    target = tmp_path / "out.h5"
    data = {"TIMESTAMPS": np.array([0.0, 1.0]), "sig": np.array([1.0, 2.0])}
    meta = {"sig": {"units": "V", "compu_method": "LINEAR", "sample_count": 2}}
    project_meta = {"project": "demo"}

    _write_hdf5(target, data, meta, project_meta)

    with h5py.File(target, "r") as hf:
        assert hf.attrs["project"] == "demo"
        npt.assert_array_equal(hf["timestamps"][...], np.array([0.0, 1.0]))
        npt.assert_array_equal(hf["sig"][...], np.array([1.0, 2.0]))
        assert hf["sig"].attrs["units"] == "V"
        assert hf["sig"].attrs["compu_method"] == "LINEAR"
        assert hf["sig"].attrs["sample_count"] == 2
