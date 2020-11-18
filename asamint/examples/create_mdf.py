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


from sqlalchemy import func, or_

import pya2l.model as model

from pya2l.api.inspect import (Measurement, ModPar, CompuMethod)

from asamint.cmdline import ArgumentParser
from asamint.mdf import MDFCreator



def select_measurements(session, selections):
    """
    """
    query = session.query(model.Measurement.name, model.Measurement.conversion, model.Measurement.datatype)
    query = query.filter(or_(func.regexp(model.Measurement.name, sel) for sel in selections))
    for measurement in query.all():
        cm = CompuMethod(session, measurement.conversion)
        print(measurement.name, measurement.datatype)


def main():
    ap = ArgumentParser(use_xcp = False)

    mdf = MDFCreator(project_config = ap.project, experiment_config = ap.experiment)
    mdf.create_mdf("CDF20demo.mf4")

if __name__ == '__main__':
    main()
