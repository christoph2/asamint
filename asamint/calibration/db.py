import uuid
from pathlib import Path
from typing import Union

import h5py
import numpy as np
import xarray as xr

from asamint.model.calibration import klasses


class CalibrationDB:
    """ """

    def __init__(self, file_name: str):
        self.opened = False
        db_name = Path(file_name).with_suffix(".h5")
        # self.logger = logger
        # self.logger.info(f"Creating database {str(db_name)!r}.")

        # mode = "r"
        mode = "w"
        self.db = h5py.File(db_name, mode=mode, libver="latest", locking="best-effort", track_order=True)
        #         self.hdf_db = h5py.File(db_name.with_suffix(".h5"), mode="w", libver="latest", locking="best-effort",
        #                                  track_order=True)

        self.opened = True
        self.guid = uuid.uuid4()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if self.opened:
            self.db.close()
            self.opened = False

    def import_scalar_value(self, value: klasses.Value) -> None:
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
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        ds.attrs["category"] = value.category
        ds.attrs["is_text"] = not value.is_numeric if value.category != "ASCII" else True
        ds.attrs["unit"] = value.unit if hasattr(value, "unit") and value.unit is not None else ""
        if raw_value is not None:
            ds["raw"] = raw_value
        if converted_value is not None:
            ds["converted"] = converted_value

    def import_value_block(self, value: klasses.ValueBlock) -> None:
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["shape"] = value.converted_values.shape
        ds.attrs["is_text"] = not value.is_numeric
        ds.attrs["category"] = value.category
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        if value.raw_values.shape != (0,):
            ds["raw"] = value.raw_values
        if value.converted_values.shape != (0,):
            if not value.is_numeric:
                ds["converted"] = value.converted_values.astype(h5py.string_dtype())
            else:
                ds["converted"] = value.converted_values

    def import_axis_pts(self, value: klasses.AxisPts) -> None:
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["shape"] = value.converted_values.shape
        ds.attrs["is_text"] = not value.is_numeric
        ds.attrs["category"] = value.category
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        if value.raw_values.shape != (0,):
            ds["raw"] = value.raw_values
        if value.converted_values.shape != (0,):
            if not value.is_numeric:
                ds["converted"] = value.converted_values.astype(h5py.string_dtype())
            else:
                ds["converted"] = value.converted_values

    def import_map_curve(self, value: Union[klasses.Curve, klasses.Map, klasses.Cuboid, klasses.Cube4, klasses.Cube5]) -> None:
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
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

    def load(self, name: str) -> xr.DataArray:
        ds = self.db[f"/{name}"]
        ds_attrs = dict(ds.attrs.items())
        category = ds_attrs["category"]
        attrs = {
            "name": name,
            "display_identifier": ds_attrs.get("display_identifier") or "",
            "category": category,
            "comment": ds_attrs.get("commment") or "",
        }
        values = ds["converted"][()]
        if category in ("VALUE", "DEPENDENT_VALUE", "BOOLEAN", "ASCII", "TEXT") or category in ("VAL_BLK", "COM_AXIS"):
            arr = xr.DataArray(values, attrs=attrs)
        else:
            axes = ds["axes"]
            axes_attrs = dict(axes.attrs.items())
            dims = []
            coords = {}
            shape = []
            for idx in range(len(axes)):
                ax = axes[str(idx)]
                ax_attrs = dict(ax.attrs.items())
                ax_items = dict(ax.items())
                ax_name = ax_attrs["name"]
                dims.append(ax_name)
                category = ax_attrs["category"]
                if category == "COM_AXIS":
                    ref_axis = ax_items["reference"]
                    raw_values = np.array(ref_axis["raw"])
                    converted_values = np.array(ref_axis["converted"])
                else:
                    if category not in ("FIX_AXIS", "STD_AXIS"):
                        raise TypeError(f"{category} axis")
                    converted_values = np.array(ax_items["converted"])
                coords[ax_name] = converted_values
                shape.append(converted_values.size)
            if values.shape == (0,):  # TODO: fix while saving!?
                values = np.zeros(tuple(shape))
            arr = xr.DataArray(values, dims=dims, coords=coords, attrs=attrs)
        return arr
