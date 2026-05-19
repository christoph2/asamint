"""HDF5-backed calibration parameter database.

Provides :class:`CalibrationDB` for importing and loading calibration
parameters (scalars, value blocks, axis points, curves, maps, cubes)
to and from an HDF5 file via *h5py*.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from types import TracebackType
from typing import Any

import h5py
import numpy as np
import xarray as xr

from asamint.core.exceptions import CalibrationError
from asamint.model.calibration import klasses

#: Categories that are stored without axis sub-groups.
_SCALAR_LIKE_CATEGORIES: frozenset[str] = frozenset(
    {
        "VALUE",
        "DEPENDENT_VALUE",
        "BOOLEAN",
        "ASCII",
        "TEXT",
        "VAL_BLK",
        "COM_AXIS",
        "AXIS_PTS",
    }
)

#: Union of all multi-dimensional calibration object types.
_NDimValue = klasses.Curve | klasses.Map | klasses.Cuboid | klasses.Cube4 | klasses.Cube5


class CalibrationDB:
    """HDF5 database for storing and retrieving calibration data.

    Supports the context-manager protocol::

        with CalibrationDB("my_cal", mode="w") as db:
            db.import_scalar_value(value)

    Args:
        file_name: Path to the database file (``.h5`` suffix is appended
            automatically if missing).
        mode: HDF5 file-open mode (``"r"``, ``"w"``, ``"a"``, ``"r+"``).
        logger: Optional logger; falls back to a module-level logger.
    """

    def __init__(self, file_name: str, mode: str = "r", logger: Optional[logging.Logger] = None) -> None:
        self.opened: bool = False
        self.logger: logging.Logger = logger or logging.getLogger(__name__)
        db_path = Path(file_name).with_suffix(".h5")
        self.logger.info("Opening database %r in mode %r", str(db_path), mode)

        self.db: h5py.File = h5py.File(
            db_path,
            mode=mode,
            libver="latest",
            locking="best-effort",
            track_order=True,
        )

        self.opened = True
        self.guid: uuid.UUID = uuid.uuid4()

    # -- Context-manager protocol ------------------------------------------

    def __enter__(self) -> CalibrationDB:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        """Close the HDF5 file if still open."""
        if self.opened:
            self.db.close()
            self.opened = False
            self.logger.debug("Database closed")

    # -- Common helpers ----------------------------------------------------

    @staticmethod
    def _set_common_attrs(
        group: h5py.Group,
        value: klasses.CalibratedObject,
        *,
        include_unit: bool = False,
        unit_field: str = "unit",
    ) -> None:
        """Write standard HDF5 attributes shared by all parameter types.

        Args:
            group: Target HDF5 group.
            value: Calibration data object providing attribute values.
            include_unit: Whether to write a ``unit`` attribute.
            unit_field: Name of the attribute on *value* that carries the
                unit string (``"unit"`` or ``"fnc_unit"``).
        """
        group.attrs["category"] = value.category
        group.attrs["comment"] = value.comment or ""
        group.attrs["display_identifier"] = value.displayIdentifier or ""
        if include_unit:
            raw_unit = getattr(value, unit_field, None)
            group.attrs["unit"] = raw_unit if raw_unit is not None else ""

    @staticmethod
    def _store_array(
        group: h5py.Group,
        key: str,
        array: np.ndarray,
        *,
        is_numeric: bool = True,
    ) -> None:
        """Store a numpy array in the HDF5 group.

        Non-numeric arrays are stored as variable-length strings.

        Args:
            group: Target HDF5 group.
            key: Dataset name inside the group.
            array: Data to write.
            is_numeric: ``False`` when the array holds text values.
        """
        if not is_numeric:
            group[key] = array.astype(h5py.string_dtype())
        else:
            group[key] = array

    # -- Import methods ----------------------------------------------------

    def import_scalar_value(self, value: klasses.Value) -> None:
        """Import a scalar calibration value.

        Args:
            value: Scalar value to import.

        Raises:
            CalibrationError: On serialisation or I/O failure.
        """
        try:
            match value.category:
                case "BOOLEAN":
                    phys: Any = 1 if value.phys == 1.0 else 0
                    raw: Any = value.raw
                case "TEXT":
                    phys = value.phys
                    raw = value.raw
                case "ASCII":
                    phys = value.phys.replace("\x00", " ") if value.phys is not None else ""
                    raw = phys
                case _:
                    phys = value.phys
                    raw = value.raw

            ds = self.db.create_group(name=f"/{value.name}", track_order=True)
            self._set_common_attrs(ds, value, include_unit=True)

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

            self.logger.debug("Imported scalar value: %s", value.name)
        except (TypeError, ValueError, OSError) as exc:
            raise CalibrationError(f"Error importing scalar value {value.name!r}: {exc}") from exc

    def import_value_block(self, value: klasses.ValueBlock) -> None:
        """Import a value block (n-dimensional array).

        Args:
            value: Value block to import.

        Raises:
            CalibrationError: On serialisation or I/O failure.
        """
        try:
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)
            self._set_common_attrs(ds, value)

            if value.raw.shape != (0,):
                ds["raw"] = value.raw
            if value.phys.shape != (0,):
                self._store_array(ds, "phys", value.phys, is_numeric=bool(value.is_numeric))

            self.logger.debug("Imported value block: %s", value.name)
        except (TypeError, ValueError, OSError) as exc:
            raise CalibrationError(f"Error importing value block {value.name!r}: {exc}") from exc

    def import_axis_pts(self, value: klasses.AxisPts) -> None:
        """Import axis-points data.

        The HDF5 group is always tagged with ``category="AXIS_PTS"`` so
        that :meth:`_validate_axis_reference` can locate it, regardless
        of the internal axis category (COM_AXIS, RES_AXIS, …) stored in
        the ``axis_category`` attribute.

        Args:
            value: Axis-points object to import.

        Raises:
            CalibrationError: On serialisation or I/O failure.
        """
        try:
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)
            self._set_common_attrs(ds, value)
            # Override the category to the container-level type so that
            # COM_AXIS/RES_AXIS soft-links can find this entry.
            ds.attrs["axis_category"] = value.category
            ds.attrs["category"] = "AXIS_PTS"

            if value.raw.shape != (0,):
                ds["raw"] = value.raw
            if value.phys.shape != (0,):
                self._store_array(ds, "phys", value.phys, is_numeric=bool(value.is_numeric))

            self.logger.debug("Imported axis points: %s", value.name)
        except (TypeError, ValueError, OSError) as exc:
            raise CalibrationError(f"Error importing axis points {value.name!r}: {exc}") from exc

    def import_map_curve(self, value: _NDimValue) -> None:
        """Import a curve, map, cuboid, or higher-dimensional cube.

        Handles all axis categories:

        * **STD_AXIS / FIX_AXIS** – values stored inline.
        * **COM_AXIS / RES_AXIS** – stored as soft-link to an AXIS_PTS entry.
        * **CURVE_AXIS** – soft-link when ``axis_pts_ref`` exists, inline
          otherwise.

        Args:
            value: Multi-dimensional calibration object to import.

        Raises:
            CalibrationError: On serialisation or I/O failure.
        """
        try:
            ds = self.db.create_group(name=f"/{value.name}", track_order=True)
            axes_grp = ds.create_group("axes")

            self._set_common_attrs(ds, value, include_unit=True, unit_field="fnc_unit")

            if value.raw is not None:
                ds["raw"] = value.raw
            if value.phys is not None:
                self._store_array(ds, "phys", value.phys, is_numeric=bool(value.is_numeric))

            for idx, axis in enumerate(value.axes):
                self._import_axis(ds, axes_grp, idx, axis, value.name)

            self.logger.debug("Imported %s: %s", value.category.lower(), value.name)
        except (TypeError, ValueError, OSError) as exc:
            raise CalibrationError(f"Error importing {value.category.lower()} {value.name!r}: {exc}") from exc

    def _import_axis(
        self,
        parent: h5py.Group,
        axes_grp: h5py.Group,
        idx: int,
        axis: klasses.AxisContainer,
        value_name: str,
    ) -> None:
        """Import a single axis into the axes sub-group.

        Args:
            parent: Parent characteristic group (for diagnostic messages).
            axes_grp: ``axes`` HDF5 group.
            idx: Zero-based axis index.
            axis: Axis data container.
            value_name: Owning characteristic name (for error messages).
        """
        ax = axes_grp.create_group(str(idx))
        ax.attrs["category"] = axis.category
        ax.attrs["unit"] = axis.unit or ""
        ax.attrs["name"] = axis.name or ""
        ax.attrs["input_quantity"] = axis.input_quantity or ""

        match axis.category:
            case "STD_AXIS" | "FIX_AXIS":
                self._store_inline_axis(ax, axis)
            case "COM_AXIS" | "RES_AXIS":
                ref_path = self._validate_axis_reference(value_name, axis.category, axis.axis_pts_ref)
                ax["reference"] = h5py.SoftLink(ref_path)
            case "CURVE_AXIS":
                if axis.axis_pts_ref:
                    ref_path = self._validate_axis_reference(value_name, axis.category, axis.axis_pts_ref)
                    ax["reference"] = h5py.SoftLink(ref_path)
                else:
                    self._store_inline_axis(ax, axis)
            case _ as unknown:
                self.logger.warning(
                    "%s: unknown axis category %r for axis %d – stored inline",
                    value_name,
                    unknown,
                    idx,
                )
                self._store_inline_axis(ax, axis)

    @staticmethod
    def _store_inline_axis(ax: h5py.Group, axis: klasses.AxisContainer) -> None:
        """Write raw/phys arrays directly into the axis group.

        Args:
            ax: HDF5 axis group.
            axis: Source axis container.
        """
        axis_raw = np.asarray(axis.raw)
        axis_phys = np.asarray(axis.phys)
        ax["raw"] = axis_raw
        if not axis.is_numeric:
            ax["phys"] = axis_phys.astype(h5py.string_dtype())
        else:
            ax["phys"] = axis_phys

    def _validate_axis_reference(
        self,
        value_name: str,
        axis_category: str,
        axis_pts_ref: str | None,
    ) -> str:
        """Verify that a referenced AXIS_PTS entry exists in the database.

        Args:
            value_name: Owning characteristic name.
            axis_category: Axis category requesting the reference.
            axis_pts_ref: Short-name of the referenced AXIS_PTS.

        Returns:
            Absolute HDF5 path to the referenced group.

        Raises:
            CalibrationError: If the reference is missing or invalid.
        """
        if not axis_pts_ref:
            raise CalibrationError(f"{value_name}: {axis_category} axis requires a non-empty axis_pts_ref")
        reference_path = f"/{axis_pts_ref}"
        try:
            referenced = self.db[reference_path]
        except KeyError as exc:
            raise CalibrationError(f"{value_name}: {axis_category} references missing AXIS_PTS {axis_pts_ref!r}") from exc
        if referenced.attrs.get("category") != "AXIS_PTS":
            raise CalibrationError(f"{value_name}: {axis_category} reference {axis_pts_ref!r} is not an AXIS_PTS entry")
        return reference_path

    # -- Load methods ------------------------------------------------------

    def load(self, name: str) -> xr.DataArray:
        """Load a calibration parameter as an :class:`xarray.DataArray`.

        The returned array carries coordinates for multi-dimensional
        parameters and metadata attributes (category, display_identifier,
        comment).

        Args:
            name: Short-name of the calibration parameter.

        Returns:
            DataArray with values, coordinates (if applicable), and metadata.

        Raises:
            KeyError: If the parameter is not found.
            CalibrationError: On data or shape inconsistencies.
        """
        try:
            ds = self.db[f"/{name}"]
            ds_attrs = dict(ds.attrs.items())
            category: str = ds_attrs["category"]
            attrs = self._build_load_attrs(name, ds_attrs, category)
            values: np.ndarray = ds["phys"][()]

            if category in _SCALAR_LIKE_CATEGORIES:
                result = xr.DataArray(values, attrs=attrs)
            else:
                dims, coords, shape = self._load_axis_metadata(ds["axes"])
                values = self._normalize_array_values(name, values, shape)
                result = self._build_data_array(name, values, dims, coords, attrs, shape)

            self.logger.debug("Loaded %s: %s", category.lower(), name)
            return result

        except KeyError:
            self.logger.error("Parameter not found: %s", name)
            raise
        except (TypeError, ValueError, OSError) as exc:
            self.logger.error("Error loading parameter %s: %s", name, exc)
            raise

    # -- Load helpers (private) --------------------------------------------

    @staticmethod
    def _build_load_attrs(
        name: str,
        ds_attrs: dict[str, Any],
        category: str,
    ) -> dict[str, str]:
        """Build the metadata dict attached to the returned DataArray."""
        return {
            "name": name,
            "display_identifier": ds_attrs.get("display_identifier") or "",
            "category": category,
            "comment": ds_attrs.get("comment") or "",
        }

    def _read_axis_values(
        self,
        axis_group: h5py.Group,
        axis_category: str,
    ) -> np.ndarray:
        """Read physical axis values from an axis sub-group.

        Dispatches to soft-link resolution for COM_AXIS / RES_AXIS /
        CURVE_AXIS (when stored as reference), or reads inline ``phys``
        for STD_AXIS / FIX_AXIS / CURVE_AXIS (when stored inline).

        Args:
            axis_group: HDF5 group representing a single axis.
            axis_category: Category string from the axis attributes.

        Returns:
            One-dimensional numpy array of physical axis values.

        Raises:
            TypeError: For unsupported axis categories.
            KeyError: For broken soft-link references.
        """
        if axis_category in ("COM_AXIS", "RES_AXIS", "CURVE_AXIS"):
            # CURVE_AXIS may be stored inline (no soft-link) when axis_pts_ref was absent.
            if "reference" in axis_group:
                return self._read_referenced_axis_values(axis_group, axis_category)
            if "phys" in axis_group:
                return np.array(axis_group["phys"])
            raise KeyError(f"{axis_category} axis {axis_group.name!r} has neither 'reference' nor 'phys'")
        if axis_category in ("FIX_AXIS", "STD_AXIS"):
            return np.array(axis_group["phys"])
        raise TypeError(f"Unsupported axis category: {axis_category!r}")

    @staticmethod
    def _read_referenced_axis_values(
        axis_group: h5py.Group,
        axis_category: str,
    ) -> np.ndarray:
        """Follow a soft-link and return the referenced phys array.

        Args:
            axis_group: HDF5 axis group containing a ``reference`` soft-link.
            axis_category: Category string (for error messages).

        Returns:
            Numpy array of physical values from the referenced AXIS_PTS.

        Raises:
            KeyError: If the soft-link target is missing or lacks ``phys``.
        """
        reference_link = axis_group.get("reference", getlink=True)
        if not isinstance(reference_link, h5py.SoftLink):
            raise KeyError(f"{axis_category} axis {axis_group.name!r} is missing a soft-link reference")
        reference_path: str = reference_link.path
        try:
            referenced = axis_group.file[reference_path]
        except KeyError as exc:
            raise KeyError(f"Broken {axis_category} reference {reference_path!r} for axis {axis_group.name!r}") from exc
        try:
            return np.array(referenced["phys"])
        except KeyError as exc:
            raise KeyError(f"Referenced axis {reference_path!r} does not provide 'phys' values") from exc

    def _load_axis_metadata(
        self,
        axes: h5py.Group,
    ) -> tuple[list[str], dict[str, Any], list[int]]:
        """Extract dimension names, coordinates, and shape from axes group.

        Args:
            axes: HDF5 group containing numbered axis sub-groups.

        Returns:
            Tuple of ``(dims, coords, shape)``.
        """
        dims: list[str] = []
        coords: dict[str, Any] = {}
        shape: list[int] = []
        for idx in range(len(axes)):
            axis_group = axes[str(idx)]
            axis_attrs = dict(axis_group.attrs.items())
            axis_name: str = axis_attrs["name"]
            axis_values = self._read_axis_values(axis_group, axis_attrs["category"])
            dims.append(axis_name)
            coords[axis_name] = ([axis_name], axis_values)
            shape.append(axis_values.size)
        return dims, coords, shape

    def _normalize_array_values(
        self,
        name: str,
        values: np.ndarray,
        shape: list[int],
    ) -> np.ndarray:
        """Reshape or zero-fill *values* to match the expected *shape*.

        Args:
            name: Parameter name (for log messages).
            values: Raw value array from HDF5.
            shape: Expected shape derived from axis metadata.

        Returns:
            Array with exactly ``tuple(shape)`` dimensions.
        """
        target_shape = tuple(shape)
        if values.shape == (0,) or values.size == 0:
            return np.zeros(target_shape)
        if values.shape == target_shape:
            return values
        if values.size == np.prod(shape):
            try:
                return values.reshape(target_shape)
            except ValueError:
                self.logger.error("Cannot reshape %s from %s to %s", name, values.shape, target_shape)
                return np.zeros(target_shape)
        self.logger.error(
            "Size mismatch for %s: %d != %d – using zero-filled array",
            name,
            values.size,
            int(np.prod(shape)),
        )
        return np.zeros(target_shape)

    def _build_data_array(
        self,
        name: str,
        values: np.ndarray,
        dims: list[str],
        coords: dict[str, Any],
        attrs: dict[str, str],
        shape: list[int],
    ) -> xr.DataArray:
        """Construct an :class:`xarray.DataArray` with fallback on shape errors.

        Args:
            name: Parameter short-name.
            values: N-dimensional value array.
            dims: Dimension names.
            coords: Coordinate mapping.
            attrs: Metadata attributes.
            shape: Expected shape (used for zero-fill fallback).

        Returns:
            Fully constructed DataArray.
        """
        try:
            return xr.DataArray(data=values, dims=dims, coords=coords, attrs=attrs, name=name)
        except ValueError as exc:
            self.logger.error(
                "Failed to create DataArray for %s: %s – falling back to zero-filled array",
                name,
                exc,
            )
            zero_values = np.zeros(tuple(shape))
            return xr.DataArray(data=zero_values, dims=dims, coords=coords, attrs=attrs, name=name)
