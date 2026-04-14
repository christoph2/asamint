import functools
import logging
import operator
import sys
from decimal import Decimal
from typing import IO, Optional

from asamint import utils
from asamint.cdf import walker
from asamint.msrsw.elements import ArraySize, Instance

logger = logging.getLogger(__name__)


def array_elements(array_size: ArraySize) -> int:
    return functools.reduce(operator.mul, array_size.dimensions, 1)


def axis() -> None:
    """
    STUETZSTELLENVERTEILUNG  ${inst.name} ${len(inst.phys)}\
${header(inst)}
##<% values = " ".join(["{:.8f}".format(x) for x in inst.phys]) %>
<% values = " ".join(["{:f}".format(x) for x in inst.phys.flatten()]) %>\
%for line in wrap(values, 130):
    ST/X ${line}
%endfor
END
    """


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
        self._write("KONSERVIERUNG_FORMAT 2.0\n\n")

    def value_header(
        self,
        type_name: str,
        instance: Instance,
        size_x: Optional[int] = None,
        size_y: Optional[int] = None,
    ) -> None:
        name = instance.short_name
        comment = instance.long_name
        display_name = instance.display_name
        function = instance.feature_ref
        unit = instance.values.unit_display_name.phys
        if size_x is not None:
            if size_y is not None:
                self._write(f"{type_name} {name} {size_x} {size_y}")
            else:
                self._write(f"{type_name} {name} {size_x}")
        else:
            self._write(f"{type_name} {name}")
        if comment:
            self._write(f'  LANGNAME "{comment}"')
        if display_name:
            self._write(f'  DISPLAYNAME "{display_name}"')
        if function:
            self._write(f"  FUNKTION {function}")
        if unit:
            self._write(f'  EINHEIT_W "{unit}"')

    def on_instance(self, instance: Instance) -> None:
        category = instance.category
        value_container = instance.values
        axes = instance.axes

        if category in {"VALUE", "DEPENDENT_VALUE", "BOOLEAN", "ASCII"}:
            self._emit_scalar(instance, category, value_container)
        elif category == "COM_AXIS":
            self._emit_axis_distribution(instance, value_container)
        elif category in {"CURVE_AXIS", "RES_AXIS", "MAP"}:
            return
        elif category == "VAL_BLK":
            self._emit_value_block(instance, value_container)
        elif category == "CURVE":
            self._emit_curve(instance, value_container, axes)
        else:
            logger.warning("Unknown category: %s", category)

    def _emit_scalar(self, instance: Instance, category: str, value_container) -> None:
        value = value_container.values_phys[0].phys
        self.value_header("FESTWERT", instance)
        if value:
            if isinstance(value, Decimal):
                self._write(f"  WERT {value}")
            elif category == "BOOLEAN":
                self._write(f"  WERT {1 if value == 'true' else 0}")
            else:
                cleaned = value.replace("'", "")
                self._write(f'  TEXT "{cleaned}"')
        self._write("END\n")

    def _emit_rows(self, prefix: str, values: list[object]) -> None:
        for row in utils.slicer(values, 6):
            self._write(f"  {prefix} {walker.dump_array(row)}")

    def _emit_axis_distribution(self, instance: Instance, value_container) -> None:
        element_count = array_elements(value_container.array_size)
        self.value_header("STUETZSTELLENVERTEILUNG", instance, element_count)
        self._emit_rows("ST/X", walker.array_values(value_container.values_phys, flatten=True))
        self._write("END\n")

    def _emit_value_block(self, instance: Instance, value_container) -> None:
        element_count = array_elements(value_container.array_size)
        self.value_header("FESTWERTEBLOCK", instance, element_count)
        self._emit_rows("WERT", walker.array_values(value_container.values_phys, flatten=True))
        self._write("END\n")

    @staticmethod
    def _curve_type_name(axis_category: str) -> str:
        if axis_category == "COM_AXIS":
            return "GRUPPENKENNLINIE"
        if axis_category == "FIX_AXIS":
            return "FESTKENNLINIE"
        return "KENNLINIE"

    def _emit_curve(self, instance: Instance, value_container, axes) -> None:
        axis = axes[0]
        element_count = len(value_container.values_phys)
        self.value_header(self._curve_type_name(axis.category), instance, element_count)
        if axis.category == "COM_AXIS":
            self._write(f"  *SSTX {axis.instance_ref.name}")
        else:
            self._emit_rows("ST/X", walker.array_values(axis.values_phys, flatten=True))
        self._emit_rows("WERT", walker.array_values(value_container.values_phys, flatten=True))
        self._write("END\n")
