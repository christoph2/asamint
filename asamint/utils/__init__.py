#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

   All Rights Reserved

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License along
   with this program; if not, write to the Free Software Foundation, Inc.,
   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

   s. FLOSS-EXCEPTION.txt
"""
__author__ = "Christoph Schueler"

import hashlib
import itertools
import math
import pathlib
import re
import time
from datetime import datetime
from typing import Any

import numpy as np
from babel import default_locale
from babel.dates import format_datetime


SINGLE_BITS = frozenset([2**b for b in range(64 + 1)])


def sha1_digest(x: str) -> str:
    return hashlib.sha1(x.encode("utf8")).hexdigest()  # nosec


def replace_non_c_char(s: str) -> str:
    return re.sub(r"[^.a-zA-Z0-9_]", "_", s)


def current_timestamp():
    return time.strftime("_%d%m%Y_%H%M%S")


def convert_name(name):
    """
    ASAP2 permits dotted, 'hierachical' names (like 'ASAM.M.SCALAR.UBYTE.TAB_NOINTP_DEFAULT_VALUE'),
    which may or may not be acceptable by tools.

    This function just replaces dots with underscores.
    """
    return name.replace(".", "_")


class Bunch(dict):
    """ """

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self.__dict__ = self


def make_2darray(arr):
    """Reshape higher dimensional array to two dimensions.

    Probably the most anti-idiomatic Numpy code in the universe...
    """
    if arr.ndim > 2:
        ndim = arr.ndim
        shape = list(arr.shape)
        reshaped = []
        while ndim > 2:
            reshaped.append(shape[0] * shape[1])
            ndim -= 1
            shape.pop(0)
            shape.pop(0)
            print(reshaped)
        if shape:
            reshaped.extend(shape)
        return arr.reshape(tuple(reshaped))
    else:
        return arr


def almost_equal(x, y, places=7):
    """Floating-point comparison done right."""
    return round(abs(x - y), places) == 0


def generate_filename(project_config, experiment_config, extension, extra=None):
    """Automatically generate filename from configuration plus timestamp."""
    project = project_config.get("PROJECT")
    subject = experiment_config.get("SUBJECT")
    if extra:
        return f"{project}_{subject}{current_timestamp()}_{extra}.{extension}"
    else:
        return f"{project}_{subject}{current_timestamp()}.{extension}"


def recursive_dict(element):
    return element.tag, dict(map(recursive_dict, element)) or element.text


def ffs(v: int) -> int:
    """Find first set bit (pure Python)."""
    return (v & (-v)).bit_length() - 1


def ffs_np(v):
    """Find first set bit (numpy)."""
    return np.uint64(np.log2(v & (-v))) if v != 0 else 0


def add_suffix_to_path(path: str, suffix: str) -> str:
    """(Conditionally) add / replace suffix/extension to a path."""

    return str(pathlib.Path(path).with_suffix(suffix))


def slicer(iterable, sliceLength, converter=None):
    if converter is None:
        converter = type(iterable)
    length = len(iterable)
    return [converter(iterable[item : item + sliceLength]) for item in range(0, length, sliceLength)]


def int_log2(x: float) -> int:
    return math.ceil(math.log2(x))


def current_datetime(locale=None):
    return format_datetime(datetime.utcnow(), locale=locale or default_locale)


def chunks(arr, size):
    """Split an array-like in `size` sub-arrays."""
    return [arr[i : i + size] for i in range(0, len(arr), size)]


def flatten(values: list[Any]) -> list[Any]:
    result = []
    for v in values:
        if isinstance(v, (list, tuple)):
            result.extend(flatten(v))
        else:
            result.append(v)
    return result


def partition(pred, iterable):
    t1, t2 = itertools.tee(iterable)
    return filter(pred, t2), itertools.filterfalse(pred, t1)
