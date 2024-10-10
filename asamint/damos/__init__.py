#!/usr/bin/env python
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

import pkgutil

import pya2l.model as model

from asamint.calibration import CalibrationData
from asamint.damos.dcm_listener import Dcm20Listener
from asamint.logger import Logger
from asamint.parserlib import ParserWrapper
from asamint.templates import renderTemplateFromText


# parser = ParserWrapper("dcm20", "konservierung", Dcm20Listener, debug = True)


class DCMCreator(CalibrationData):
    """ """

    EXTENSION = ".dcm"
    TEMPLATE = pkgutil.get_data("asamint", "data/templates/dcm.tmpl")

    def on_init(self, project_config, experiment_config, *args, **kws):
        super().on_init(project_config, experiment_config, *args, **kws)
        self.loadConfig(project_config, experiment_config)

    def save(self):

        namespace = {
            "params": self._parameters,
            "project": self.project_config,
            "experiment": self.experiment_config,
        }

        res = renderTemplateFromText(self.TEMPLATE, namespace, formatExceptions=False, encoding="latin-1")
        file_name = self.generate_filename(self.EXTENSION)
        self.logger.info(f"Saving tree to {file_name}")
        with open(f"{file_name}", "w") as of:
            of.write(res)
        print(res)
