import functools
import operator
from decimal import Decimal
from typing import Optional

from asamint import utils
from asamint.cdf import walker
from asamint.msrsw.elements import ArraySize, Instance


def array_elements(array_size: ArraySize) -> int:
    return functools.reduce(operator.mul, array_size.dimensions, 1)


def axis():
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

    def on_header(
        self,
        shortname: str,
        a2l_file: str,
        hex_file: str,
        references: list,
        variants: bool,
    ):
        print("KONSERVIERUNG_FORMAT 2.0\n\n")

        # print("* ", shortname, a2l_file, hex_file, variants)
        # print("FUNKTIONEN")
        # for ref in references:
        #    print(f'  FKT {ref.name} "" ""')
        # print("END\n")

    def value_header(
        self,
        type_name: str,
        instance: Instance,
        size_x: Optional[int] = None,
        size_y: Optional[int] = None,
    ):
        name = instance.short_name
        comment = instance.long_name
        display_name = instance.display_name
        function = instance.feature_ref
        unit = instance.values.unit_display_name.phys
        if size_x is not None:
            if size_y is not None:
                print(f"{type_name} {name} {size_x} {size_y}")
            else:
                print(f"{type_name} {name} {size_x}")
        else:
            print(f"{type_name} {name}")
        if comment:
            print(f'  LANGNAME "{comment}"')
        if display_name:
            print(f'  DISPLAYNAME "{display_name}"')
        if function:
            print(f"  FUNKTION {function}")
        if unit:
            print(f'  EINHEIT_W "{unit}"')

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
            print("\t\t\tCATEGORY!?", category)

    def _emit_scalar(self, instance: Instance, category: str, value_container) -> None:
        value = value_container.values_phys[0].phys
        self.value_header("FESTWERT", instance)
        if value:
            if isinstance(value, Decimal):
                print(f"  WERT {value}")
            elif category == "BOOLEAN":
                print(f"  WERT {1 if value == 'true' else 0}")
            else:
                cleaned = value.replace("'", "")
                print(f'  TEXT "{cleaned}"')
        print("END\n")

    def _emit_rows(self, prefix: str, values: list[object]) -> None:
        for row in utils.slicer(values, 6):
            print(f"  {prefix} {walker.dump_array(row)}")

    def _emit_axis_distribution(self, instance: Instance, value_container) -> None:
        element_count = array_elements(value_container.array_size)
        self.value_header("STUETZSTELLENVERTEILUNG", instance, element_count)
        self._emit_rows(
            "ST/X", walker.array_values(value_container.values_phys, flatten=True)
        )
        print("END\n")

    def _emit_value_block(self, instance: Instance, value_container) -> None:
        element_count = array_elements(value_container.array_size)
        self.value_header("FESTWERTEBLOCK", instance, element_count)
        self._emit_rows(
            "WERT", walker.array_values(value_container.values_phys, flatten=True)
        )
        print("END\n")

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
            print(f"  *SSTX {axis.instance_ref.name}")
        else:
            self._emit_rows("ST/X", walker.array_values(axis.values_phys, flatten=True))
        self._emit_rows(
            "WERT", walker.array_values(value_container.values_phys, flatten=True)
        )
        print("END\n")
