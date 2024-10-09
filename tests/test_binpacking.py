import pytest

from asamint.utils.optimize import McObject, make_continuous_blocks
from asamint.utils.optimize.binpacking import Bin, first_fit_decreasing


@pytest.fixture
def blocks():
    return [
        McObject(name="", address=0x000E10BA, length=2),
        McObject(name="", address=0x000E10BE, length=2),
        McObject(name="", address=0x000E41F4, length=4),
        McObject(name="", address=0x000E51FC, length=4),
        McObject(name="", address=0x00125288, length=4),
        McObject(name="", address=0x00125294, length=4),
        McObject(name="", address=0x001252A1, length=1),
        McObject(name="", address=0x001252A4, length=4),
        McObject(name="", address=0x00125438, length=3),
        McObject(name="", address=0x0012543C, length=1),
    ]


def test_pack_to_single_bin(blocks):
    BIN_SIZE = 253
    bins = first_fit_decreasing(items=blocks, bin_size=BIN_SIZE)

    assert len(bins) == 1
    bin0 = bins[0]
    assert bin0.residual_capacity == BIN_SIZE - 29
    assert bin0.entries == [
        McObject(name="", address=0x000E41F4, length=4),
        McObject(name="", address=0x000E51FC, length=4),
        McObject(name="", address=0x00125288, length=4),
        McObject(name="", address=0x00125294, length=4),
        McObject(name="", address=0x001252A4, length=4),
        McObject(name="", address=0x00125438, length=3),
        McObject(name="", address=0x000E10BA, length=2),
        McObject(name="", address=0x000E10BE, length=2),
        McObject(name="", address=0x001252A1, length=1),
        McObject(name="", address=0x0012543C, length=1),
    ]


def test_pack_empty_block_set():
    BIN_SIZE = 253
    bins = first_fit_decreasing(items=[], bin_size=BIN_SIZE)
    assert bins == [Bin(size=BIN_SIZE)]


def test_pack_to_multiple_bins(blocks):
    BIN_SIZE = 6
    bins = first_fit_decreasing(items=blocks, bin_size=BIN_SIZE)
    assert len(bins) == 6
    bin0, bin1, bin2, bin3, bin4, bin5 = bins
    assert bin0.residual_capacity == 0
    assert bin0.entries == [
        McObject(name="", address=0x000E41F4, length=4),
        McObject(name="", address=0x000E10BA, length=2),
    ]
    assert bin1.residual_capacity == 0
    assert bin1.entries == [
        McObject(name="", address=0x000E51FC, length=4),
        McObject(name="", address=0x000E10BE, length=2),
    ]
    assert bin2.residual_capacity == 0
    assert bin2.entries == [
        McObject(name="", address=0x00125288, length=4),
        McObject(name="", address=0x001252A1, length=1),
        McObject(name="", address=0x0012543C, length=1),
    ]
    assert bin3.residual_capacity == 2
    assert bin3.entries == [McObject(name="", address=0x00125294, length=4)]
    assert bin4.residual_capacity == 2
    assert bin4.entries == [McObject(name="", address=0x001252A4, length=4)]
    assert bin5.residual_capacity == 3
    assert bin5.entries == [McObject(name="", address=0x00125438, length=3)]


def test_make_continuous_blocks1():
    BLOCKS = [
        McObject(name="", address=0x000E0002, length=2),
        McObject(name="", address=0x000E0008, ext=23, length=4),
        McObject(name="", address=0x000E0004, length=4),
        McObject(name="", address=0x000E000C, ext=23, length=4),
        McObject(name="", address=0x000E0000, length=2),
    ]
    bins = make_continuous_blocks(chunks=BLOCKS)
    assert bins == [
        McObject(name="", address=0x000E0000, ext=0x0000, length=8),
        McObject(name="", address=0x000E0008, ext=0x0017, length=8),
    ]


def test_make_continuous_blocks2():
    BLOCKS = [
        McObject(name="", address=0x000E0002, length=2),
        McObject(name="", address=0x000E0008, length=4),
        McObject(name="", address=0x000E0004, length=4),
        McObject(name="", address=0x000E000C, length=4),
        McObject(name="", address=0x000E0000, length=2),
    ]
    bins = make_continuous_blocks(chunks=BLOCKS)
    assert bins == [McObject(name="", address=0x000E0000, ext=0x0000, length=16)]


def test_make_continuous_blocks3():
    BLOCKS = [
        McObject(name="", address=0x000E0002, ext=0x01, length=2),
        McObject(name="", address=0x000E0008, ext=0x03, length=4),
        McObject(name="", address=0x000E0004, ext=0x02, length=4),
        McObject(name="", address=0x000E000C, ext=0x04, length=4),
        McObject(name="", address=0x000E0000, ext=0x00, length=2),
    ]
    bins = make_continuous_blocks(chunks=BLOCKS)
    assert bins == [
        McObject(name="", address=0x000E0000, ext=0x0000, length=2),
        McObject(name="", address=0x000E0002, ext=0x0001, length=2),
        McObject(name="", address=0x000E0004, ext=0x0002, length=4),
        McObject(name="", address=0x000E0008, ext=0x0003, length=4),
        McObject(name="", address=0x000E000C, ext=0x0004, length=4),
    ]


def test_mc_object_len_zero():
    with pytest.raises(ValueError):
        McObject(name="", address=0, ext=0, length=0)


def test_mc_object_ok():
    mc = McObject(name="", address=0, ext=0, length=1)
