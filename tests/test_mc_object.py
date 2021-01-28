#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pytest

from asamint.utils.optimize import McObject, make_continuous_blocks

def make_blocks(objs):
    sections = []
    for obj in objs:
        sections.append(McObject(*obj))
    return make_continuous_blocks(sections)

def test_overlap():
    OBJS = (
        ("BitSlice",     0x00125438, 2),
        ("BitSlice0",    0x00125438, 2),
        ("BitSlice1",    0x00125438, 2),
        ("bit12Counter", 0x00125438, 2),
        ("wordCounter",  0x00125438, 2),
        ("BitSlice2",    0x00125439, 2),
        ("ShiftByte",    0x0012543a, 1),
        ("Shifter_B0",   0x0012543a, 1),
        ("Shifter_B1",   0x0012543a, 1),
        ("Shifter_B2",   0x0012543a, 1),
        ("Shifter_B3",   0x0012543a, 1),
        ("KL1Output",    0x0012543c, 1),
    )
    blocks = make_blocks(OBJS)
    assert blocks == [
            McObject(name = "", address = 0x00125438, length = 3),
            #McObject(name = "", address = 0x00125438, length = 2),
            #McObject(name = "", address = 0x00125439, length = 2),
            #McObject(name = "", address = 0x0012543a, length = 1),
            McObject(name = "", address = 0x0012543c, length = 1)
    ]

def test_non_overlap1():
    OBJS = (
        ("BitSlice",     0x00125438, 1),
        ("BitSlice0",    0x00125439, 1),
        ("BitSlice1",    0x0012543a, 1),
        ("bit12Counter", 0x0012543b, 1),
    )
    blocks = make_blocks(OBJS)
    assert blocks == [
            McObject(name = "", address = 0x00125438, length = 4),
    ]

def test_non_continuous():
    OBJS = (
        ("BitSlice",     0x00125438, 1),
        ("BitSlice0",    0x0012543a, 1),
        ("BitSlice1",    0x0012543c, 1),
        ("bit12Counter", 0x0012543e, 1),
    )
    blocks = make_blocks(OBJS)
    assert blocks == [
            McObject(name = "", address = 0x00125438, length = 1),
            McObject(name = "", address = 0x0012543a, length = 1),
            McObject(name = "", address = 0x0012543c, length = 1),
            McObject(name = "", address = 0x0012543e, length = 1),
    ]


