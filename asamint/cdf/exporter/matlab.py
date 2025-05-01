from asamint.cdf import walker
from asamint.msrsw.elements import Instance


"""%CANape Parameter ExportV1.0
par_info.date ='';
par_info.name ='';
par_info.department ='';
par_info.comment ='';
%Begin
"""


def do_axis_containers(conts):
    if conts:
        for cont in conts:
            print(
                "\tAX:",
                cont.category.phys,
                cont.unit_display_name,
                cont.array_size.dimensions,
                cont.instance_ref.name,
                walker.axis_formatter(walker.array_values(cont.values)),
            )


class Exporter(walker.CdfWalker):

    def on_header(self, shortname: str, a2l_file: str, hex_file: str, references: list, variants: bool):
        print("HEADER", shortname, a2l_file, hex_file, variants)

    def on_instance(self, instance: Instance) -> None:
        # do_axis_containers(instance.axis_containers)
        name = instance.short_name
        comment = instance.long_name
        #        unit = instance.value_container.unit_display_name.value or ""

        match instance.category:
            case "VALUE":
                print(f"{name} = {walker.scalar_value(instance)}; %[{unit}]@CANAPE_ORIGIN@{name}")
            case "DEPENDENT_VALUE":
                print(f"{name} = {walker.scalar_value(instance)}; %[{unit}]@CANAPE_ORIGIN@{name}  -- DEP")
            case "BOOLEAN":
                print(f"{name} = {walker.scalar_value(instance)}; %[{unit}]@CANAPE_ORIGIN@{name}  -- BOOL")
            case "ASCII":
                print("\tACI!!!", instance.short_name)
                print(f"{name} = {walker.scalar_value(instance)}; %[{unit}]@CANAPE_ORIGIN@{name} -- ASCII")

            case "VAL_BLK":
                values = walker.array_values(instance.value_container.values, flatten=False)
                print(f"{name} = [{walker.dump_array(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}  -- BLK")
            case "CURVE":
                values = walker.array_values(instance.value_container.values, flatten=False)
                print(f"{name} = [{walker.dump_array(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}  -- CURVE")
            case "MAP":
                array_size = instance.value_container.array_size.dimensions
                if array_size:
                    values = walker.array_values(instance.value_container.values, flatten=True)
                    values = walker.reshape(values, array_size)
                else:
                    values = walker.array_values(instance.value_container.values, flatten=False)
                print(f"{name} = [{walker.dump_array(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}  -- MAP")
            case "COM_AXIS":
                values = [v for v in array_values(instance.value_container.values, flatten=True)]
                print(f"{name} = [{axis_formatter(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}  -- COM")
            case "CURVE_AXIS":
                pass
            case "RES_AXIS":
                values = [v for v in array_values(instance.value_container.values, flatten=True)]
                print(f"{name} = [{axis_formatter(values)}]; %[{unit}]@CANAPE_ORIGIN@{name}  -- RES")
            case _:
                pass
