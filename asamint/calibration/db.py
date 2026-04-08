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

    def __init__(
        self, file_name: str, mode: str = "r", logger: Optional[logging.Logger] = None
    ) -> None:
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

        self.db = h5py.File(
            db_name, mode=mode, libver="latest", locking="best-effort", track_order=True
        )

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
            ds.attrs["display_identifier"] = (
                value.displayIdentifier if value.displayIdentifier is not None else ""
            )
            ds.attrs["category"] = value.category
            ds.attrs["unit"] = (
                value.unit if hasattr(value, "unit") and value.unit is not None else ""
            )

            # Store raw and physical values
            if raw is not None:
                ds["raw"] = raw
            if phys is not None:
                ds["phys"] = phys

            self.logger.debug(f"Imported scalar value: {value.name}")
        except (TypeError, ValueError, OSError) as e:
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
            ds.attrs["display_identifier"] = (
                value.displayIdentifier if value.displayIdentifier is not None else ""
            )

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
        except (TypeError, ValueError, OSError) as e:
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
            ds.attrs["display_identifier"] = (
                value.displayIdentifier if value.displayIdentifier is not None else ""
            )

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
        except (TypeError, ValueError, OSError) as e:
            self.logger.error(f"Error importing axis points {value.name}: {e}")
            raise

    def import_map_curve(
        self,
        value: Union[
            klasses.Curve, klasses.Map, klasses.Cuboid, klasses.Cube4, klasses.Cube5
        ],
    ) -> None:
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
            ds.attrs["display_identifier"] = (
                value.displayIdentifier if value.displayIdentifier is not None else ""
            )

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
                ax.attrs["input_quantity"] = (
                    axis.input_quantity if axis.input_quantity else ""
                )

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
                        reference_path = self._validate_axis_reference(
                            value.name, category, axis.axis_pts_ref
                        )
                        ax["reference"] = h5py.SoftLink(reference_path)

            self.logger.debug(f"Imported {value.category.lower()}: {value.name}")
        except (TypeError, ValueError, OSError) as e:
            self.logger.error(
                f"Error importing {value.category.lower()} {value.name}: {e}"
            )
            raise

    def _validate_axis_reference(
        self, value_name: str, axis_category: str, axis_pts_ref: str | None
    ) -> str:
        if not axis_pts_ref:
            raise ValueError(
                f"{value_name}: {axis_category} axis requires a non-empty axis_pts_ref"
            )
        reference_path = f"/{axis_pts_ref}"
        try:
            referenced_axis = self.db[reference_path]
        except KeyError as exc:
            raise ValueError(
                f"{value_name}: {axis_category} references missing AXIS_PTS {axis_pts_ref!r}"
            ) from exc
        if referenced_axis.attrs.get("category") != "AXIS_PTS":
            raise ValueError(
                f"{value_name}: {axis_category} reference {axis_pts_ref!r} is not an AXIS_PTS entry"
            )
        return reference_path

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
            ds = self.db[f"/{name}"]
            ds_attrs = dict(ds.attrs.items())
            category = ds_attrs["category"]
            attrs = self._create_data_array_attrs(name, ds_attrs, category)
            values = ds["phys"][()]
            if self._is_scalar_like_category(category):
                arr = xr.DataArray(values, attrs=attrs)
            else:
                dims, coords, shape = self._load_axis_metadata(ds["axes"])
                values = self._normalize_array_values(name, values, shape)
                arr = self._create_data_array(name, values, dims, coords, attrs, shape)

            self.logger.debug(f"Loaded {category.lower()}: {name}")
            return arr

        except KeyError:
            self.logger.error(f"Parameter not found: {name}")
            raise
        except (TypeError, ValueError, OSError) as e:
            self.logger.error(f"Error loading parameter {name}: {e}")
            raise

    @staticmethod
    def _is_scalar_like_category(category: str) -> bool:
        return category in (
            "VALUE",
            "DEPENDENT_VALUE",
            "BOOLEAN",
            "ASCII",
            "TEXT",
            "VAL_BLK",
            "COM_AXIS",
        )

    @staticmethod
    def _create_data_array_attrs(
        name: str, ds_attrs: dict[str, Any], category: str
    ) -> dict[str, Any]:
        return {
            "name": name,
            "display_identifier": ds_attrs.get("display_identifier") or "",
            "category": category,
            "comment": ds_attrs.get("comment") or "",
        }

    def _read_axis_values(
        self, axis_group: h5py.Group, axis_category: str
    ) -> np.ndarray:
        if axis_category in ("COM_AXIS", "RES_AXIS", "CURVE_AXIS"):
            return self._read_referenced_axis_values(axis_group, axis_category)
        if axis_category not in ("FIX_AXIS", "STD_AXIS"):
            raise TypeError(f"Unsupported axis category: {axis_category}")
        return np.array(axis_group["phys"])

    @staticmethod
    def _read_referenced_axis_values(
        axis_group: h5py.Group, axis_category: str
    ) -> np.ndarray:
        reference_link = axis_group.get("reference", getlink=True)
        if not isinstance(reference_link, h5py.SoftLink):
            raise KeyError(
                f"{axis_category} axis {axis_group.name!r} is missing a soft-link reference"
            )
        reference_path = reference_link.path
        try:
            referenced_axis = axis_group.file[reference_path]
        except KeyError as exc:
            raise KeyError(
                f"Broken {axis_category} reference {reference_path!r} for axis {axis_group.name!r}"
            ) from exc
        try:
            return np.array(referenced_axis["phys"])
        except KeyError as exc:
            raise KeyError(
                f"Referenced axis {reference_path!r} does not provide 'phys' values"
            ) from exc

    def _load_axis_metadata(
        self, axes: h5py.Group
    ) -> tuple[list[str], dict[str, Any], list[int]]:
        dims: list[str] = []
        coords: dict[str, Any] = {}
        shape: list[int] = []
        for idx in range(len(axes)):
            axis_group = axes[str(idx)]
            axis_attrs = dict(axis_group.attrs.items())
            axis_name = axis_attrs["name"]
            axis_values = self._read_axis_values(axis_group, axis_attrs["category"])
            dims.append(axis_name)
            coords[axis_name] = ([axis_name], axis_values)
            shape.append(axis_values.size)
        return dims, coords, shape

    def _normalize_array_values(
        self, name: str, values: np.ndarray, shape: list[int]
    ) -> np.ndarray:
        target_shape = tuple(shape)
        if values.shape == (0,) or values.size == 0:
            return np.zeros(target_shape)
        if values.shape == target_shape:
            return values
        if values.size == np.prod(shape):
            try:
                return values.reshape(target_shape)
            except ValueError:
                self.logger.error(
                    f"Cannot reshape {name} from {values.shape} to {target_shape}"
                )
                return np.zeros(target_shape)
        self.logger.error(
            f"Size mismatch for {name}: {values.size} != {np.prod(shape)}. Using zero-filled array."
        )
        return np.zeros(target_shape)

    def _create_data_array(
        self,
        name: str,
        values: np.ndarray,
        dims: list[str],
        coords: dict[str, Any],
        attrs: dict[str, Any],
        shape: list[int],
    ) -> xr.DataArray:
        try:
            return xr.DataArray(
                data=values, dims=dims, coords=coords, attrs=attrs, name=name
            )
        except ValueError as e:
            self.logger.error(
                f"Failed to create DataArray for {name}: {e}. Falling back to zero-filled array."
            )
            zero_values = np.zeros(tuple(shape))
            return xr.DataArray(
                data=zero_values, dims=dims, coords=coords, attrs=attrs, name=name
            )
