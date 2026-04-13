"""
CURVE_AXIS normalisation and interpolation engine (ASAM MCD-2MC Appendix B).

Provides:
- ``normalize_axis_input``:  pass a raw input through a normalisation curve
  to obtain a floating-point map index  (section B.1.3).
- ``interpolate_normalized``:  N-dimensional map interpolation using
  floating-point indices with clamping  (section B.1.4).
- ``lookup_normalized_map``:  high-level convenience that chains
  normalisation + interpolation for a map characteristic.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Union

import numpy as np

if TYPE_CHECKING:
    from asamint.calibration.api import Calibration

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# B.1.3  Normalisation — input value → floating-point index
# ---------------------------------------------------------------------------


def normalize_axis_input(
    curve_x: np.ndarray,
    curve_y: np.ndarray,
    input_value: float,
) -> float:
    """Map a raw input value through a normalisation curve to a float index.

    Implements ASAM MCD-2MC Appendix B, section B.1.3:

    * input ≤ lowest X  →  Y of lowest X
    * input ≥ highest X →  Y of highest X
    * otherwise         →  linear interpolation between bracketing pairs

    Parameters
    ----------
    curve_x : array-like
        Monotonically non-decreasing X values of the normalisation curve.
    curve_y : array-like
        Corresponding Y (index) values.
    input_value : float
        The raw physical input to normalise.

    Returns
    -------
    float
        A floating-point index suitable for ``interpolate_normalized``.
    """
    x = np.asarray(curve_x, dtype=np.float64)
    y = np.asarray(curve_y, dtype=np.float64)
    return float(np.interp(input_value, x, y))


# ---------------------------------------------------------------------------
# B.1.4  Interpolation — floating-point indices → Z value
# ---------------------------------------------------------------------------


def interpolate_normalized(
    map_values: np.ndarray,
    indices: list[float],
) -> float:
    """N-dimensional map interpolation using floating-point indices.

    Implements ASAM MCD-2MC Appendix B, section B.1.4.  Each dimension
    is handled independently:

    1. Clamp the index to ``[0, size-1]``.
    2. Split into ``lo = floor(idx)`` and ``hi = lo + 1`` (clamped).
    3. Compute the fractional part ``frac = idx - lo``.
    4. Linearly interpolate between the two adjacent slices.

    Dimensions are processed from the **last** to the **first** so that
    the first index corresponds to columns (X) and the second to rows (Y),
    matching the Appendix B convention.

    Parameters
    ----------
    map_values : np.ndarray
        The map's function values.  Shape ``(rows, cols)`` for a 2-D map,
        or higher for CUBOID / CUBE_4 / CUBE_5.
    indices : list[float]
        One floating-point index per dimension, ordered ``[x, y, z, …]``.

    Returns
    -------
    float
        The interpolated Z value.
    """
    values = np.asarray(map_values, dtype=np.float64)

    if len(indices) != values.ndim:
        raise ValueError(f"Expected {values.ndim} indices for a {values.ndim}-D map, got {len(indices)}.")

    # Reverse indices: ASAM axis order [x, y, z, …] → numpy dim order
    # [outermost … rows, cols].  Processing from last dim to first ensures
    # that remaining dimension indices stay valid after each reduction.
    dim_indices = list(reversed(indices))

    for dim in reversed(range(len(dim_indices))):
        idx = dim_indices[dim]
        size = values.shape[dim]

        # Clamp (B.1.4)
        idx = max(0.0, min(idx, size - 1.0))

        lo = int(idx)
        hi = lo + 1
        if hi >= size:
            hi = size - 1
            lo = hi

        frac = idx - lo

        # Build slice objects for lo and hi along this dimension
        slices_lo: list[Union[int, slice]] = [slice(None)] * values.ndim
        slices_hi: list[Union[int, slice]] = [slice(None)] * values.ndim
        slices_lo[dim] = lo
        slices_hi[dim] = hi

        values = values[tuple(slices_lo)] * (1.0 - frac) + values[tuple(slices_hi)] * frac

    return float(values)


# ---------------------------------------------------------------------------
# High-level lookup
# ---------------------------------------------------------------------------


def lookup_normalized_map(
    calibration: "Calibration",
    characteristic_name: str,
    *raw_inputs: float,
) -> float:
    """Look up a value in a map that uses CURVE_AXIS normalisation.

    Chains:
    1. Load the map characteristic and its axes.
    2. For each CURVE_AXIS axis, normalise the corresponding raw input
       through the referenced curve.
    3. For non-CURVE_AXIS axes (STD_AXIS, COM_AXIS, FIX_AXIS), use
       ``numpy.interp`` to convert the raw input to a floating-point index.
    4. Interpolate the map function values using the float indices.

    Parameters
    ----------
    calibration : Calibration
        The calibration instance providing load methods.
    characteristic_name : str
        Name of the MAP / CUBOID / CUBE_4 / CUBE_5 characteristic.
    *raw_inputs : float
        One raw physical input per axis, in axis order (x, y, z, …).

    Returns
    -------
    float
        The interpolated result.

    Raises
    ------
    ValueError
        If the number of inputs doesn't match the number of axes, or
        the characteristic is not a multi-axis type.
    """
    chr_type = calibration.characteristic_category(characteristic_name)
    axes_map = {"CURVE": 1, "MAP": 2, "CUBOID": 3, "CUBE_4": 4, "CUBE_5": 5}
    num_axes = axes_map.get(chr_type)
    if num_axes is None:
        raise ValueError(f"interpolate() requires a CURVE/MAP/CUBOID/CUBE_4/CUBE_5, got {chr_type!r} for {characteristic_name!r}.")

    if len(raw_inputs) != num_axes:
        raise ValueError(f"{characteristic_name!r} has {num_axes} axis/axes, but {len(raw_inputs)} input(s) were given.")

    # Load the characteristic (populates axes and function values)
    obj = calibration.load_curve_or_map(characteristic_name, chr_type, num_axes)

    # Build floating-point indices for each axis
    float_indices: list[float] = []
    for axis_idx, axis in enumerate(obj.axes):
        inp = raw_inputs[axis_idx]

        if axis.category == "CURVE_AXIS" and axis.axis_pts_ref:
            # Normalise through the referenced curve
            ref_curve = calibration.parameter_cache["CURVE"][axis.axis_pts_ref]
            curve_x = np.asarray(ref_curve.axes[0].phys, dtype=np.float64)
            curve_y = np.asarray(ref_curve.phys, dtype=np.float64)
            float_indices.append(normalize_axis_input(curve_x, curve_y, inp))
        else:
            # For STD_AXIS / COM_AXIS / FIX_AXIS: convert raw input to a
            # floating-point index via interpolation against the axis values.
            axis_vals = np.asarray(axis.phys, dtype=np.float64)
            size = len(axis_vals)
            if size < 2:
                float_indices.append(0.0)
            else:
                index_array = np.arange(size, dtype=np.float64)
                float_indices.append(float(np.interp(inp, axis_vals, index_array)))

    return interpolate_normalized(np.asarray(obj.phys), float_indices)
