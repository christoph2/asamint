#!/usr/bin/env python
"""Create ASAM CDF files from 9Z72520S A2L / HEX.

Demonstrates the recommended asamint public API:

1. ``open_project()`` — reads ``asamint_conf.py``, parses A2L, creates
   working directories.  Returns an :class:`AsamMC` context manager.
2. ``load_all_characteristics()`` — loads **all** calibration parameters
   from the HEX file into an in-memory dictionary.
3. ``export_to_cdf()`` — serialises the parameters into an ASAM CDF20
   XML (``.cdfx``) file.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2026 by Christoph Schueler <cpu12.gems.googlemail.com>

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

from asamint.api import load_all_characteristics, open_project


def main() -> None:
    """Run the example workflow."""
    with open_project() as mc:
        params = load_all_characteristics(mc)
        mc.logger.info(
            "Loaded %d VALUE(s), %d CURVE(s), %d MAP(s).",
            len(params["VALUE"]),
            len(params["CURVE"]),
            len(params["MAP"]),
        )


if __name__ == "__main__":
    main()
