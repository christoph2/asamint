from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from objutils import Image, Section

from asamint.adapters.objutils import InvalidAddressError
from asamint.calibration.api import (
    AxesContainer,
    Calibration,
    ExecutionPolicy,
    RangeError,
    ReadOnlyError,
    Status,
)
from asamint.core import byte_order as resolve_byte_order
from asamint.core.logging import configure_logging


class _MatrixDim:
    def __init__(self, x: int, is_valid: bool = True) -> None:
        self.x = x
        self._is_valid = is_valid

    def valid(self) -> bool:
        return self._is_valid


class _RecordingImage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.string_result = "MOTOR"
        self.numeric_result: int | float = 34
        self.ndarray_result = np.array([1, 2, 3], dtype=np.uint16)

    def read_asam_string(
        self, addr: int, dtype: str, length: int = -1, **kws: Any
    ) -> str:
        self.calls.append(("read_asam_string", (addr, dtype, length), kws))
        return self.string_result

    def write_asam_string(self, addr: int, value: str, dtype: str, **kws: Any) -> None:
        self.calls.append(("write_asam_string", (addr, value, dtype), kws))

    def read_asam_numeric(
        self, addr: int, dtype: str, byte_order: str = "MSB_LAST", **kws: Any
    ) -> int | float:
        self.calls.append(("read_asam_numeric", (addr, dtype, byte_order), kws))
        return self.numeric_result

    def write_asam_numeric(
        self,
        addr: int,
        value: int | float,
        dtype: str,
        byte_order: str = "MSB_LAST",
        **kws: Any,
    ) -> None:
        self.calls.append(("write_asam_numeric", (addr, value, dtype, byte_order), kws))

    def read_asam_ndarray(
        self,
        addr: int,
        length: int,
        dtype: str,
        shape: tuple[int, ...] | None = None,
        order: str | None = None,
        byte_order: str = "MSB_LAST",
        **kws: Any,
    ) -> np.ndarray:
        self.calls.append(
            (
                "read_asam_ndarray",
                (addr, length, dtype, shape, order, byte_order),
                kws,
            )
        )
        return self.ndarray_result

    def write_asam_ndarray(
        self,
        addr: int,
        array: np.ndarray,
        dtype: str,
        byte_order: str = "MSB_LAST",
        order: str | None = None,
        **kws: Any,
    ) -> None:
        self.calls.append(
            ("write_asam_ndarray", (addr, array.copy(), dtype, byte_order, order), kws)
        )

    def read_string(self, *args: Any, **kwargs: Any) -> str:
        raise AssertionError("generic read_string should not be used")

    def write_string(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("generic write_string should not be used")

    def read_numeric(self, *args: Any, **kwargs: Any) -> int | float:
        raise AssertionError("generic read_numeric should not be used")

    def write_numeric(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("generic write_numeric should not be used")


class _FailingInvalidAddressError(InvalidAddressError):
    pass


class _FailingImage(_RecordingImage):
    def __init__(self, fail_on: str) -> None:
        super().__init__()
        self.fail_on = fail_on

    def _maybe_raise(self, method_name: str) -> None:
        if self.fail_on == method_name:
            raise _FailingInvalidAddressError("invalid address")

    def write_asam_string(self, addr: int, value: str, dtype: str, **kws: Any) -> None:
        self._maybe_raise("write_asam_string")
        super().write_asam_string(addr, value, dtype, **kws)

    def write_asam_numeric(
        self,
        addr: int,
        value: int | float,
        dtype: str,
        byte_order: str = "MSB_LAST",
        **kws: Any,
    ) -> None:
        self._maybe_raise("write_asam_numeric")
        super().write_asam_numeric(addr, value, dtype, byte_order, **kws)

    def write_asam_ndarray(
        self,
        addr: int,
        array: np.ndarray,
        dtype: str,
        byte_order: str = "MSB_LAST",
        order: str | None = None,
        **kws: Any,
    ) -> None:
        self._maybe_raise("write_asam_ndarray")
        super().write_asam_ndarray(addr, array, dtype, byte_order, order, **kws)


def _make_calibration(image: _RecordingImage, characteristic: Any) -> Calibration:
    calibration = Calibration.__new__(Calibration)
    calibration.image = image
    calibration.logger = configure_logging(
        name="asamint.calibration.tests.asam_io",
        level=logging.DEBUG,
    )
    calibration.mod_common = None
    calibration.parameter_cache = {}
    calibration.get_characteristic = lambda name, category, writable: characteristic
    calibration.int_to_physical = lambda current_characteristic, raw: raw
    calibration.physical_to_int = lambda current_characteristic, value: value
    calibration.is_numeric = lambda compu_method: True
    return calibration


def _make_axis_pts(
    adjustable: bool = False,
    category: str = "COM_AXIS",
    read_only: bool = False,
) -> SimpleNamespace:
    elements: dict[str, Any] = {
        "axis_pts": SimpleNamespace(address=0x5000),
    }
    if adjustable:
        elements["no_axis_pts"] = SimpleNamespace(address=0x5004, data_type="UWORD")
    return SimpleNamespace(
        name="AXIS_PTS_CHAR",
        maxAxisPoints=4,
        readOnly=read_only,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        record_layout_components={
            "axes": {
                "x": SimpleNamespace(
                    category=category,
                    elements=elements,
                    data_type="SWORD",
                    reversed_storage=False,
                )
            }
        },
    )


def test_core_byte_order_maps_legacy_aliases() -> None:
    assert resolve_byte_order(SimpleNamespace(byteOrder="BIG_ENDIAN")) == "BIG_ENDIAN"
    assert (
        resolve_byte_order(SimpleNamespace(byteOrder="LITTLE_ENDIAN"))
        == "LITTLE_ENDIAN"
    )


def test_load_ascii_uses_asam_string_reader() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        matrixDim=_MatrixDim(8),
        number=8,
        address=0x2000,
        encoding="UTF8",
        name="ASCII_CHAR",
        longIdentifier="ASCII characteristic",
        displayIdentifier="DI_ASCII_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    value = Calibration.load_ascii(calibration, "ASCII_CHAR")

    assert value.phys == "MOTOR"
    assert image.calls == [
        ("read_asam_string", (0x2000, "UTF8", 8), {}),
    ]


def test_save_ascii_uses_asam_string_writer() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        matrixDim=_MatrixDim(8),
        number=8,
        address=0x2000,
        encoding="ASCII",
        readOnly=False,
        name="ASCII_CHAR",
        longIdentifier="ASCII characteristic",
        displayIdentifier="DI_ASCII_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_ascii(calibration, "ASCII_CHAR", "AB")

    assert status == Status.OK
    assert image.calls == [
        ("write_asam_string", (0x2000, "AB\x00     ", "ASCII"), {"length": 8}),
    ]


def test_load_ascii_falls_back_to_number_without_matrix_dim() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        matrixDim=None,
        number=12,
        address=0x2000,
        encoding="ASCII",
        name="ASCII_CHAR",
        longIdentifier="ASCII characteristic",
        displayIdentifier="DI_ASCII_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    Calibration.load_ascii(calibration, "ASCII_CHAR")

    assert image.calls == [
        ("read_asam_string", (0x2000, "ASCII", 12), {}),
    ]


def test_save_ascii_falls_back_to_number_for_invalid_matrix_dim() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        matrixDim=_MatrixDim(8, is_valid=False),
        number=12,
        address=0x2000,
        encoding="ASCII",
        readOnly=False,
        name="ASCII_CHAR",
        longIdentifier="ASCII characteristic",
        displayIdentifier="DI_ASCII_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_ascii(calibration, "ASCII_CHAR", "AB")

    assert status == Status.OK
    assert image.calls == [
        ("write_asam_string", (0x2000, "AB\x00         ", "ASCII"), {"length": 12}),
    ]


def test_save_ascii_returns_address_error_on_invalid_address() -> None:
    image = _FailingImage("write_asam_string")
    characteristic = SimpleNamespace(
        matrixDim=_MatrixDim(8),
        number=8,
        address=0x2000,
        encoding="ASCII",
        readOnly=False,
        name="ASCII_CHAR",
        longIdentifier="ASCII characteristic",
        displayIdentifier="DI_ASCII_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_ascii(calibration, "ASCII_CHAR", "AB")

    assert status == Status.ADDRESS_ERROR


def test_load_value_uses_asam_numeric_reader() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        physUnit="",
        _conversionRef="NO_COMPU_METHOD",
        compuMethod=SimpleNamespace(conversionType="LINEAR", unit=""),
        dependent_characteristic=False,
        virtual_characteristic=None,
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    value = Calibration.load_value(calibration, "VALUE_CHAR")

    assert value.raw == 34
    assert value.phys == 34
    assert image.calls == [
        ("read_asam_numeric", (0x2000, "UWORD", "BIG_ENDIAN"), {}),
    ]


def test_save_value_uses_asam_numeric_writer() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=False,
        lowerLimit=0,
        upperLimit=65535,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value(calibration, "VALUE_CHAR", 34)

    assert status == Status.OK
    assert image.calls == [
        ("write_asam_numeric", (0x2000, 34, "UWORD", "BIG_ENDIAN"), {}),
    ]


def test_save_value_returns_address_error_on_invalid_address() -> None:
    image = _FailingImage("write_asam_numeric")
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=False,
        lowerLimit=0,
        upperLimit=65535,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value(calibration, "VALUE_CHAR", 34)

    assert status == Status.ADDRESS_ERROR


def test_save_value_read_only_returns_error_status() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=True,
        lowerLimit=0,
        upperLimit=65535,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value(
        calibration,
        "VALUE_CHAR",
        34,
        readOnlyPolicy=ExecutionPolicy.RETURN_ERROR,
    )

    assert status == Status.READ_ONLY_ERROR
    assert image.calls == []


def test_save_value_read_only_ignore_still_writes() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=True,
        lowerLimit=0,
        upperLimit=65535,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value(
        calibration,
        "VALUE_CHAR",
        34,
        readOnlyPolicy=ExecutionPolicy.IGNORE,
    )

    assert status == Status.OK
    assert image.calls == [
        ("write_asam_numeric", (0x2000, 34, "UWORD", "BIG_ENDIAN"), {}),
    ]


def test_save_value_read_only_except_raises() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=True,
        lowerLimit=0,
        upperLimit=65535,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    with pytest.raises(ReadOnlyError):
        Calibration.save_value(calibration, "VALUE_CHAR", 34)


def test_save_value_out_of_range_returns_error_status() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=False,
        lowerLimit=0,
        upperLimit=10,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value(
        calibration,
        "VALUE_CHAR",
        34,
        limitsPolicy=ExecutionPolicy.RETURN_ERROR,
    )

    assert status == Status.RANGE_ERROR
    assert image.calls == []


def test_save_value_out_of_range_ignore_still_writes() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=False,
        lowerLimit=0,
        upperLimit=10,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value(
        calibration,
        "VALUE_CHAR",
        34,
        limitsPolicy=ExecutionPolicy.IGNORE,
    )

    assert status == Status.OK
    assert image.calls == [
        ("write_asam_numeric", (0x2000, 34, "UWORD", "BIG_ENDIAN"), {}),
    ]


def test_save_value_out_of_range_except_raises() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x2000,
        bitMask=None,
        compuMethod=SimpleNamespace(conversionType="LINEAR"),
        fnc_asam_dtype="UWORD",
        byteOrder="BIG_ENDIAN",
        readOnly=False,
        lowerLimit=0,
        upperLimit=10,
        name="VALUE_CHAR",
        longIdentifier="Numeric characteristic",
        displayIdentifier="DI_VALUE_CHAR",
    )
    calibration = _make_calibration(image, characteristic)

    with pytest.raises(RangeError):
        Calibration.save_value(calibration, "VALUE_CHAR", 34)


def test_save_value_block_uses_asam_ndarray_writer() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x3000,
        fnc_asam_dtype="UWORD",
        fnc_np_shape=(3,),
        fnc_np_order="C",
        readOnly=False,
        name="VALUE_BLOCK",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value_block(
        calibration,
        "VALUE_BLOCK",
        np.array([1, 2, 3], dtype=np.uint16),
    )

    assert status == Status.OK
    call_name, call_args, call_kwargs = image.calls[0]
    assert call_name == "write_asam_ndarray"
    assert call_args[0] == 0x3000
    assert np.array_equal(call_args[1], np.array([1, 2, 3], dtype=np.uint16))
    assert call_args[2:] == ("UWORD", "MSB_LAST", "C")
    assert call_kwargs == {}


def test_save_value_block_returns_address_error_on_invalid_address() -> None:
    image = _FailingImage("write_asam_ndarray")
    characteristic = SimpleNamespace(
        address=0x3000,
        fnc_asam_dtype="UWORD",
        fnc_np_shape=(3,),
        fnc_np_order="C",
        readOnly=False,
        name="VALUE_BLOCK",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value_block(
        calibration,
        "VALUE_BLOCK",
        np.array([1, 2, 3], dtype=np.uint16),
    )

    assert status == Status.ADDRESS_ERROR


def test_save_value_block_read_only_returns_error_status() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x3000,
        fnc_asam_dtype="UWORD",
        fnc_np_shape=(3,),
        fnc_np_order="C",
        readOnly=True,
        name="VALUE_BLOCK",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value_block(
        calibration,
        "VALUE_BLOCK",
        np.array([1, 2, 3], dtype=np.uint16),
        readOnlyPolicy=ExecutionPolicy.RETURN_ERROR,
    )

    assert status == Status.READ_ONLY_ERROR
    assert image.calls == []


def test_save_value_block_read_only_ignore_still_writes() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x3000,
        fnc_asam_dtype="UWORD",
        fnc_np_shape=(3,),
        fnc_np_order="C",
        readOnly=True,
        name="VALUE_BLOCK",
    )
    calibration = _make_calibration(image, characteristic)

    status = Calibration.save_value_block(
        calibration,
        "VALUE_BLOCK",
        np.array([1, 2, 3], dtype=np.uint16),
        readOnlyPolicy=ExecutionPolicy.IGNORE,
    )

    assert status == Status.OK
    assert image.calls


def test_save_value_block_read_only_except_raises() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        address=0x3000,
        fnc_asam_dtype="UWORD",
        fnc_np_shape=(3,),
        fnc_np_order="C",
        readOnly=True,
        name="VALUE_BLOCK",
    )
    calibration = _make_calibration(image, characteristic)

    with pytest.raises(ReadOnlyError):
        Calibration.save_value_block(
            calibration,
            "VALUE_BLOCK",
            np.array([1, 2, 3], dtype=np.uint16),
        )


def test_save_curve_or_map_uses_asam_ndarray_writer() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        type="CURVE",
        readOnly=False,
        name="CURVE_CHAR",
        fnc_np_order="F",
        byteOrder="BIG_ENDIAN",
        record_layout_components={
            "elements": {
                "fnc_values": SimpleNamespace(address=0x4000, data_type="UWORD")
            }
        },
    )
    values = SimpleNamespace(
        phys=np.array([10, 20], dtype=np.uint16),
        raw=np.array([10, 20], dtype=np.uint16),
    )
    calibration = _make_calibration(image, characteristic)
    calibration.get_axes = lambda current_characteristic, num_axes: AxesContainer(
        axes=[],
        shape=(2,),
        flip_axes=[],
    )

    status = Calibration.save_curve_or_map(calibration, "CURVE_CHAR", values)

    assert status == Status.OK
    call_name, call_args, call_kwargs = image.calls[0]
    assert call_name == "write_asam_ndarray"
    assert call_args[0] == 0x4000
    assert np.array_equal(call_args[1], np.array([10, 20], dtype=np.uint16))
    assert call_args[2:] == ("UWORD", "BIG_ENDIAN", "F")
    assert call_kwargs == {}


