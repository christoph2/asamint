#!/usr/bin/env python

__copyright__ = """
    pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2009-2016 by Christoph Schueler <github.com/Christoph2,
                                        cpu12.gems@googlemail.com>

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
"""

import logging
import os
from pathlib import Path

from asamint import parserlib
from asamint.damos.dcm_listener import Dcm20Listener

logger = logging.getLogger(__name__)

parser = parserlib.ParserWrapper("dcm20", "konservierung", Dcm20Listener)
# res = parser.parseFromFile(r"C:\Users\Chris\PycharmProjects\asamint\asamint\examples\Offical_ECU_Description\ASAP2_Demo_V171.dcm")
res = parser.parseFromFile(r"Z:\DAMOS\Damos\SCM900_C2\Daten_20l_42ASb\dcm\42ASb-M900_C2_X737_S05_new_labels.DCM")
# res = parser.parseFromFile(r"Z:\DAMOS\Damos\DMG1002A01C1303_MY17IC0\20170922_V6TFSI_C1303_B9_Q5_LK2_EU6_ULEV_IC0_DINH.dcm")

# res = parser.parseFromFile(r"Z:\DAMOS\DAMOS_A2L_ORI\DAMOS_A2L_ORI\AUDI_VW_SKODA_SEAT\VAG\BOSCH_ME7.5\24B5_EU3_WFS3\RDW_TT\RDWTT01.dcm")


BASE = r"Z:\DAMOS"

for root, _dirs, files in os.walk(BASE):
    for fn in files:
        pth = Path(root) / fn
        if pth.suffix != ".dcm":
            continue
        logger.info("%s", pth)
        try:
            res = parser.parseFromFile(pth)
        except Exception as e:
            logger.error("%s", e)

"""
line 3494:10 mismatched input '2.0' expecting {FLOAT, INT}
line 3495:10 mismatched input '2.0' expecting {FLOAT, INT}
line 3528:22 extraneous input '2.0' expecting {'\n', FLOAT, INT}
line 11384:8 mismatched input '2.0' expecting {FLOAT, INT}
line 11391:8 mismatched input '2.0' expecting {FLOAT, INT}
line 11503:8 mismatched input '2.0' expecting {FLOAT, INT}
line 12412:8 mismatched input '2.0' expecting {FLOAT, INT}
line 13024:22 extraneous input '2.0' expecting {'\n', 'FESTWERT', 'WERT', 'FESTWERTEBLOCK', 'KENNLINIE', 'FESTKENNLINIE', 'GRUPPENKENNLINIE', 'KENNFELD', 'FESTKENNFELD', 'GRUPPENKENNFELD', 'STUETZSTELLENVERTEILUNG', 'TEXTSTRING', 'ST/X', 'ST_TX/X', FLOAT, INT}
line 13029:10 mismatched input '2.0' expecting {FLOAT, INT}
=====================================================
"""
