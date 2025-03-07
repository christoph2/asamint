#!/usr/bin/env python

from operator import itemgetter

from asamint.model.calibration.klasses import MemoryType


MT_ABBREVS = {
    MemoryType.AXIS_PTS: "AX",
    MemoryType.VALUE: "V",
    MemoryType.ASCII: "AS",
    MemoryType.VAL_BLK: "VB",
    MemoryType.CURVE: "CV",
    MemoryType.MAP: "M",
    MemoryType.CUBOID: "CB",
}


class MapFile:

    def __init__(self, filename, memory_map: dict, memory_errors: dict):
        self.memory_map = memory_map
        self.memory_errors = memory_errors
        self.out_file = open(filename, "w")

    def __del__(self):
        self.out_file.close()

    def run(self):
        self.header()
        self.allocated_objects()
        self.out_file.write("*" * 96)
        self.out_file.write("\n")
        self.out_file.write("ERRORS".center(96))
        self.out_file.write("\n")
        self.out_file.write("*" * 96)
        self.out_file.write("\n")
        self.error_objects()

    def header(self):
        self.out_file.write(f"{'name':<70s}    address   length  type\n")
        self.out_file.write("=" * 96)
        self.out_file.write("\n")

    def memory_objects(self, mem_objs):
        prev_address = None
        for address, objs in sorted(mem_objs.items(), key=itemgetter(0)):
            length = max(o.length for o in objs)
            names = ", ".join([o.name for o in objs])
            mt = MT_ABBREVS.get(objs[0].memory_type, "UNKNOWN")
            if prev_address is not None and (address - prev_address) > 1:
                self.out_file.write(f"{'':<30s}----------{'':<30s} 0x{prev_address:08X} {(address - prev_address):08d}\n")
            self.out_file.write(f"{names:<70s} 0x{address:08X} {length:08d}  {mt}\n")
            prev_address = address + length

    def allocated_objects(self):
        self.memory_objects(self.memory_map)

    def error_objects(self):
        self.memory_objects(self.memory_errors)