def test_save_curve_or_map_returns_address_error_on_invalid_address() -> None:
    image = _FailingImage("write_asam_ndarray")
    characteristic = SimpleNamespace(
        type="CURVE",
        readOnly=False,
        name="CURVE_CHAR",
        fnc_np_order="F",
        byteOrder="BIG_ENDIAN",
        record_layout_components={
            "elements": {
                "fnc_values": SimpleNamespace(address=0x4000, data_type="UWORD")
            }
        },
    )
    values = SimpleNamespace(
        phys=np.array([10, 20], dtype=np.uint16),
        raw=np.array([10, 20], dtype=np.uint16),
    )
    calibration = _make_calibration(image, characteristic)
    calibration.get_axes = lambda current_characteristic, num_axes: AxesContainer(
        axes=[],
        shape=(2,),
        flip_axes=[],
    )

    status = Calibration.save_curve_or_map(calibration, "CURVE_CHAR", values)

    assert status == Status.ADDRESS_ERROR


def test_save_curve_or_map_read_only_returns_error_status() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        type="CURVE",
        readOnly=True,
        name="CURVE_CHAR",
        fnc_np_order="F",
        byteOrder="BIG_ENDIAN",
        record_layout_components={
            "elements": {
                "fnc_values": SimpleNamespace(address=0x4000, data_type="UWORD")
            }
        },
    )
    values = SimpleNamespace(
        phys=np.array([10, 20], dtype=np.uint16),
        raw=np.array([10, 20], dtype=np.uint16),
    )
    calibration = _make_calibration(image, characteristic)
    calibration.get_axes = lambda current_characteristic, num_axes: AxesContainer(
        axes=[],
        shape=(2,),
        flip_axes=[],
    )

    status = Calibration.save_curve_or_map(
        calibration,
        "CURVE_CHAR",
        values,
        readOnlyPolicy=ExecutionPolicy.RETURN_ERROR,
    )

    assert status == Status.READ_ONLY_ERROR
    assert image.calls == []


