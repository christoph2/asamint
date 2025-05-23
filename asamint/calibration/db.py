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
            phys = 1 if value.phys == 1.0 else 0
            raw = value.raw
        elif value.category == "TEXT":
            phys = value.phys
            raw = value.raw
        elif value.category == "ASCII":
            phys = value.phys.replace("\x00", " ") if value.phys is not None else ""
            raw = phys
        else:
            phys = value.phys
            raw = value.raw
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        ds.attrs["category"] = value.category
        ds.attrs["unit"] = value.unit if hasattr(value, "unit") and value.unit is not None else ""
        if raw is not None:
            ds["raw"] = raw
        if phys is not None:
            ds["phys"] = phys

    def import_value_block(self, value: klasses.ValueBlock) -> None:
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        # ds.attrs["shape"] = value.phys.shape
        ds.attrs["category"] = value.category
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        if value.raw.shape != (0,):
            ds["raw"] = value.raw
        if value.phys.shape != (0,):
            if not value.is_numeric:
                ds["phys"] = value.phys.astype(h5py.string_dtype())
            else:
                ds["phys"] = value.phys

    def import_axis_pts(self, value: klasses.AxisPts) -> None:
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        # ds.attrs["shape"] = value.phys.shape
        ds.attrs["category"] = value.category
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        if value.raw.shape != (0,):
            ds["raw"] = value.raw
        if value.phys.shape != (0,):
            if not value.is_numeric:
                ds["phys"] = value.phys.astype(h5py.string_dtype())
            else:
                ds["phys"] = value.phys

    def import_map_curve(self, value: Union[klasses.Curve, klasses.Map, klasses.Cuboid, klasses.Cube4, klasses.Cube5]) -> None:
        ds = self.db.create_group(name=f"/{value.name}", track_order=True)
        axes = ds.create_group("axes")
        ds.attrs["category"] = value.category
        ds.attrs["unit"] = value.fnc_unit if value.fnc_unit is not None else ""
        ds.attrs["comment"] = value.comment if value.comment is not None else ""
        ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
        if value.raw is not None:
            ds["raw"] = value.raw
        if value.phys is not None:
            if not value.is_numeric:
                ds["phys"] = value.phys.astype(h5py.string_dtype())
            else:
                ds["phys"] = value.phys
        for idx, axis in enumerate(value.axes):
            ax = axes.create_group(str(idx))
            category = axis.category
            ax.attrs["category"] = category
            ax.attrs["unit"] = axis.unit if axis.unit else ""
            ax.attrs["name"] = axis.name if axis.name else ""
            ax.attrs["input_quantity"] = axis.input_quantity if axis.input_quantity else ""
            match category:
                case "STD_AXIS" | "FIX_AXIS":
                    ax["raw"] = axis.raw
                    if not axis.is_numeric:
                        ax["phys"] = axis.phys.astype(h5py.string_dtype())
                    else:
                        ax["phys"] = axis.phys
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
        values = ds["phys"][()]
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
                    raw = np.array(ref_axis["raw"])
                    phys = np.array(ref_axis["phys"])
                else:
                    if category not in ("FIX_AXIS", "STD_AXIS"):
                        raise TypeError(f"{category} axis")
                    phys = np.array(ax_items["phys"])
                coords[ax_name] = phys
                shape.append(phys.size)
            if values.shape == (0,):  # TODO: fix while saving!?
                values = np.zeros(tuple(shape))
            arr = xr.DataArray(values, dims=dims, coords=coords, attrs=attrs)
        return arr
