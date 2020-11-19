#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Create ASAM MDF files from CDF20demo.a2l and some random data"""

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

"""
"""


import numpy as np

from sqlalchemy import func, or_

import pya2l.model as model
from pya2l.api.inspect import (Measurement, CompuMethod)

from asamint.cmdline import ArgumentParser
from asamint.mdf import MDFCreator


def random_data(mdf_obj, num_values = 100):

    STEPPER = 0.1
    data = {
        "TIMESTAMPS": np.arange(start = STEPPER, stop = (num_values // 10) + STEPPER, step = STEPPER, dtype = np.float32)
    }
    for meas in mdf_obj.measurements:
        if meas.datatype in ('FLOAT32_IEEE', 'FLOAT64_IEEE'):
            samples = 200 * np.random.random_sample(num_values) - 100
        elif meas.datatype in ('SBYTE', 'SWORD', 'SLONG', 'A_INT64'):
            samples = np.random.randint(-100, 100 + 1, num_values)
        else:
            samples = np.random.randint(0, 100 + 1, num_values)
        data[meas.name] = samples
    return data

def main():
    ap = ArgumentParser(use_xcp = False)

    mdf = MDFCreator(project_config = ap.project, experiment_config = ap.experiment)

    data = random_data(mdf, 1000)
    mdf.save_measurements("CDF20demo.mf4", data)

if __name__ == '__main__':
    main()
