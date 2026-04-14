#!/usr/bin/env python
"""Tests for asamint.utils – pure utility functions and Bunch class."""

from __future__ import annotations

import math
import re
import time

import numpy as np
import pytest

from asamint.utils import (
    Bunch,
    adjust_to_word_boundary,
    almost_equal,
    chunks,
    convert_name,
    ffs,
    ffs_np,
    flatten,
    generate_filename,
    int_log2,
    make_2darray,
    partition,
    replace_non_c_char,
    sha1_digest,
    slicer,
)

# ---------------------------------------------------------------------------
# sha1_digest
# ---------------------------------------------------------------------------


def test_sha1_digest_returns_hex_string() -> None:
    result = sha1_digest("hello")
    assert re.fullmatch(r"[0-9a-f]{40}", result)


def test_sha1_digest_deterministic() -> None:
    assert sha1_digest("abc") == sha1_digest("abc")


def test_sha1_digest_different_inputs_differ() -> None:
    assert sha1_digest("foo") != sha1_digest("bar")


def test_sha1_digest_empty_string() -> None:
    result = sha1_digest("")
    assert len(result) == 40


# ---------------------------------------------------------------------------
# replace_non_c_char
# ---------------------------------------------------------------------------


def test_replace_non_c_char_spaces() -> None:
    assert replace_non_c_char("hello world") == "hello_world"


def test_replace_non_c_char_special_chars() -> None:
    assert replace_non_c_char("a+b=c!") == "a_b_c_"


def test_replace_non_c_char_already_valid() -> None:
    assert replace_non_c_char("validName_123") == "validName_123"


def test_replace_non_c_char_dot_preserved() -> None:
    assert replace_non_c_char("a.b") == "a.b"


def test_replace_non_c_char_empty() -> None:
    assert replace_non_c_char("") == ""


# ---------------------------------------------------------------------------
# convert_name
# ---------------------------------------------------------------------------


def test_convert_name_dots_to_underscore() -> None:
    assert convert_name("ASAM.M.SCALAR.UBYTE") == "ASAM_M_SCALAR_UBYTE"


def test_convert_name_no_dots_unchanged() -> None:
    assert convert_name("MyParam") == "MyParam"


def test_convert_name_multiple_dots() -> None:
    result = convert_name("a.b.c.d")
    assert result == "a_b_c_d"


# ---------------------------------------------------------------------------
# Bunch
# ---------------------------------------------------------------------------


def test_bunch_attribute_access() -> None:
    b = Bunch(x=1, y=2)
    assert b.x == 1
    assert b.y == 2


def test_bunch_dict_access() -> None:
    b = Bunch(name="test")
    assert b["name"] == "test"


def test_bunch_set_attribute() -> None:
    b = Bunch()
    b.z = 42
    assert b["z"] == 42


def test_bunch_is_dict_subclass() -> None:
    assert isinstance(Bunch(), dict)


# ---------------------------------------------------------------------------
# make_2darray
# ---------------------------------------------------------------------------


def test_make_2darray_1d_unchanged() -> None:
    arr = np.array([1, 2, 3, 4])
    result = make_2darray(arr)
    assert result.shape == (4,)


def test_make_2darray_2d_unchanged() -> None:
    arr = np.ones((3, 4))
    result = make_2darray(arr)
    assert result.shape == (3, 4)


def test_make_2darray_3d_collapsed() -> None:
    arr = np.ones((2, 3, 4))
    result = make_2darray(arr)
    assert result.ndim == 2
    assert result.shape == (6, 4)


def test_make_2darray_4d_collapsed() -> None:
    arr = np.ones((2, 3, 4, 5))
    result = make_2darray(arr)
    assert result.ndim == 2


def test_make_2darray_preserves_total_elements() -> None:
    arr = np.arange(24).reshape((2, 3, 4))
    result = make_2darray(arr)
    assert result.size == 24


# ---------------------------------------------------------------------------
# almost_equal
# ---------------------------------------------------------------------------


def test_almost_equal_identical() -> None:
    assert almost_equal(1.0, 1.0)


def test_almost_equal_within_tolerance() -> None:
    assert almost_equal(1.0, 1.0 + 1e-8)


def test_almost_equal_outside_tolerance() -> None:
    assert not almost_equal(1.0, 1.1)


def test_almost_equal_custom_places() -> None:
    assert almost_equal(1.0, 1.001, places=2)
    assert not almost_equal(1.0, 2.0, places=0)


def test_almost_equal_negative_values() -> None:
    assert almost_equal(-3.14, -3.14)


# ---------------------------------------------------------------------------
# generate_filename
# ---------------------------------------------------------------------------


def test_generate_filename_basic_structure() -> None:
    name = generate_filename({"PROJECT": "PJ"}, {"SUBJECT": "EXP"}, "dcm")
    assert name.startswith("PJ_EXP_")
    assert name.endswith(".dcm")


def test_generate_filename_with_extra() -> None:
    name = generate_filename({"PROJECT": "P"}, {"SUBJECT": "S"}, "h5", extra="v1")
    assert name.endswith("_v1.h5")


def test_generate_filename_timestamp_present() -> None:
    name = generate_filename({"PROJECT": "P"}, {"SUBJECT": "S"}, "dcm")
    # timestamp pattern: _DDMMYYYY_HHMMSS
    assert re.search(r"_\d{8}_\d{6}", name)


