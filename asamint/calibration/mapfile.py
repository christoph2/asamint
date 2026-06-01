#!/usr/bin/env python

from pathlib import Path
from typing import Union

from asamint.model.calibration.klasses import MemoryType
from pya2l.api import inspect

LINE_WIDTH = 108

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
    """Write a human-readable memory-map report for calibration parameters.

    Args:
        filename: Output file path.
        memory_map: List of :class:`~asamint.asam.MemoryRange` describing the
            ECU memory segments together with the characteristic names they
            contain.
        memory_errors: Mapping of ``address → list[MemoryObject]`` collected
            during the calibration scan.
    """

    def __init__(self, session, filename: Union[str, Path], memory_map: list, memory_errors: dict) -> None:
        self.session = session
        self.memory_map = memory_map
        self.memory_errors = memory_errors
        self.out_file = open(filename, "w", encoding="utf-8")  # noqa: WPS515

    def __del__(self) -> None:
        try:
            self.out_file.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write(self, text: str) -> None:
        self.out_file.write(text)

    def _writeln(self, text: str = "") -> None:
        self.out_file.write(text + "\n")

    def _separator(self, char: str = "=") -> None:
        self._writeln(char * LINE_WIDTH)

    def _section_header(self, title: str) -> None:
        self._separator("*")
        self._writeln(title.center(LINE_WIDTH))
        self._separator("*")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Write the complete map file."""
        self._segment_header()
        self._allocated_objects()
        self._section_header("ERRORS")
        self._error_objects()

    # ------------------------------------------------------------------
    # Segments / allocated objects (list[MemoryRange])
    # ------------------------------------------------------------------

    def _segment_header(self) -> None:
        self._writeln(f"{'Segment':<30s}  {'Address':>12s}  {'Length (bytes)':>14s}  {'PrgType':<28s}  {'MemType':<12s}")
        self._separator()

    def _allocated_objects(self) -> None:
        prev_end: int | None = None

        for mr in sorted(self.memory_map, key=lambda r: r.address):
            # Print gap between segments
            if prev_end is not None and mr.address > prev_end:
                gap = mr.address - prev_end
                self._writeln(f"    {'<gap>':<28s}  {'':>9s}  {gap:>14d}  {'':28s}  {'':<12s}")

            # Segment line
            self._writeln(
                f"[{mr.name:<28s}  0x{mr.address:010X}  {mr.length:>14d}  {mr.prg_type.name:<28s}  {mr.memory_type.name}]"
            )

            entries = []
            if mr.characteristics:
                for char_name in mr.characteristics:
                    chs = inspect.Characteristic.get(self.session, char_name)
                    if chs is None:
                        # self.logger.warning("Characteristic %s not found", chs.name)
                        print(f"Characteristic {char_name!r} not found")
                        continue
                    size = chs.total_allocated_memory
                    entries.append((char_name, chs.address, size, chs.type))

            axis_pts: list[str] = getattr(mr, "axis_pts", [])
            if axis_pts:
                for ax_name in axis_pts:
                    ax = inspect.AxisPts.get(self.session, ax_name)
                    size = ax.axis_allocated_memory
                    entries.append((ax_name, ax.address, size, "AXIS_PTS"))
            entries.sort(key=lambda x: x[1])
            for name, address, size, category in entries:
                self._writeln(f"    {name:<63s}  0x{address:010X}  {size:>8d}  {category}")

            prev_end = mr.address + mr.length

        self._separator()

    # ------------------------------------------------------------------
    # Error objects (defaultdict[int, list[MemoryObject]])
    # ------------------------------------------------------------------

    def _error_objects(self) -> None:
        if not self.memory_errors:
            self._writeln("  <no errors>")
            return

        self._writeln(f"  {'Parameter':<50s}  {'Address':>12s}  {'Length':>8s}  {'Type':<6s}")
        self._separator("-")

        prev_address: int | None = None

        for address in sorted(self.memory_errors):
            objs = self.memory_errors[address]
            length = max(o.length for o in objs)
            names = ", ".join(o.name for o in objs)
            mt = MT_ABBREVS.get(objs[0].memory_type, "?")

            if prev_address is not None and (address - prev_address) > 1:
                gap = address - prev_address
                self._writeln(f"  {'<gap>':<50s}  {'':>12s}  {gap:>8d}")

            self._writeln(f"  {names:<50s}  0x{address:010X}  {length:>8d}  {mt:<6s}")
            prev_address = address + length
