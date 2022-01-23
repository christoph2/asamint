#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pytest

from asamint.utils.optimize import make_continuous_blocks
from asamint.utils.optimize import McObject


def make_blocks(objs, upper_bound=None):
    sections = []
    for obj in objs:
        sections.append(McObject(*obj))
    return make_continuous_blocks(sections, upper_bound)


def test_overlap():
    OBJS = (
        ("BitSlice", 0x00125438, 2),
        ("BitSlice0", 0x00125438, 2),
        ("BitSlice1", 0x00125438, 2),
        ("bit12Counter", 0x00125438, 2),
        ("wordCounter", 0x00125438, 2),
        ("BitSlice2", 0x00125439, 2),
        ("ShiftByte", 0x0012543A, 1),
        ("Shifter_B0", 0x0012543A, 1),
        ("Shifter_B1", 0x0012543A, 1),
        ("Shifter_B2", 0x0012543A, 1),
        ("Shifter_B3", 0x0012543A, 1),
        ("KL1Output", 0x0012543C, 1),
    )
    blocks = make_blocks(OBJS)
    assert blocks == [
        McObject(name="", address=0x00125438, length=3),
        McObject(name="", address=0x0012543C, length=1),
    ]


def test_non_overlap1():
    OBJS = (
        ("BitSlice", 0x00125438, 1),
        ("BitSlice0", 0x00125439, 1),
        ("BitSlice1", 0x0012543A, 1),
        ("bit12Counter", 0x0012543B, 1),
    )
    blocks = make_blocks(OBJS)
    assert blocks == [
        McObject(name="", address=0x00125438, length=4),
    ]


def test_non_continuous():
    OBJS = (
        ("BitSlice", 0x00125438, 1),
        ("BitSlice0", 0x0012543A, 1),
        ("BitSlice1", 0x0012543C, 1),
        ("bit12Counter", 0x0012543E, 1),
    )
    blocks = make_blocks(OBJS)
    assert blocks == [
        McObject(name="", address=0x00125438, length=1),
        McObject(name="", address=0x0012543A, length=1),
        McObject(name="", address=0x0012543C, length=1),
        McObject(name="", address=0x0012543E, length=1),
    ]


def test_bounded_bins1():
    OBJS = (
        ("", 0x00001000, 4),
        ("", 0x00001004, 2),
        ("", 0x00001006, 4),
        ("", 0x0000100A, 2),
        ("", 0x0000100C, 4),
        ("", 0x00001010, 2),
    )
    blocks = make_blocks(OBJS, 7)
    assert blocks == [
        McObject(name="", address=0x00001000, length=6),
        McObject(name="", address=0x00001006, length=6),
        McObject(name="", address=0x0000100C, length=6),
    ]


def test_bounded_bins2():
    OBJS = (
        ("", 0x00001000, 4),
        ("", 0x00001004, 2),
        ("", 0x00001006, 1),
        ("", 0x00001007, 1),
        ("", 0x00001008, 1),
        ("", 0x00001009, 1),
        ("", 0x0000100A, 2),
        ("", 0x0000100C, 4),
        ("", 0x00001010, 2),
    )
    blocks = make_blocks(OBJS, 7)
    assert blocks == [
        McObject(name="", address=0x00001000, length=7),
        McObject(name="", address=0x00001007, length=5),
        McObject(name="", address=0x0000100C, length=6),
    ]


def test_mc_containment():
    mo = McObject("", 0x1000, 5)
    assert 0x0FFF not in mo
    assert 0x1000 in mo
    assert 0x1001 in mo
    assert 0x1002 in mo
    assert 0x1003 in mo
    assert 0x1004 in mo
    assert 0x1005 not in mo


def test_mc_index():
    mo = McObject("", 0x1000, 5)
    with pytest.raises(ValueError):
        assert mo.index(0x0FFF)
    assert mo.index(0x1000) == 0
    assert mo.index(0x1001) == 1
    assert mo.index(0x1002) == 2
    assert mo.index(0x1003) == 3
    assert mo.index(0x1004) == 4
    with pytest.raises(ValueError):
        assert mo.index(0x1005)
