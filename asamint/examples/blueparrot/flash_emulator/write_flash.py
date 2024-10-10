#!/usr/bin/env python
"""HEX file downloader.
"""

__copyright__ = """
    pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2009-2020 by Christoph Schueler <cpu12.gems@googlemail.com>

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

from os.path import exists

from create import create_example_hexfile
from objutils import load
from pyxcp.cmdline import ArgumentParser


HEX_FILE_NAME = "paged_flash.s28"

if not exists(HEX_FILE_NAME):
    create_example_hexfile()

hex_file = load("srec", HEX_FILE_NAME)


def upload_file(xcp_master):
    print(end="\n")
    for idx, sec in enumerate(hex_file, start=1):
        address = 0x8000  # Paging window.
        address_ext = (sec.start_address >> 16) - 0x10  # Calculate page number.
        data = sec.data
        # print(hex(address), address_ext, len(sec))
        print(f"Writing page {idx:02d} of 32", end="\r")
        xcp_master.setMta(address, address_ext)
        xcp_master.push(data)
    print("OK, successfully written 32 pages.")


def callout(master, args):
    if args.sk_dll:
        master.seedNKeyDLL = args.sk_dll


ap = ArgumentParser(callout, description="HEX file downloader.")
ap.parser.add_argument(
    "-s",
    "--sk-dll",
    dest="sk_dll",
    help="Seed-and-Key .DLL name",
    type=str,
    default=None,
)

with ap.run() as x:
    x.connect()
    if x.slaveProperties.optionalCommMode:
        x.getCommModeInfo()
    x.cond_unlock()
    upload_file(x)
    x.disconnect()
