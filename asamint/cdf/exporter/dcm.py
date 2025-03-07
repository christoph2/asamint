import functools
import operator
from decimal import Decimal

from asamint import utils
from asamint.cdf import walker
from asamint.msrsw.elements import ArraySize, Instance


def array_elements(array_size: ArraySize) -> int:
    return functools.reduce(operator.mul, array_size.dimensions, 1)


def axis():
    """
    STUETZSTELLENVERTEILUNG  ${inst.name} ${len(inst.converted_values)}\
${header(inst)}
##<% values = " ".join(["{:.8f}".format(x) for x in inst.converted_values]) %>
<% values = " ".join(["{:f}".format(x) for x in inst.converted_values.flatten()]) %>\
%for line in wrap(values, 130):
    ST/X ${line}
%endfor
END
    """


class Exporter(walker.CdfWalker):

    def on_header(self, shortname: str, a2l_file: str, hex_file: str, references: list, variants: bool):
        print("KONSERVIERUNG_FORMAT 2.0")

        print("* ", shortname, a2l_file, hex_file, variants)
        print("FUNKTIONEN")
        for ref in references:
            print(f'  FKT {ref.name} "" ""')
        print("END\n")

    def on_instance(self, instance: Instance) -> None:
        name = instance.short_name
        comment = instance.long_name
        function = instance.feature_ref
        unit = instance.values.unit_display_name
        category = instance.category
        value_container = instance.values
        axes = instance.axes
        array_size = value_container.array_size

        match category:
            case "VALUE" | "DEPENDENT_VALUE" | "BOOLEAN":
                value = value_container.values_phys[0].value
                print(f"FESTWERT {name}")
                if function:
                    print(f"  FUNKTION {function}")
                print(f'  EINHEIT_W "{unit.value}"')
                if isinstance(value, Decimal):
                    print(f"  WERT {value}")
                elif category == "BOOLEAN":
                    value = 1 if value == "true" else 0
                    print(f"  WERT {value}")
                else:
                    print(f'  TEXT "{value.replace("'", "")}"')
                print("END\n")
            case "ASCII":
                pass
            case "COM_AXIS":
                element_count = array_elements(value_container.array_size)
                print(f"STUETZSTELLENVERTEILUNG  {name} {element_count}")
                print(f'  EINHEIT_W "{unit.value}"')
                values = utils.flatten(value_container.values_phys)
                for row in utils.slicer(values, 6):
                    print(f"  ST/X {walker.dump_array(row)}")
                print("END\n")
            case "CURVE_AXIS":
                pass
            case "RES_AXIS":
                pass
            case "VAL_BLK":
                element_count = array_elements(value_container.array_size)
                print(f"FESTWERTEBLOCK {name} {element_count}")
                if function:
                    print(f"  FUNKTION {function.value}")
                print(f'  EINHEIT_W "{unit.value}"')
                values = utils.flatten(value_container.values_phys)
                for row in utils.slicer(values, 6):
                    print(f"  WERT {walker.dump_array(row)}")
                print("END\n")
            case "CURVE":

                print(f"KENNLINIE {name} {len(value_container.values_phys)}")
                if function:
                    print(f"  FUNKTION {function.value}")
                print(f'  EINHEIT_W "{unit.value}"')
                print(axes)
                print(value_container)
                print("END\n")
            case "MAP":
                pass
            #            case "CUBE_4":
            #                pass
            case _:
                print("\t\t\tCATEGORY!?", category)