# ---------------------------------------------------------------------------
# ffs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (1, 0),  # bit 0
        (2, 1),  # bit 1
        (4, 2),  # bit 2
        (8, 3),  # bit 3
        (16, 4),
        (6, 1),  # lowest set bit of 0b110 is bit 1
        (12, 2),  # lowest set bit of 0b1100 is bit 2
    ],
)
def test_ffs(value: int, expected: int) -> None:
    assert ffs(value) == expected


def test_ffs_power_of_two() -> None:
    for exp in range(10):
        assert ffs(2**exp) == exp


# ---------------------------------------------------------------------------
# ffs_np
# ---------------------------------------------------------------------------


def test_ffs_np_zero_returns_zero() -> None:
    assert ffs_np(0) == 0


def test_ffs_np_power_of_two() -> None:
    assert int(ffs_np(4)) == 2
    assert int(ffs_np(8)) == 3


def test_ffs_np_lowest_set_bit() -> None:
    assert int(ffs_np(12)) == 2  # 0b1100 → bit 2


# ---------------------------------------------------------------------------
# int_log2
# ---------------------------------------------------------------------------


def test_int_log2_power_of_two() -> None:
    assert int_log2(4) == 2
    assert int_log2(8) == 3
    assert int_log2(1024) == 10


def test_int_log2_non_power_ceils() -> None:
    assert int_log2(5) == 3  # ceil(log2(5)) = 3
    assert int_log2(7) == 3  # ceil(log2(7)) = 3
    assert int_log2(9) == 4  # ceil(log2(9)) = 4


# ---------------------------------------------------------------------------
# slicer
# ---------------------------------------------------------------------------


def test_slicer_list_into_chunks() -> None:
    result = slicer([1, 2, 3, 4, 5, 6], 2)
    assert result == [[1, 2], [3, 4], [5, 6]]


def test_slicer_uneven_length() -> None:
    result = slicer([1, 2, 3, 4, 5], 2)
    assert result == [[1, 2], [3, 4], [5]]


def test_slicer_string_input() -> None:
    result = slicer("abcdef", 3)
    assert result == ["abc", "def"]


def test_slicer_with_custom_converter() -> None:
    result = slicer([1, 2, 3, 4], 2, converter=tuple)
    assert result == [(1, 2), (3, 4)]


def test_slicer_slice_larger_than_input() -> None:
    result = slicer([1, 2], 5)
    assert result == [[1, 2]]


# ---------------------------------------------------------------------------
# chunks
# ---------------------------------------------------------------------------


def test_chunks_even_split() -> None:
    assert chunks([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]


def test_chunks_uneven_split() -> None:
    result = chunks([1, 2, 3, 4, 5], 2)
    assert result == [[1, 2], [3, 4], [5]]


def test_chunks_size_equals_length() -> None:
    assert chunks([1, 2, 3], 3) == [[1, 2, 3]]


def test_chunks_size_one() -> None:
    assert chunks([1, 2, 3], 1) == [[1], [2], [3]]


def test_chunks_empty_input() -> None:
    assert chunks([], 3) == []


# ---------------------------------------------------------------------------
# flatten
# ---------------------------------------------------------------------------


def test_flatten_flat_list() -> None:
    assert flatten([1, 2, 3]) == [1, 2, 3]


def test_flatten_nested_list() -> None:
    assert flatten([1, [2, 3], [4, [5, 6]]]) == [1, 2, 3, 4, 5, 6]


def test_flatten_tuple_inside() -> None:
    assert flatten([1, (2, 3), 4]) == [1, 2, 3, 4]


def test_flatten_empty() -> None:
    assert flatten([]) == []


def test_flatten_deeply_nested() -> None:
    assert flatten([[[1, 2], 3], [4]]) == [1, 2, 3, 4]


def test_flatten_no_nesting() -> None:
    assert flatten(["a", "b", "c"]) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# partition
# ---------------------------------------------------------------------------


def test_partition_even_odd() -> None:
    evens, odds = partition(lambda x: x % 2 == 0, [1, 2, 3, 4, 5, 6])
    assert list(evens) == [2, 4, 6]
    assert list(odds) == [1, 3, 5]


def test_partition_all_match() -> None:
    yes, no = partition(lambda x: x > 0, [1, 2, 3])
    assert list(yes) == [1, 2, 3]
    assert list(no) == []


def test_partition_none_match() -> None:
    yes, no = partition(lambda x: x < 0, [1, 2, 3])
    assert list(yes) == []
    assert list(no) == [1, 2, 3]


# ---------------------------------------------------------------------------
# adjust_to_word_boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,alignment,expected",
    [
        (4, 2, 4),  # already aligned (4 % 4 == 0)
        (5, 2, 8),  # 5 → next 4-byte boundary = 8
        (8, 2, 8),  # already aligned
        (9, 2, 12),  # 9 → 12
        (0, 2, 0),  # 0 is always aligned
        (1, 1, 2),  # alignment=1 → 2-byte boundary
        (3, 1, 4),
    ],
)
def test_adjust_to_word_boundary(value: int, alignment: int, expected: int) -> None:
    assert adjust_to_word_boundary(value, alignment) == expected


def test_adjust_to_word_boundary_default_alignment() -> None:
    # default alignment=2 → 4-byte boundaries
    assert adjust_to_word_boundary(4) == 4
    assert adjust_to_word_boundary(5) == 8