def test_save_curve_or_map_read_only_ignore_still_writes() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        type="CURVE",
        readOnly=True,
        name="CURVE_CHAR",
        fnc_np_order="F",
        byteOrder="BIG_ENDIAN",
        record_layout_components={
            "elements": {
                "fnc_values": SimpleNamespace(address=0x4000, data_type="UWORD")
            }
        },
    )
    values = SimpleNamespace(
        phys=np.array([10, 20], dtype=np.uint16),
        raw=np.array([10, 20], dtype=np.uint16),
    )
    calibration = _make_calibration(image, characteristic)
    calibration.get_axes = lambda current_characteristic, num_axes: AxesContainer(
        axes=[],
        shape=(2,),
        flip_axes=[],
    )

    status = Calibration.save_curve_or_map(
        calibration,
        "CURVE_CHAR",
        values,
        readOnlyPolicy=ExecutionPolicy.IGNORE,
    )

    assert status == Status.OK
    assert image.calls


def test_save_curve_or_map_read_only_except_raises() -> None:
    image = _RecordingImage()
    characteristic = SimpleNamespace(
        type="CURVE",
        readOnly=True,
        name="CURVE_CHAR",
        fnc_np_order="F",
        byteOrder="BIG_ENDIAN",
        record_layout_components={
            "elements": {
                "fnc_values": SimpleNamespace(address=0x4000, data_type="UWORD")
            }
        },
    )
    values = SimpleNamespace(
        phys=np.array([10, 20], dtype=np.uint16),
        raw=np.array([10, 20], dtype=np.uint16),
    )
    calibration = _make_calibration(image, characteristic)
    calibration.get_axes = lambda current_characteristic, num_axes: AxesContainer(
        axes=[],
        shape=(2,),
        flip_axes=[],
    )

    with pytest.raises(ReadOnlyError):
        Calibration.save_curve_or_map(calibration, "CURVE_CHAR", values)


