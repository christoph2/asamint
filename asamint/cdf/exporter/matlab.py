import logging
import sys
from typing import IO, Any

from asamint.cdf import walker
from asamint.msrsw.elements import Instance

logger = logging.getLogger(__name__)

"""%CANape Parameter ExportV1.0
par_info.date ='';
par_info.name ='';
par_info.department ='';
par_info.comment ='';
%Begin
"""


def do_axis_containers(conts) -> None:
    if conts:
        for cont in conts:
            logger.debug(
                "AX: %s %s %s %s %s",
                cont.category.phys,
                cont.unit_display_name,
                cont.array_size.dimensions,
                cont.instance_ref.name,
                walker.axis_formatter(walker.array_values(cont.values)),
            )


class Exporter(walker.CdfWalker):

    def __init__(self, db_name: str, output: IO[str] | None = None) -> None:
        super().__init__(db_name)
        self._out = output

    def _write(self, text: str) -> None:
        out = self._out or sys.stdout
        out.write(text)
        out.write("\n")

    def on_header(
        self,
        shortname: str,
        a2l_file: str,
        hex_file: str,
        references: list,
        variants: bool,
    ) -> None:
        self._write(f"HEADER {shortname} {a2l_file} {hex_file} {variants}")

    def on_instance(self, instance: Instance) -> None:
        name = instance.short_name
        value_container = instance.values
        unit = (
            value_container.unit_display_name.value
            if value_container.unit_display_name
            else ""
        )
        category = instance.category

        if category in {"VALUE", "DEPENDENT_VALUE", "BOOLEAN"}:
            self._emit_scalar(
                name, value_container, unit, self._scalar_suffix(category)
            )
        elif category == "ASCII":
            logger.debug("ASCII instance: %s", instance.short_name)
            self._emit_scalar(name, value_container, unit, " -- ASCII")
        elif category in {"VAL_BLK", "CURVE", "MAP"}:
            self._emit_array(name, value_container, unit, category)
        elif category in {"COM_AXIS", "RES_AXIS"}:
            self._emit_axis(name, value_container, unit, category)

    @staticmethod
    def _scalar_suffix(category: str) -> str:
        return {"VALUE": "", "DEPENDENT_VALUE": "  -- DEP", "BOOLEAN": "  -- BOOL"}[
            category
        ]

    @staticmethod
    def _array_suffix(category: str) -> str:
        return {
            "VAL_BLK": "  -- BLK",
            "CURVE": "  -- CURVE",
            "MAP": "  -- MAP",
            "COM_AXIS": "  -- COM",
            "RES_AXIS": "  -- RES",
        }[category]

    def _emit_scalar(self, name: str, value_container, unit: str, suffix: str) -> None:
        value = walker.scalar_value(value_container.values_phys)
        self._write(f"{name} = {value}; %[{unit}]@CANAPE_ORIGIN@{name}{suffix}")

    def _array_values(self, value_container, category: str) -> list[Any]:
        if category != "MAP":
            return walker.array_values(value_container.values_phys, flatten=False)
        array_size = value_container.array_size.dimensions
        if array_size:
            values = walker.array_values(value_container.values_phys, flatten=True)
            return walker.reshape(values, array_size)
        return walker.array_values(value_container.values_phys, flatten=False)

    def _emit_array(self, name: str, value_container, unit: str, category: str) -> None:
        values = self._array_values(value_container, category)
        self._write(
            f"{name} = [{walker.dump_array(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}{self._array_suffix(category)}"
        )

    def _emit_axis(self, name: str, value_container, unit: str, category: str) -> None:
        values = list(walker.array_values(value_container.values_phys, flatten=True))
        self._write(
            f"{name} = [{walker.axis_formatter(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}{self._array_suffix(category)}"
        )
