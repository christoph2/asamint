from pathlib import Path
from typing import List, Union

from asamint.calibration.msrsw_db import (
    Category,
    DataFile,
    DisplayName,
    LongName,
    Msrsw,
    MSRSWDatabase,
    ShortName,
    SwArraysize,
    SwAxisCont,
    SwAxisConts,
    SwCsCollection,
    SwCsCollections,
    SwInstance,
    SwInstancePropsVariant,
    SwInstancePropsVariants,
    SwInstanceSpec,
    SwInstanceTree,
    SwInstanceTreeOrigin,
    SwSystem,
    SwSystems,
    SwValueCont,
    SwValuesCoded,
    SwValuesPhys,
    SymbolicFile,
    UnitDisplayName,
    V,
    Vf,
    Vg,
    Vh,
    Vt,
)
from asamint.utils import slicer


class DBImporter:

    def __init__(self, file_name: str, parameters, logger):
        db_name = Path(file_name).with_suffix(".msrswdb")
        self.parameters = parameters
        self.logger = logger
        try:
            db_name.unlink()
        except Exception:
            pass
        self.logger.info(f"Creating database {str(db_name)!r}")
        self.db = MSRSWDatabase(db_name, debug=False)
        self.session = self.db.session
        self.logger.info("Done.")
        # for k, v in parameters.items():
        #    print(k)

    def run(self):
        self.top_level_boilerplate()

    def top_level_boilerplate(self):
        msrsw = Msrsw()
        self.session.add(msrsw)

        self.set_short_name(msrsw, "calib_test")
        self.set_category(msrsw, "CDF20")

        systems = SwSystems()
        self.session.add(systems)
        system = SwSystem()

        self.set_short_name(system, "n/a")

        self.session.add(system)
        systems.sw_system.append(system)

        instance_spec = SwInstanceSpec()
        self.session.add(instance_spec)

        instance_tree = SwInstanceTree()
        self.set_short_name(instance_tree, r"ETAS\CalDemo_V2a\CalDemo_V2\CalDemo_V2_1")
        self.set_category(instance_tree, "VCD")
        self.session.add(instance_tree)

        origin = SwInstanceTreeOrigin()
        self.session.add(origin)

        instance_tree.sw_instance_tree_origin = origin

        symbolic_file = SymbolicFile()
        symbolic_file.content = "symfile.a2l"

        self.session.add(symbolic_file)

        data_file = DataFile()
        data_file.content = "datafile.hex"
        self.session.add(data_file)

        origin.symbolic_file = symbolic_file
        origin.data_file = data_file

        instance_spec.sw_instance_tree.append(instance_tree)
        system.sw_instance_spec = instance_spec

        collections = SwCsCollections()
        self.session.add(collections)
        collection = SwCsCollection()
        self.session.add(collection)

        collections.sw_cs_collection.append(collection)
        res = []
        instance_tree.sw_instances = []
        for key, value in self.parameters.get("VALUE").items():
            instance_tree.sw_instances.append(self.scalar_value(value))
        for key, value in self.parameters.get("ASCII").items():
            instance_tree.sw_instances.append(self.scalar_value(value))
        for key, value in self.parameters.get("VAL_BLK").items():
            instance_tree.sw_instances.append(self.value_block(value))
        for key, value in self.parameters.get("AXIS_PTS").items():
            instance_tree.sw_instances.append(self.axis_pts(value))
        for key, value in self.parameters.get("CURVE").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CURVE"))
        for key, value in self.parameters.get("MAP").items():
            instance_tree.sw_instances.append(self.map_curve(value, "MAP"))
        for key, value in self.parameters.get("CUBOID").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBOID"))
        for key, value in self.parameters.get("CUBE_4").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBE_4"))
        for key, value in self.parameters.get("CUBE_5").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBE_5"))
        self.session.commit()
        self.db.close()

    def scalar_value(self, value):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)
        values_phys = SwValuesPhys()  # self.create_values_phys(inst, value.converted_value)
        values_coded = SwValuesCoded()
        inst.sw_value_cont.sw_values_phys = values_phys
        inst.sw_value_cont.sw_values_coded = values_coded
        self.session.add(values_phys)
        self.session.add(values_coded)
        is_text = False
        if value.category == "BOOLEAN":
            converted_value = 1 if value.converted_value == 1.0 else 0
            raw_value = value.raw_value
        elif value.category == "TEXT":
            converted_value = value.converted_value
            raw_value = value.raw_value
            is_text = True
        elif value.category == "ASCII":
            converted_value = value.value
            raw_value = value.value
            is_text = True
        else:
            converted_value = value.converted_value
            raw_value = value.raw_value
        if is_text:
            node_phys = Vt()
            node_internal = Vt()
        else:
            node_phys = V()
            node_internal = V()
        self.session.add(node_phys)
        self.session.add(node_internal)
        node_phys.content = converted_value
        node_internal.content = raw_value
        if is_text:
            values_phys.vts = []
            values_phys.vts.append(node_phys)
            values_coded.vts = []
            values_coded.vts.append(node_internal)
        else:
            values_phys.vs = []
            values_phys.vs.append(node_phys)
            values_coded.vs = []
            values_coded.vs.append(node_internal)
        return inst

    def map_curve(self, value, category: str):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)
        values_phys = SwValuesPhys()  # self.create_values_phys(inst, value.converted_value)
        values_coded = SwValuesCoded()
        inst.sw_value_cont.sw_values_phys = values_phys
        inst.sw_value_cont.sw_values_coded = values_coded
        self.session.add(values_phys)
        self.session.add(values_coded)

        sw_axis_conts = SwAxisConts()
        self.session.add(sw_axis_conts)
        inst.sw_axis_conts = sw_axis_conts

        if value.converted_values.shape != (0,):
            self.output_value_array(inst.sw_value_cont.sw_values_phys, value.converted_values, is_numeric=value.is_numeric)
        if value.raw_values.shape != (0,):
            self.output_value_array(inst.sw_value_cont.sw_values_coded, value.raw_values)
        for axis in value.axes:
            print("\t", axis)
            category = axis.category
            match category:
                case "STD_AXIS":
                    self.add_axis(sw_axis_conts.sw_axis_cont, axis.converted_values, axis.raw_values, "STD_AXIS", axis.unit)
                case "FIX_AXIS":
                    self.add_axis(sw_axis_conts.sw_axis_cont, axis.converted_values, axis.raw_values, "FIX_AXIS", axis.unit)
                case "COM_AXIS" | "RES_AXIS" | "CURVE_AXIS":
                    # axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
                    # create_elem(axis_cont, "CATEGORY", "COM_AXIS")
                    # create_elem(axis_cont, "SW-INSTANCE-REF", text=axis.axi.s_pts_ref)
                    pass
        return inst

    def value_block(self, value):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)
        values_phys = SwValuesPhys()  # self.create_values_phys(inst, value.converted_value)
        values_coded = SwValuesCoded()
        inst.sw_value_cont.sw_values_phys = values_phys
        inst.sw_value_cont.sw_values_coded = values_coded
        self.session.add(values_phys)
        self.session.add(values_coded)
        arraysize = SwArraysize()
        self.session.add(arraysize)
        inst.sw_value_cont.sw_arraysize = arraysize
        if value.converted_values.shape != (0,):
            self.add_1d_array(inst.sw_value_cont, "sw_arraysize", reversed(value.converted_values.shape))
            self.output_value_array(inst.sw_value_cont.sw_values_phys, value.converted_values, is_numeric=value.is_numeric)
        if value.raw_values.shape != (0,):
            self.output_value_array(inst.sw_value_cont.sw_values_coded, value.raw_values)
        return inst

    def axis_pts(self, value):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)
        values_phys = SwValuesPhys()  # self.create_values_phys(inst, value.converted_value)
        values_coded = SwValuesCoded()
        inst.sw_value_cont.sw_values_phys = values_phys
        inst.sw_value_cont.sw_values_coded = values_coded
        self.session.add(values_phys)
        self.session.add(values_coded)
        arraysize = SwArraysize()
        self.session.add(arraysize)
        inst.sw_value_cont.sw_arraysize = arraysize
        if value.converted_values.shape != (0,):
            self.add_1d_array(inst.sw_value_cont, "sw_arraysize", reversed(value.converted_values.shape))
            self.output_value_array(inst.sw_value_cont.sw_values_phys, value.converted_values, is_numeric=value.is_numeric)
        if value.raw_values.shape != (0,):
            self.output_value_array(inst.sw_value_cont.sw_values_coded, value.raw_values)
        return inst

    def create_instance(self, value):
        inst = SwInstance()
        self.session.add(inst)
        self.set_short_name(inst, value.name)
        self.set_category(inst, "VALUE" if value.category == "TEXT" else value.category)
        if value.comment:
            self.set_long_name(inst, value.comment)
        if value.displayIdentifier:
            self.set_display_name(inst, value.displayIdentifier)
        return inst

    def add_value_container(self, obj, unit: str):
        container = SwValueCont()
        self.session.add(container)
        if unit:
            unit_display_name = UnitDisplayName()
            unit_display_name.content = unit
            container.unit_display_name = unit_display_name
        obj.sw_value_cont = container

    def set_short_name(self, obj, name):
        short_name = ShortName()
        short_name.content = name
        self.session.add(short_name)
        obj.short_name = short_name

    def set_long_name(self, obj, name):
        long_name = LongName()
        long_name.content = name
        self.session.add(long_name)
        obj.long_name = long_name

    def set_category(self, obj, name):
        category = Category()
        category.content = name
        self.session.add(category)
        obj.category = category

    def set_display_name(self, obj, name):
        display_name = DisplayName()
        display_name.content = name
        self.session.add(display_name)
        obj.display_name = display_name

    def add_1d_array(self, obj, name: str, values=[], is_numeric: bool = True, paired: bool = False):
        if is_numeric:
            value_klass = V
        else:
            value_klass = Vt
        if name:
            container = getattr(obj, name)
        else:
            container = obj
        result = []
        if paired:
            if isinstance(values, np.ndarray):
                parts = np.split(values, values.size // 2)
            else:
                parts = slicer(values, 2)
            for part in parts:
                group = Vg()
                self.session.add(group)
                container.vgs.append(group)
                v0 = value_klass()
                v0.content = part[0]
                v1 = value_klass()
                v1.content = part[1]
                self.session.add(v0)
                self.session.add(v1)
                group.vs.append(v0)
                group.vs.append(v1)
        else:
            for value in values:
                value_holder = value_klass()
                value_holder.content = value
                self.session.add(value_holder)
                result.append(value_holder)
            if is_numeric:
                container.vs = result
            else:
                container.vts = result

    def output_value_array(self, obj, values, is_numeric: bool = True):
        if values.ndim == 1:
            self.add_1d_array(obj, None, values, is_numeric)
        else:
            obj.vgs = []
            for value in values:
                vg = Vg()
                self.session.add(vg)
                obj.vgs.append(vg)
                self.output_value_array(vg, value, is_numeric)

    # def add_axis(self, axis_conts, converted_value, raw_values, category, unit=""):
    #    axis_cont = create_elem(axis_conts, "SW-AXIS-CONT")
    #    create_elem(axis_cont, "CATEGORY", text=category)
    #    if unit:
    #        create_elem(axis_cont, "UNIT-DISPLAY-NAME", text=unit)
    #    self.output_1darray(axis_cont, "SW-VALUES-PHYS", converted_value)

    def add_axis(self, obj, converted_values, raw_values, category, unit=""):
        # sw_axis_cont = SwAxisCont()
        # self.session.add(sw_axis_cont)
        # inst.sw_axis_conts.sw_axis_cont.append(sw_axis_cont)

        axis_cont = SwAxisCont()
        self.session.add(axis_cont)
        obj.append(axis_cont)
        self.set_category(axis_cont, category)
        if unit:
            unit_display_name = UnitDisplayName()
            self.session.add(unit_display_name)
            unit_display_name.content = unit
            axis_cont.unit_display_name = unit_display_name
        values_phys = SwValuesPhys()
        values_coded = SwValuesCoded()
        self.session.add(values_phys)
        self.session.add(values_coded)
        axis_cont.sw_values_phys = values_phys
        axis_cont.sw_values_coded = values_coded
        self.add_1d_array(axis_cont, "sw_values_phys", converted_values)
        self.add_1d_array(axis_cont, "sw_values_coded", raw_values)
