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


def create_map_file(filename, memory_map: dict) -> None:
    prev_address = None
    with open(filename, "w") as file:
        file.write(f"{'name':<70s}    address   length  type\n")
        file.write("=" * 96)
        file.write("\n")
        for address, objs in sorted(memory_map.items(), key=itemgetter(0)):
            length = max(o.length for o in objs)
            names = ", ".join([o.name for o in objs])
            mt = MT_ABBREVS.get(objs[0].memory_type, "UNKNOWN")
            if prev_address is not None and (address - prev_address) > 1:
                file.write(f"{'':<30s}----------{'':<30s} 0x{prev_address:08X} {(address - prev_address):08d}\n")
            file.write(f"{names:<70s} 0x{address:08X} {length:08d}  {mt}\n")
            prev_address = address + length
