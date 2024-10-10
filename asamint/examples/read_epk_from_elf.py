#!/usr/bin/env python

__copyright__ = """
  (C) 2022 by Christoph Schueler <cpu12.gems@googlemail.com>

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

import argparse

from objutils.elf import ElfParser


def main():
    parser = argparse.ArgumentParser(description="Display EPROM Kennung.")
    parser.add_argument("elf_file", help="ELF file")
    args = parser.parse_args()
    try:
        ep = ElfParser(args.elf_file)
    except Exception as e:
        print(f"\n'{args.elf_file}' is not valid ELF file. Raised exception: '{repr(e)}'.")
        exit(1)
    for section_name, syms in ep.symbols.fetch(sections="calflash_signature", name_pattern="epk", types_str="object").items():
        if not syms:
            print("Sorry, no EPK found.")
        else:
            epk = syms[0]
            print("Found EPROM Kennung @0x{:08x} '{}' [{} bytes].".format(epk.st_value, "", epk.st_size))
            print(ep.sections.get(section_name))
            break


if __name__ == "__main__":
    main()