def test_save_axis_pts_returns_address_error_for_size_write() -> None:
    image = _FailingImage("write_asam_numeric")
    calibration = _make_calibration(image, SimpleNamespace())
    axis_pts = _make_axis_pts(adjustable=True)
    calibration.get_axis_pts = lambda name: axis_pts

    status = Calibration.save_axis_pts(
        calibration,
        "AXIS_PTS_CHAR",
        np.array([1, 2], dtype=np.int16),
    )

    assert status == Status.ADDRESS_ERROR


def test_save_axis_pts_read_only_returns_error_status() -> None:
    image = _RecordingImage()
    calibration = _make_calibration(image, SimpleNamespace())
    axis_pts = _make_axis_pts(adjustable=False, read_only=True)
    calibration.get_axis_pts = lambda name: axis_pts

    status = Calibration.save_axis_pts(
        calibration,
        "AXIS_PTS_CHAR",
        np.array([1, 2, 3, 4], dtype=np.int16),
        readOnlyPolicy=ExecutionPolicy.RETURN_ERROR,
    )

    assert status == Status.READ_ONLY_ERROR
    assert image.calls == []


def test_save_axis_pts_read_only_ignore_still_writes() -> None:
    image = _RecordingImage()
    calibration = _make_calibration(image, SimpleNamespace())
    axis_pts = _make_axis_pts(adjustable=False, read_only=True)
    calibration.get_axis_pts = lambda name: axis_pts

    status = Calibration.save_axis_pts(
        calibration,
        "AXIS_PTS_CHAR",
        np.array([1, 2, 3, 4], dtype=np.int16),
        readOnlyPolicy=ExecutionPolicy.IGNORE,
    )

    assert status == Status.OK
    assert image.calls


