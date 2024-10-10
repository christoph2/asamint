#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2024 by Christoph Schueler <cpu12.gems.googlemail.com>

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
from rich import pretty
from rich.console import Console
from rich.traceback import install as tb_install


pretty.install()

# from .master import Master  # noqa: F401, E402
# from .transport import Can, Eth, SxI, Usb  # noqa: F401, E402


console = Console()
tb_install(show_locals=True, max_frames=3)  # Install custom exception handler.

# if you update this manually, do not forget to update
# .bumpversion.cfg and pyproject.toml.
__version__ = "0.1.4"
