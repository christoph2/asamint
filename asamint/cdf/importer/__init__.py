from collections.abc import Mapping
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from asamint.calibration.db import CalibrationDB
from asamint.calibration.msrsw_db import (Category, DataFile, DisplayName,
                                          LongName, Msrsw, MSRSWDatabase,
                                          ShortName, SwCsCollection,
                                          SwCsCollections, SwInstance,
                                          SwInstanceSpec, SwInstanceTree,
                                          SwInstanceTreeOrigin, SwSystem,
                                          SwSystems, SwValueCont, SymbolicFile,
                                          UnitDisplayName)
from asamint.model.calibration import klasses

logger = logging.getLogger(__name__)


class DBImporter:
    opened: bool = False

    def __init__(
        self, file_name: str, parameters: Mapping[str, Any], logger: Any
    ) -> None:
        db_name = Path(file_name).with_suffix(".msrswdb")
        self.parameters = parameters
        self.logger = logger
        with suppress(FileNotFoundError):
            db_name.unlink()
        self.logger.info(f"Creating database {str(db_name)!r}.")
        self.cdf_db = MSRSWDatabase(db_name, debug=False)
        # self.hdf_db = h5py.File(db_name.with_suffix(".h5"), mode="w", libver="latest", locking="best-effort",
        #                         track_order=True)
        self.hdf_db = CalibrationDB(db_name, mode="w")
        self.session = self.cdf_db.session
        self.logger.info("Saving characteristics...")
        self.opened = True

    def close(self) -> None:
        if self.opened:
            self.hdf_db.close()
            self.cdf_db.close()
            self.opened = False

    def __del__(self) -> None:
        self.close()

    def run(self) -> None:
        self.top_level_boilerplate()
        self.logger.info("Done.")

    def top_level_boilerplate(self) -> None:
        msrsw = Msrsw()
        self.session.add(msrsw)

        self.set_short_name(msrsw, "calib_test")
        self.set_category(msrsw, "CDF20")

        systems = SwSystems()
        self.session.add(systems)
        msrsw.sw_systems = systems
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
        instance_tree.sw_instances = []
        self.logger.info("VALUEs")
        for value in self.parameters.get("VALUE", {}).values():
            instance_tree.sw_instances.append(self.scalar_value(value))
        self.logger.info("ASCIIs")
        for value in self.parameters.get("ASCII", {}).values():
            instance_tree.sw_instances.append(self.scalar_value(value))
        self.logger.info("VAL_BLKs")
        for value in self.parameters.get("VAL_BLK", {}).values():
            instance_tree.sw_instances.append(self.value_block(value))
        self.logger.info("AXIS_PTSs")
        for value in self.parameters.get("AXIS_PTS", {}).values():
            instance_tree.sw_instances.append(self.axis_pts(value))
        self.logger.info("CURVEs")
        for value in self.parameters.get("CURVE", {}).values():
            instance_tree.sw_instances.append(self.map_curve(value, "CURVE"))
        self.logger.info("MAPs")
        for value in self.parameters.get("MAP", {}).values():
            instance_tree.sw_instances.append(self.map_curve(value, "MAP"))
        self.logger.info("CUBOIDs")
        for value in self.parameters.get("CUBOID", {}).values():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBOID"))
        self.logger.info("CUBE_4s")
        for value in self.parameters.get("CUBE_4", {}).values():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBE_4"))
        self.logger.info("CUBE_5s")
        for value in self.parameters.get("CUBE_5", {}).values():
            instance_tree.sw_instances.append(self.map_curve(value, "CUBE_5"))
        self.session.commit()
        self.cdf_db.create_indices()

    def scalar_value(self, value: klasses.Value) -> SwInstance:
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit)
        self.hdf_db.import_scalar_value(value)
        return inst

    def map_curve(
        self,
        value: klasses.Curve | klasses.Map | klasses.Cuboid | klasses.Cube4 | klasses.Cube5,
        category: str,
    ) -> SwInstance:
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit)

        try:
            self.hdf_db.import_map_curve(value)
        except Exception as e:
            self.logger.error(f"map_curve({value.name}): {e} value: {value}")
        return inst

    def value_block(self, value: klasses.ValueBlock) -> SwInstance:
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit)
        self.hdf_db.import_value_block(value)
        return inst

    def axis_pts(self, value: klasses.AxisPts) -> SwInstance:
        inst = self.create_instance(value)
        self.add_value_container(inst, value.unit)
        self.hdf_db.import_axis_pts(value)
        return inst

    def create_instance(self, value: Any) -> SwInstance:
        inst = SwInstance()
        self.session.add(inst)
        self.set_short_name(inst, value.name)
        self.set_category(inst, "VALUE" if value.category == "TEXT" else value.category)
        if value.comment:
            self.set_long_name(inst, value.comment)
        if value.displayIdentifier:
            self.set_display_name(inst, value.displayIdentifier)
        return inst

    def add_value_container(self, obj: SwInstance, unit: str | None) -> None:
        container = SwValueCont()
        self.session.add(container)
        if unit:
            unit_display_name = UnitDisplayName()
            unit_display_name.content = unit
            container.unit_display_name = unit_display_name
        obj.sw_value_cont = container

    def set_short_name(self, obj: Any, name: str) -> None:
        short_name = ShortName()
        short_name.content = name
        self.session.add(short_name)
        obj.short_name = short_name

    def set_long_name(self, obj: Any, name: str) -> None:
        long_name = LongName()
        long_name.content = name
        self.session.add(long_name)
        obj.long_name = long_name

    def set_category(self, obj: Any, name: str) -> None:
        category = Category()
        category.content = name
        self.session.add(category)
        obj.category = category

    def set_display_name(self, obj: Any, name: str) -> None:
        display_name = DisplayName()
        display_name.content = name
        self.session.add(display_name)
        obj.display_name = display_name


from .cdf_importer import CDFImporter, import_cdf_to_db
