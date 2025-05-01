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

    def on_header(self, shortname: str, a2l_file: str, hex_file: str, references: list, variants: bool):
        print("KONSERVIERUNG_FORMAT 2.0\n\n")

        # print("* ", shortname, a2l_file, hex_file, variants)
        # print("FUNKTIONEN")
        # for ref in references:
        #    print(f'  FKT {ref.name} "" ""')
        # print("END\n")

    def value_header(self, type_name: str, instance: Instance, size_x: Optional[int] = None, size_y: Optional[int] = None):
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
        name = instance.short_name
        comment = instance.long_name
        display_name = instance.display_name
        function = instance.feature_ref
        unit = instance.values.unit_display_name.phys
        category = instance.category
        value_container = instance.values
        axes = instance.axes
        array_size = value_container.array_size

        match category:
            case "VALUE" | "DEPENDENT_VALUE" | "BOOLEAN" | "ASCII":
                value = value_container.values_phys[0].phys
                self.value_header("FESTWERT", instance)
                if value:
                    if isinstance(value, Decimal):
                        print(f"  WERT {value}")
                    elif category == "BOOLEAN":
                        value = 1 if value == "true" else 0
                        print(f"  WERT {value}")
                    else:
                        print(f'  TEXT "{value.replace("'", "")}"')
                print("END\n")
            case "COM_AXIS":
                element_count = array_elements(value_container.array_size)
                self.value_header("STUETZSTELLENVERTEILUNG", instance, element_count)
                values = walker.array_values(value_container.values_phys, flatten=True)
                for row in utils.slicer(values, 6):
                    print(f"  ST/X {walker.dump_array(row)}")
                print("END\n")
            case "CURVE_AXIS":
                pass
            case "RES_AXIS":
                pass
            case "VAL_BLK":
                element_count = array_elements(value_container.array_size)
                self.value_header("FESTWERTEBLOCK", instance, element_count)
                values = walker.array_values(value_container.values_phys, flatten=True)
                for row in utils.slicer(values, 6):
                    print(f"  WERT {walker.dump_array(row)}")
                print("END\n")
            case "CURVE":
                axis = axes[0]
                element_count = len(value_container.values_phys)
                if axis.category == "COM_AXIS":
                    type_name = "GRUPPENKENNLINIE"
                elif axis.category == "FIX_AXIS":
                    type_name = "FESTKENNLINIE"
                else:  # if axis.category=='STD_AXIS':
                    type_name = "KENNLINIE"
                self.value_header(type_name, instance, element_count)
                if axis.category == "COM_AXIS":
                    print(f"  *SSTX {axis.instance_ref.name}")
                else:
                    values = walker.array_values(axis.values_phys, flatten=True)
                    for row in utils.slicer(values, 6):
                        print(f"  ST/X {walker.dump_array(row)}")
                values = walker.array_values(value_container.values_phys, flatten=True)
                for row in utils.slicer(values, 6):
                    print(f"  WERT {walker.dump_array(row)}")
                print("END\n")
            case "MAP":
                pass
            #            case "CUBE_4":
            #                pass
            case _:
                print("\t\t\tCATEGORY!?", category)
