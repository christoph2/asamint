#!/usr/bin/env python
"""Transfer CALRAM segments from a live XCP target into a HEX file."""

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

from typing import Any

from asamint.asam import AsamMC
from asamint.calibration import CalibrationData
from asamint.cmdline import ArgumentParser


def _prepare_xcp_connection(mc: AsamMC) -> Any:
    mc.xcp_connect()
    xcp_master = mc.xcp_master
    if xcp_master.slaveProperties.optionalCommMode:
        xcp_master.getCommModeInfo()
    xcp_general = mc.config.xcp.general
    if getattr(xcp_general, "seed_n_key_function", None) or getattr(
        xcp_general, "seed_n_key_dll", None
    ):
        xcp_master.cond_unlock()
    return xcp_master


def main() -> None:
    ap = ArgumentParser()
    ap.run()
    mc = AsamMC()
    cdm = CalibrationData(mc)
    try:
        xcp_master = _prepare_xcp_connection(mc)
        image = cdm.upload_calram(
            xcp_master=xcp_master,
            file_type=mc.master_hexfile_type,
        )
        if image is None:
            mc.logger.info("No CALRAM segment defined in MOD_PAR.")
        else:
            mc.logger.info("CALRAM transfer completed.")
    finally:
        cdm.close()


if __name__ == "__main__":
    main()
