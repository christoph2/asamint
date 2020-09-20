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

import argparse

from asamint.config import read_configuration

from pyxcp.master import Master
from pyxcp.transport.can import (try_to_install_system_supplied_drivers, registered_drivers)

try_to_install_system_supplied_drivers()

CAN_DRIVERS = registered_drivers()


class ArgumentParser:
    """

    Parameter
    ---------
    callout: callable
        Process user-supplied arguments.
    """

    def __init__(self, use_xcp = True, callout = None, *args, **kws):
        self.callout = callout
        self.use_xcp = use_xcp
        kws.update(formatter_class = argparse.RawDescriptionHelpFormatter, add_help = True)
        self._parser = argparse.ArgumentParser(*args, **kws)
        self._parser.add_argument('-p', '--project-file', type = argparse.FileType('r'), dest = "project",
            help = 'General project configuration.')

        self._parser.add_argument('-e', '--experiment-file', type = argparse.FileType('r'), dest = "experiment",
            help = 'Experiment specific configuration.')

        self._parser.add_argument('-l', '--loglevel', choices = ["ERROR", "WARN", "INFO", "DEBUG"], default = "INFO")
        self._parser.add_argument("-u", '--unlock', help = "Unlock protected resources", dest = "unlock", action = "store_true")
        #self._parser.epilog = "".format(self._parser.prog)
        self._args = []

    @property
    def args(self):
        return self._args

    def run(self):
        """

        """
        self._args = self.parser.parse_args()
        args = self.args
        self.project = read_configuration(args.project)
        self.experiment = read_configuration(args.experiment)
        self.project["LOGLEVEL"] = args.loglevel
        if not "TRANSPORT" in self.project:
            raise AttributeError("TRANSPORT must be specified in config!")
        transport = self.project['TRANSPORT'].lower()
        master = Master(transport, config = self.project) if self.use_xcp else None
        if self.callout:
            self.callout(master, args)
        return master

    @property
    def parser(self):
        return self._parser
