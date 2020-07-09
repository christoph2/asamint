#!/usr/bin/env python
# -*- coding: utf-8 -*-

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

from asamint import utils

import asammdf
from asammdf import MDF, Signal
from pya2l import DB
import pya2l.model as model


    # IDENTICAL     -
    # FORM          -
    # LINEAR        -
    # RAT_FUNC      -
    # TAB_INTP      -
    # TAB_NOINTP    -
    # TAB_VERB      -

    """
    0 = 1:1 conversion 0 0                                                      - IDENTICAL
    1 = parametric, linear 0 2                                                  - LINEAR
    2 = rational conversion formula 0 6                                         - RAT_FUNC
    3 = algebraic conversion (MCD-2 MC text formula) 1 0                        - FORM

    4 = value to value tabular look-up with interpolation 0 2 x n               - TAB_INTP
    5 = value to value tabular look-up without interpolation 0 2 x n            - TAB_NOINTP

    6 = value range to value tabular look-up 0 3 x n + 1

    7 = value to text/scale conversion tabular look-up n + 1 n
    8 = value range to text/scale conversion tabular look-up  n + 1 2 x n
    9 = text to value tabular look-up n n + 1
    10 = text to text tabular look-up (translation) 2 x n + 1 0
    """



def create_conversion_channel(a2ldb, mdf_version):
    """
    """
    block = ChannelConversion(
        address = address,
        stream = stream,
        mapped = mapped,
        tx_map = tx_map,
    )


def create_mdf(session, mdf):
    measurements = session.query(model.Measurement).order_by(model.Measurement.name).all()
    for m in measurements:
        print("{:48} {:12} 0x{:08x} [{}]".format(m.name, m.datatype, m.ecu_address.address, m.conversion))
