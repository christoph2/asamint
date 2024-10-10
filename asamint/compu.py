#!/usr/bin/env python

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
__author__ = "Christoph Schueler"


from collections.abc import Mapping

import pya2l.model as model
from pya2l import DB


"""
a2ldb_import [imex]

"""


class CompuMethods(Mapping):
    """dict-like (non-modifiable) container for `COMPU_METHOD`s.

    Parameters
    ----------
    session: `SQLAlchemy` session instance.

    referenced: bool
        Only include referenced `COMPU_METHOD`s.
    """

    # IDENTICAL     -
    # FORM          -
    # LINEAR        -
    # RAT_FUNC      -
    # TAB_INTP      -
    # TAB_NOINTP    -
    # TAB_VERB      -

    """
    0 = 1:1 conversion 0 0
    1 = parametric, linear 0 2
    2 = rational conversion formula 0 6
    3 = algebraic conversion (MCD-2 MC text formula) 1 0
    4 = value to value tabular look-up with interpolation 0 2 x n
    5 = value to value tabular look-up without interpolation 0 2 x n
    6 = value range to value tabular look-up 0 3 x n + 1
    7 = value to text/scale conversion tabular look-up n + 1 n
    8 = value range to text/scale conversion tabular look-up  n + 1 2 x n
    9 = text to value tabular look-up n n + 1
    10 = text to text tabular look-up (translation) 2 x n + 1 0
    """

    def __init__(self, session, referenced: bool = True):
        if referenced:
            conversions = (
                session.query(model.Measurement.conversion).filter(model.Measurement.conversion != "NO_COMPU_METHOD").distinct()
            )
            self._compu_methods = {
                item.name: item for item in session.query(model.CompuMethod).filter(model.CompuMethod.name.in_(conversions)).all()
            }
        else:
            self._compu_methods = {item.name: item for item in session.query(model.CompuMethod).all()}
        for cm in self._compu_methods.values():
            conversionType = cm.conversionType
            if conversionType == "IDENTICAL":
                pass
            elif conversionType == "FORM":
                pass
            elif conversionType == "LINEAR":
                pass
            elif conversionType == "RAT_FUNC":
                pass
            elif conversionType == "TAB_INTP":
                pass
            elif conversionType == "TAB_NOINTP":
                pass
            elif conversionType == "TAB_VERB":
                pass
        print(self._compu_methods)

    def __getitem__(self, name):
        return self._compu_methods[name]

    def __iter__(self):
        return iter(self._compu_methods)

    def __len__(self):
        return len(self._compu_methods)


class Measurement:
    """Container for Measurement-related data."""

    def __init__(self, session, name):
        self.session = session
        self._meas = session.query(model.Measurement).filter(model.Measurement.name == name).first()


def getCM(session, name):
    if name != "NO_COMPU_METHOD":
        cm = session.query(model.CompuMethod).filter(model.CompuMethod.name == name).first()
        return cm
    else:
        return None


db = DB()
session = db.open_existing("ASAP2_Demo_V161")
measurements = session.query(model.Measurement).order_by(model.Measurement.name).all()

cms = CompuMethods(session)

for m in measurements:
    print(f"{m.name:48} {m.datatype:12} 0x{m.ecu_address.address:08x}")
    # print("{:48} {:12} 0x{:08x} [{}]".format(m.name, m.datatype, m.ecu_address.address, m.conversion))

conversions = session.query(model.Measurement.conversion).filter(model.Measurement.conversion != "NO_COMPU_METHOD").distinct()
# print(conversions)


cm = session.query(model.CompuMethod).filter(model.CompuMethod.name.in_(conversions)).all()
print("\n\n")
for c in cm:
    print(c)

print("\n\n")
print(list(cms.keys()))
