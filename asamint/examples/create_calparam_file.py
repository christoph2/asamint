#!/usr/bin/env python
"""Create ASAM CDF files from CDF20demo.a2l / CDF20demo.hex"""

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

from asamint.cdf import CDFCreator
from asamint.cmdline import ArgumentParser


def main():
    ap = ArgumentParser(use_xcp=False)
    cd = CDFCreator(ap.project, ap.experiment)
    cd.save_parameters(hexfile="CDF20demo.hex")


if __name__ == "__main__":
    main()
