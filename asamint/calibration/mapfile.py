#!/usr/bin/env python

from operator import itemgetter


def create_map_file(filename, memory_map: dict) -> None:
    prev_address = None
    with open(filename, "w") as file:
        for address, objs in sorted(memory_map.items(), key=itemgetter(0)):
            length = max(o.length for o in objs)
            names = ", ".join([o.name for o in objs])
            if prev_address is not None and (address - prev_address) > 1:
                file.write(f"{'':<30s}----------{'':<30s} 0x{prev_address:08X} {(address - prev_address):08d}\n")
            file.write(f"{names:<70s} 0x{address:08X} {length:08d}\n")
            prev_address = address + length
