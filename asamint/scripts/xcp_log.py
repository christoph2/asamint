#!/usr/bin/env python
"""Read / export XCP raw measurement files.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021 by Christoph Schueler <cpu12.gems.googlemail.com>

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
import binascii
import csv

from asamint.xcp.reco import XcpLogFileReader


def main():
    ep = argparse.ArgumentParser()
    ep.add_argument("input_file", help="Input file (extension .xmraw)")
    ep.add_argument("-c", "--export-to-csv", dest="csv_file", help="Write XCP frames to .CSV file")
    args = ep.parse_args()
    print()
    reader = XcpLogFileReader(args.input_file)
    print("# of containers:    ", reader.num_containers)
    print("# of frames:        ", reader.total_record_count)
    print("Size / uncompressed:", reader.total_size_uncompressed)
    print("Size / compressed:  ", reader.total_size_compressed)
    print(f"Compression ratio:   {reader.compression_ratio:3.3f}")
    print("-" * 32, end="\n\n")
    if args.csv_file:
        with open(args.csv_file, "w", newline="") as outf:
            print(f"Writing frames to '{outf.name}'...")
            csv_writer = csv.writer(outf)
            for frame in reader.frames:
                cat, counter, timestamp, data = frame
                data = str(binascii.hexlify(data.tobytes()), encoding="ascii")
                csv_writer.writerow((cat, counter, timestamp, data))
            print("OK, done.")


if __name__ == "__main__":
    main()
