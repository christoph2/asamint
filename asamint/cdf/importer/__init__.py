from pathlib import Path
from typing import List, Union

import h5py
import numpy as np
from numpy.dtypes import StringDType

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
    SwInstanceRef,
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


class DBImporter:
    opened: bool = False

    def __init__(self, file_name: str, parameters, logger):
        db_name = Path(file_name).with_suffix(".msrswdb")
        self.parameters = parameters
        self.logger = logger
        try:
            db_name.unlink()
        except Exception:
            pass
        self.logger.info(f"Creating database {str(db_name)!r}.")
        self.db = MSRSWDatabase(db_name, debug=False)
        self.storage = h5py.File(db_name.with_suffix(".h5"), mode="w", libver="latest", locking="best-effort", track_order=True)
        self.session = self.db.session
        self.logger.info("Saving characteristics...")
        self.opened = True

    def close(self):
        if self.opened:
            self.storage.close()
            self.db.close()
            self.opened = False

    def __del__(self):
        self.close()

    def run(self):
        self.top_level_boilerplate()
        self.logger.info("Done.")

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
        self.logger.info("VALUEs")
        for key, value in self.parameters.get("VALUE").items():
            instance_tree.sw_instances.append(self.scalar_value(value))
        self.logger.info("ASCIIs")
        for key, value in self.parameters.get("ASCII").items():
            instance_tree.sw_instances.append(self.scalar_value(value))
        self.logger.info("VAL_BLKs")
        for key, value in self.parameters.get("VAL_BLK").items():
            instance_tree.sw_instances.append(self.value_block(value))
        self.logger.info("AXIS_PTSs")
        for key, value in self.parameters.get("AXIS_PTS").items():
            instance_tree.sw_instances.append(self.axis_pts(value))
        self.logger.info("CURVEs")
        for key, value in self.parameters.get("CURVE").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CURVE"))
        self.logger.info("MAPs")
        for key, value in self.parameters.get("MAP").items():
            instance_tree.sw_instances.append(self.map_curve(value, "MAP"))
        self.logger.info("CUBOIDs")
        for key, value in self.parameters.get("CUBOID").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBOID"))
        self.logger.info("CUBE_4s")
        for key, value in self.parameters.get("CUBE_4").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBE_4"))
        self.logger.info("CUBE_5s")
        for key, value in self.parameters.get("CUBE_5").items():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBE_5"))
        self.session.commit()
        self.db.create_indices()

    def scalar_value(self, value):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)
        if value.category == "BOOLEAN":
            converted_value = 1 if value.converted_value == 1.0 else 0
            raw_value = value.raw_value
        elif value.category == "TEXT":
            converted_value = value.converted_value
            raw_value = value.raw_value
        elif value.category == "ASCII":
            converted_value = value.value.replace("\x00", " ") if value.value is not None else ""
            raw_value = converted_value
        else:
            converted_value = value.converted_value
            raw_value = value.raw_value
        ds = self.storage.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        ds.attrs["category"] = value.category
        ds.attrs["is_text"] = not value.is_numeric if value.category != "ASCII" else True
        ds.attrs["unit"] = value.unit if hasattr(value, "unit") and value.unit is not None else ""
        if raw_value is not None:
            ds["raw"] = raw_value
        if converted_value is not None:
            ds["converted"] = converted_value
        return inst

    def map_curve(self, value, category: str):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)
        ds = self.storage.create_group(name=f"/{value.name}", track_order=True)
        axes = ds.create_group("axes")
        ds.attrs["category"] = value.category
        ds.attrs["unit"] = value.fnc_unit if value.fnc_unit is not None else ""
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        ds.attrs["is_text"] = not value.is_numeric if value.category != "ASCII" else True
        if value.raw_values is not None:
            ds["raw"] = value.raw_values
        if value.converted_values is not None:
            if not value.is_numeric:
                ds["converted"] = value.converted_values.astype(h5py.string_dtype())
            else:
                ds["converted"] = value.converted_values
        for idx, axis in enumerate(value.axes):
            ax = axes.create_group(str(idx))
            category = axis.category
            ax.attrs["category"] = category
            ax.attrs["unit"] = axis.unit if axis.unit else ""
            ax.attrs["name"] = axis.name if axis.name else ""
            ax.attrs["input_quantity"] = axis.input_quantity if axis.input_quantity else ""
            match category:
                case "STD_AXIS" | "FIX_AXIS":
                    ax["raw"] = axis.raw_values
                    if not axis.is_numeric:
                        ax["converted"] = axis.converted_values.astype(h5py.string_dtype())
                    else:
                        ax["converted"] = axis.converted_values
                case "COM_AXIS" | "RES_AXIS" | "CURVE_AXIS":
                    ax["reference"] = h5py.SoftLink(f"/{axis.axis_pts_ref}")
        return inst

    def value_block(self, value):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)

        ds = self.storage.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["shape"] = value.converted_values.shape
        ds.attrs["is_text"] = not value.is_numeric
        ds.attrs["category"] = value.category
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        # ds.attrs["unit"] = value.unit if value.unit is not None else ""

        if value.raw_values.shape != (0,):
            ds["raw"] = value.raw_values
        if value.converted_values.shape != (0,):
            if not value.is_numeric:
                ds["converted"] = value.converted_values.astype(h5py.string_dtype())
            else:
                ds["converted"] = value.converted_values
        return inst

    def axis_pts(self, value):
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit if hasattr(value, "unit") else None)

        ds = self.storage.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["shape"] = value.converted_values.shape
        ds.attrs["is_text"] = not value.is_numeric
        ds.attrs["category"] = value.category
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""

        # ds.attrs["unit"] = value.unit if hasattr(value, "unit") else ""

        if value.raw_values.shape != (0,):
            ds["raw"] = value.raw_values
        if value.converted_values.shape != (0,):
            if not value.is_numeric:
                ds["converted"] = value.converted_values.astype(h5py.string_dtype())
            else:
                ds["converted"] = value.converted_values
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
