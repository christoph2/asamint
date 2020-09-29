#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020 by Christoph Schueler <cpu12.gems.googlemail.com>

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
__author__  = 'Christoph Schueler'

import hashlib
import os
import re
import time

from lxml.etree import SubElement

SINGLE_BITS = frozenset([2 ** b for b in range(64)])

sha1_digest = lambda x: hashlib.sha1(x.encode("utf8")).hexdigest()
replace_non_c_char = lambda s: re.sub(r"[^.a-zA-Z0-9_]", "_", s)

def convert_name(name):
    """
    ASAP2 permits dotted, 'hierachical' names (like 'ASAM.M.SCALAR.UBYTE.TAB_NOINTP_DEFAULT_VALUE'),
    which may or may not be acceptable by tools.

    This function just replaces dots with underscores.
    """
    return name.replace(".", "_")

def create_elem(parent, name, text = None, attrib = {}):
    """

    """
    elem = SubElement(parent, name, attrib)
    if text:
        elem.text = text
    return elem

class Bunch(dict):
    """
    """
    def __init__(self, *args, **kwds):
        super(Bunch, self).__init__(*args, **kwds)
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

def almost_equal(x, y, places = 7):
    """Floating-point comparison done right.
    """
    return round(abs(x - y), places) == 0


def generate_filename(project_config, experiment_config, extension, extra = None):
    """Automatically generate filename from configuration plus timestamp.
    """
    project = project_config.get("PROJECT")
    subject = experiment_config.get("SUBJECT")
    if extra:
        return "{}_{}_{}_{}.{}".format(project, subject, time.strftime("%Y%m%d%H%M%S"), extra, extension)
    else:
        return "{}_{}_{}.{}".format(project, subject, time.strftime("%Y%m%d%H%M%S"), extension)

def cond_create_directories():
    """
    """
    SUB_DIRS = ["measurements", "parameters", "hexfiles"]   # Directory names could be configurable.
    for d in SUB_DIRS:
        if not os.access(d, os.F_OK):
            os.mkdir(d)
