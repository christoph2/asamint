from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import h5py
import numpy as np
import pytest

from asamint.calibration.db import CalibrationDB
from asamint.model.calibration import klasses


@pytest.fixture
def calibration_db(tmp_path: Path) -> Iterator[CalibrationDB]:
    database = CalibrationDB(str(tmp_path / "calibration-db"), mode="w")
    try:
        yield database
    finally:
        database.close()


def _make_axis_pts(name: str = "AXIS_REF") -> klasses.AxisPts:
    return klasses.AxisPts(
        name=name,
        comment="",
        category="AXIS_PTS",
        _raw=np.array([10, 20, 30], dtype=np.uint16),
        _phys=np.array([1.0, 2.0, 3.0], dtype=np.float64),
        displayIdentifier="DI_AXIS_REF",
        unit="rpm",
        is_numeric=True,
    )


def _make_curve(
    axis_category: str,
    axis_pts_ref: str = "AXIS_REF",
    name: str = "CURVE_PARAM",
) -> klasses.Curve:
    axis = klasses.AxisContainer(
        name="speed",
        input_quantity="N",
        category=axis_category,
        unit="rpm",
        raw=[],
        phys=[],
        axis_pts_ref=axis_pts_ref,
        is_numeric=True,
    )
    return klasses.Curve(
        name=name,
        comment="",
        category="CURVE",
        _raw=np.array([100, 200, 300], dtype=np.uint16),
        _phys=np.array([10.0, 20.0, 30.0], dtype=np.float64),
        displayIdentifier="DI_CURVE_PARAM",
        fnc_unit="ms",
        axes=[axis],
        is_numeric=True,
    )


@pytest.mark.parametrize("axis_category", ["COM_AXIS", "RES_AXIS", "CURVE_AXIS"])
def test_load_reads_soft_linked_axis_categories(
    calibration_db: CalibrationDB, axis_category: str
) -> None:
    calibration_db.import_axis_pts(_make_axis_pts())
    calibration_db.import_map_curve(_make_curve(axis_category))

    array = calibration_db.load("CURVE_PARAM")

    assert array.dims == ("speed",)
    assert np.array_equal(array.coords["speed"].values, np.array([1.0, 2.0, 3.0]))
    assert np.array_equal(array.values, np.array([10.0, 20.0, 30.0]))


@pytest.mark.parametrize("axis_category", ["COM_AXIS", "RES_AXIS", "CURVE_AXIS"])
def test_import_map_curve_rejects_missing_axis_reference(
    calibration_db: CalibrationDB, axis_category: str
) -> None:
    with pytest.raises(ValueError, match="missing AXIS_PTS 'MISSING_AXIS'"):
        calibration_db.import_map_curve(
            _make_curve(axis_category, axis_pts_ref="MISSING_AXIS")
        )


def test_load_reports_broken_soft_link_reference(
    calibration_db: CalibrationDB,
) -> None:
    dataset = calibration_db.db.create_group("/BROKEN_CURVE", track_order=True)
    dataset.attrs["category"] = "CURVE"
    dataset.attrs["comment"] = ""
    dataset.attrs["display_identifier"] = ""
    dataset["phys"] = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    axes = dataset.create_group("axes")
    axis_group = axes.create_group("0")
    axis_group.attrs["category"] = "CURVE_AXIS"
    axis_group.attrs["unit"] = "rpm"
    axis_group.attrs["name"] = "speed"
    axis_group.attrs["input_quantity"] = "N"
    axis_group["reference"] = h5py.SoftLink("/MISSING_AXIS")

    with pytest.raises(KeyError, match="Broken CURVE_AXIS reference '/MISSING_AXIS'"):
        calibration_db.load("BROKEN_CURVE")
