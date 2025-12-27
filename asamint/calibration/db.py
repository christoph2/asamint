import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Union

import h5py
import numpy as np
import xarray as xr

from asamint.model.calibration import klasses


class CalibrationDB:
    """HDF5 database for storing calibration data.

    This class provides methods for importing and loading calibration data
    (scalar values, value blocks, axis points, curves, maps, etc.) to/from
    an HDF5 database file.
    """

    def __init__(self, file_name: str, mode: str = "r", logger: Optional[logging.Logger] = None):
        """Initialize the calibration database.

        Args:
            file_name: Path to the database file (will be given .h5 extension if not present)
            mode: File opening mode ('r', 'w', 'a', 'r+')
            logger: Optional logger for recording operations
        """
        self.opened = False
        self.logger = logger or logging.getLogger(__name__)
        db_name = Path(file_name).with_suffix(".h5")
        self.logger.info(f"Opening database {str(db_name)!r} in mode {mode!r}")

        self.db = h5py.File(db_name, mode=mode, libver="latest", locking="best-effort", track_order=True)

        self.opened = True
        self.guid = uuid.uuid4()

    def __del__(self) -> None:
        """Destructor that ensures the database is closed."""
        self.close()

    def close(self) -> None:
        """Close the database if it's open."""
        if self.opened:
            self.db.close()
            self.opened = False
            self.logger.debug("Database closed")

    def import_scalar_value(self, value: klasses.Value) -> None:
        """Import a scalar value into the database.

        Args:
            value: The scalar value to import

        Note:
            Different categories of values (BOOLEAN, TEXT, ASCII) are handled differently.
            For BOOLEAN values, the physical value is converted to 0 or 1.
            For ASCII values, null characters are replaced with spaces.
        """
        try:
            # Process value based on its category
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

            # Create a group for the value
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)

            # Set attributes
            ds.attrs["comment"] = value.comment if value.comment is not None else ""
            ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""
            ds.attrs["category"] = value.category
            ds.attrs["unit"] = value.unit if hasattr(value, "unit") and value.unit is not None else ""

            # Store raw and physical values
            if raw is not None:
                ds["raw"] = raw
            if phys is not None:
                ds["phys"] = phys

            self.logger.debug(f"Imported scalar value: {value.name}")
        except Exception as e:
            self.logger.error(f"Error importing scalar value {value.name}: {e}")
            raise

    def import_value_block(self, value: klasses.ValueBlock) -> None:
        """Import a value block (array of values) into the database.

        Args:
            value: The value block to import

        Note:
            Non-numeric values are stored as strings using h5py.string_dtype().
            Empty arrays (shape == (0,)) are not stored.
        """
        try:
            # Create a group for the value block
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)

            # Set attributes
            ds.attrs["category"] = value.category
            ds.attrs["comment"] = value.comment if value.comment is not None else ""
            ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""

            # Store raw values if not empty
            if value.raw.shape != (0,):
                ds["raw"] = value.raw

            # Store physical values if not empty
            if value.phys.shape != (0,):
                if not value.is_numeric:
                    ds["phys"] = value.phys.astype(h5py.string_dtype())
                else:
                    ds["phys"] = value.phys

            self.logger.debug(f"Imported value block: {value.name}")
        except Exception as e:
            self.logger.error(f"Error importing value block {value.name}: {e}")
            raise

    def import_axis_pts(self, value: klasses.AxisPts) -> None:
        """Import axis points into the database.

        Args:
            value: The axis points to import

        Note:
            Non-numeric values are stored as strings using h5py.string_dtype().
            Empty arrays (shape == (0,)) are not stored.
        """
        try:
            # Create a group for the axis points
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)

            # Set attributes
            ds.attrs["category"] = value.category
            ds.attrs["comment"] = value.comment if value.comment is not None else ""
            ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""

            # Store raw values if not empty
            if value.raw.shape != (0,):
                ds["raw"] = value.raw

            # Store physical values if not empty
            if value.phys.shape != (0,):
                if not value.is_numeric:
                    ds["phys"] = value.phys.astype(h5py.string_dtype())
                else:
                    ds["phys"] = value.phys

            self.logger.debug(f"Imported axis points: {value.name}")
        except Exception as e:
            self.logger.error(f"Error importing axis points {value.name}: {e}")
            raise

    def import_map_curve(self, value: Union[klasses.Curve, klasses.Map, klasses.Cuboid, klasses.Cube4, klasses.Cube5]) -> None:
        """Import a map or curve into the database.

        Args:
            value: The map or curve to import (can be Curve, Map, Cuboid, Cube4, or Cube5)

        Note:
            This method handles different types of axes (STD_AXIS, FIX_AXIS, COM_AXIS, etc.)
            and creates appropriate links for referenced axes.
        """
        try:
            # Create a group for the map/curve
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)
            axes = ds.create_group("axes")

            # Set attributes
            ds.attrs["category"] = value.category
            ds.attrs["unit"] = value.fnc_unit if value.fnc_unit is not None else ""
            ds.attrs["comment"] = value.comment if value.comment is not None else ""
            ds.attrs["display_identifier"] = value.displayIdentifier if value.displayIdentifier is not None else ""

            # Store raw values if not None
            if value.raw is not None:
                ds["raw"] = value.raw

            # Store physical values if not None
            if value.phys is not None:
                if not value.is_numeric:
                    ds["phys"] = value.phys.astype(h5py.string_dtype())
                else:
                    ds["phys"] = value.phys

            # Process each axis
            for idx, axis in enumerate(value.axes):
                ax = axes.create_group(str(idx))
                category = axis.category

                # Set axis attributes
                ax.attrs["category"] = category
                ax.attrs["unit"] = axis.unit if axis.unit else ""
                ax.attrs["name"] = axis.name if axis.name else ""
                ax.attrs["input_quantity"] = axis.input_quantity if axis.input_quantity else ""

                # Handle different axis types
                match category:
                    case "STD_AXIS" | "FIX_AXIS":
                        # Standard or fixed axis: store raw and physical values
                        ax["raw"] = axis.raw
                        if not axis.is_numeric:
                            ax["phys"] = axis.phys.astype(h5py.string_dtype())
                        else:
                            ax["phys"] = axis.phys
                    case "COM_AXIS" | "RES_AXIS" | "CURVE_AXIS":
                        # Referenced axis: create a soft link to the referenced axis
                        ax["reference"] = h5py.SoftLink(f"/{axis.axis_pts_ref}")

            self.logger.debug(f"Imported {value.category.lower()}: {value.name}")
        except Exception as e:
            self.logger.error(f"Error importing {value.category.lower()} {value.name}: {e}")
            raise

    def load(self, name: str) -> xr.DataArray:
        """Load a calibration parameter from the database.

        Args:
            name: Name of the parameter to load

        Returns:
            An xarray DataArray containing the parameter data and metadata

        Raises:
            KeyError: If the parameter is not found in the database
            TypeError: If an unsupported axis category is encountered
        """
        try:
            # Get the dataset and its attributes
            ds = self.db[f"/{name}"]
            ds_attrs = dict(ds.attrs.items())
            category = ds_attrs["category"]

            # Create attributes dictionary
            attrs = {
                "name": name,
                "display_identifier": ds_attrs.get("display_identifier") or "",
                "category": category,
                "comment": ds_attrs.get("comment") or "",  # Fixed: was "commment"
            }

            # Get physical values
            values = ds["phys"][()]

            # Handle scalar values and value blocks
            if category in ("VALUE", "DEPENDENT_VALUE", "BOOLEAN", "ASCII", "TEXT") or category in ("VAL_BLK", "COM_AXIS"):
                arr = xr.DataArray(values, attrs=attrs)
            else:
                # Handle maps and curves with axes
                axes = ds["axes"]
                dims = []
                coords = {}
                shape = []

                # Process each axis
                # Note: HDF5 stores data in C-order (last dimension varies fastest).
                # For a 2D map (x, y), HDF5 shape is (len(x), len(y)) if x is first axis and y is second axis.
                # However, many tools export (y, x) shape for (x, y) maps.
                # We need to ensure dims and shape are consistent.
                for idx in range(len(axes)):
                    ax = axes[str(idx)]
                    ax_attrs = dict(ax.attrs.items())
                    ax_name = ax_attrs["name"]
                    dims.append(ax_name)
                    ax_category = ax_attrs["category"]

                    # Handle different axis types
                    if ax_category == "COM_AXIS":
                        # Referenced axis
                        ref_axis = ax["reference"]
                        phys = np.array(ref_axis["phys"])
                    else:
                        # Standard or fixed axis
                        if ax_category not in ("FIX_AXIS", "STD_AXIS"):
                            raise TypeError(f"Unsupported axis category: {ax_category}")
                        phys = np.array(ax["phys"])

                    # Store coordinates and shape
                    coords[ax_name] = ([ax_name], phys)
                    shape.append(phys.size)

                # Handle empty values array or shape mismatch
                if values.shape == (0,) or values.size == 0:
                    values = np.zeros(tuple(shape))
                elif values.shape != tuple(shape):
                    # If there's a mismatch, we try to reshape if possible.
                    # This often happens if the metadata dimensions don't match the actual HDF5 data size.
                    # Or if the dimension order is reversed (e.g. (y, x) instead of (x, y)).
                    if values.size == np.prod(shape):
                        try:
                            values = values.reshape(tuple(shape))
                            # self.logger.warning(f"Reshaped {name} from {values.shape} to {tuple(shape)}")
                        except ValueError:
                            self.logger.error(f"Cannot reshape {name} from {values.shape} to {tuple(shape)}")
                            values = np.zeros(tuple(shape))
                    else:
                        self.logger.error(f"Size mismatch for {name}: {values.size} != {np.prod(shape)}. Using zero-filled array.")
                        values = np.zeros(tuple(shape))

                # Create DataArray with dimensions and coordinates
                try:
                    arr = xr.DataArray(
                        data=values,
                        dims=dims,
                        coords=coords,
                        attrs=attrs,
                        name=name
                    )
                except ValueError as e:
                    self.logger.error(f"Failed to create DataArray for {name}: {e}. Falling back to zero-filled array.")
                    values = np.zeros(tuple(shape))
                    arr = xr.DataArray(
                        data=values,
                        dims=dims,
                        coords=coords,
                        attrs=attrs,
                        name=name
                    )

            self.logger.debug(f"Loaded {category.lower()}: {name}")
            return arr

        except KeyError as e:
            self.logger.error(f"Parameter not found: {name}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading parameter {name}: {e}")
            raise