def test_save_axis_pts_read_only_except_raises() -> None:
    image = _RecordingImage()
    calibration = _make_calibration(image, SimpleNamespace())
    axis_pts = _make_axis_pts(adjustable=False, read_only=True)
    calibration.get_axis_pts = lambda name: axis_pts

    with pytest.raises(ReadOnlyError):
        Calibration.save_axis_pts(
            calibration,
            "AXIS_PTS_CHAR",
            np.array([1, 2, 3, 4], dtype=np.int16),
        )


def test_save_axis_pts_returns_address_error_for_array_write() -> None:
    image = _FailingImage("write_asam_ndarray")
    calibration = _make_calibration(image, SimpleNamespace())
    axis_pts = _make_axis_pts(adjustable=False)
    calibration.get_axis_pts = lambda name: axis_pts

    status = Calibration.save_axis_pts(
        calibration,
        "AXIS_PTS_CHAR",
        np.array([1, 2, 3, 4], dtype=np.int16),
    )

    assert status == Status.ADDRESS_ERROR


def test_write_nd_array_uses_asam_ndarray_writer() -> None:
    image = _RecordingImage()
    calibration = _make_calibration(image, SimpleNamespace())
    axis_pts = SimpleNamespace(
        byteOrder="MSB_FIRST",
        record_layout_components={
            "axes": {
                "x": SimpleNamespace(
                    data_type="SWORD",
                    elements={"axis_pts": SimpleNamespace(address=0x5000)},
                )
            }
        },
    )

    Calibration.write_nd_array(
        calibration,
        axis_pts,
        "x",
        "axis_pts",
        np.array([1, 2], dtype=np.int16),
        order="C",
    )

    call_name, call_args, call_kwargs = image.calls[0]
    assert call_name == "write_asam_ndarray"
    assert call_args[0] == 0x5000
    assert np.array_equal(call_args[1], np.array([1, 2], dtype=np.int16))
    assert call_args[2:] == ("SWORD", "MSB_FIRST", "C")
    assert call_kwargs == {}


def test_objutils_image_supports_direct_asam_helpers() -> None:
    image = Image([Section(0x810000, bytes(32))])

    image.write_asam_numeric(0x810000, 0x1122, "UWORD", "MSB_FIRST")
    image.write_asam_numeric(0x810002, 0x7F, "UBYTE", "MSB_FIRST")
    image.write_asam_string(0x810010, "MOTOR", "ASCII", length=8)

    assert image.read_asam_numeric(0x810000, "UWORD", "MSB_FIRST") == 0x1122
    assert image.read_asam_numeric(0x810002, "UBYTE", "MSB_FIRST") == 0x7F
    assert image.read_asam_string(0x810010, "ASCII", length=8).startswith("MOTOR")
