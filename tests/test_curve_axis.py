"""Tests for CURVE_AXIS normalisation and interpolation (ASAM Appendix B)."""

from __future__ import annotations

import numpy as np
import pytest

from asamint.calibration.curve_axis import (
    interpolate_normalized,
    normalize_axis_input,
)


# ---------------------------------------------------------------------------
# Appendix B example data
# ---------------------------------------------------------------------------

# X_NORM curve (5 pairs)
X_NORM_X = np.array([0.0, 200.0, 400.0, 1000.0, 5700.0])
X_NORM_Y = np.array([2.0, 2.7, 3.0, 4.2, 4.9])

# Y_NORM curve (4 pairs)
Y_NORM_X = np.array([0.0, 50.0, 70.0, 100.0])
Y_NORM_Y = np.array([0.5, 1.0, 2.4, 4.2])

# Z_MAP (6 rows × 7 columns)
Z_MAP = np.array(
    [
        [3.4, 4.5, 2.1, 5.4, 1.2, 3.4, 4.4],
        [2.3, 1.2, 1.2, 5.6, 3.2, 2.1, 7.8],
        [3.2, 1.5, 3.2, 2.2, 1.6, 1.7, 1.7],
        [2.1, 0.4, 1.1, 1.5, 1.8, 3.2, 1.5],
        [1.1, 4.3, 2.1, 4.6, 1.2, 1.4, 3.2],
        [1.2, 5.3, 3.2, 3.5, 2.1, 1.4, 4.2],
    ]
)


# ---------------------------------------------------------------------------
# Tests: normalize_axis_input  (B.1.3)
# ---------------------------------------------------------------------------


class TestNormalizeAxisInput:
    """Section B.1.3 — determining the map indices."""

    def test_appendix_b_x_norm(self):
        """Input 850.0 through X_NORM → 3.9."""
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, 850.0)
        assert result == pytest.approx(3.9, abs=1e-9)

    def test_appendix_b_y_norm(self):
        """Input 60.0 through Y_NORM → 1.7."""
        result = normalize_axis_input(Y_NORM_X, Y_NORM_Y, 60.0)
        assert result == pytest.approx(1.7, abs=1e-9)

    def test_below_lowest_x(self):
        """Input below lowest X → Y of lowest X (clamping)."""
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, -100.0)
        assert result == pytest.approx(2.0, abs=1e-9)

    def test_above_highest_x(self):
        """Input above highest X → Y of highest X (clamping)."""
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, 10000.0)
        assert result == pytest.approx(4.9, abs=1e-9)

    def test_exact_match(self):
        """Input exactly at a curve X value → corresponding Y."""
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, 400.0)
        assert result == pytest.approx(3.0, abs=1e-9)

    def test_at_lowest_x(self):
        """Input exactly at lowest X → Y of lowest X."""
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, 0.0)
        assert result == pytest.approx(2.0, abs=1e-9)

    def test_at_highest_x(self):
        """Input exactly at highest X → Y of highest X."""
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, 5700.0)
        assert result == pytest.approx(4.9, abs=1e-9)

    def test_linear_interpolation_mid(self):
        """Input midway between two X values → midpoint Y."""
        # Between 0.0 and 200.0 at midpoint 100.0:
        # Y = 2.0 + (100-0)*((2.7-2.0)/(200-0)) = 2.0 + 0.35 = 2.35
        result = normalize_axis_input(X_NORM_X, X_NORM_Y, 100.0)
        assert result == pytest.approx(2.35, abs=1e-9)


# ---------------------------------------------------------------------------
# Tests: interpolate_normalized  (B.1.4)
# ---------------------------------------------------------------------------


class TestInterpolateNormalized:
    """Section B.1.4 — determining the map normalised value."""

    def test_appendix_b_full_example(self):
        """Full Appendix B example: indices (3.9, 1.7) → Z = 2.194."""
        # Note: map_values shape is (rows, cols) = (6, 7).
        # Appendix B convention: first index = column (X), second = row (Y).
        result = interpolate_normalized(Z_MAP, [3.9, 1.7])
        assert result == pytest.approx(2.194, abs=1e-9)

    def test_integer_indices(self):
        """Integer indices should return exact cell values."""
        # Index (3, 1) → row=1, col=3 → Z_MAP[1][3] = 5.6
        result = interpolate_normalized(Z_MAP, [3.0, 1.0])
        assert result == pytest.approx(5.6, abs=1e-9)

    def test_corner_0_0(self):
        """Top-left corner (0, 0)."""
        result = interpolate_normalized(Z_MAP, [0.0, 0.0])
        assert result == pytest.approx(3.4, abs=1e-9)

    def test_corner_max_max(self):
        """Bottom-right corner (6, 5)."""
        result = interpolate_normalized(Z_MAP, [6.0, 5.0])
        assert result == pytest.approx(4.2, abs=1e-9)

    def test_clamp_negative_indices(self):
        """Negative indices should clamp to 0."""
        result = interpolate_normalized(Z_MAP, [-1.0, -1.0])
        assert result == pytest.approx(Z_MAP[0, 0], abs=1e-9)

    def test_clamp_beyond_max(self):
        """Indices beyond max should clamp to last cell."""
        result = interpolate_normalized(Z_MAP, [10.0, 10.0])
        assert result == pytest.approx(Z_MAP[5, 6], abs=1e-9)

    def test_row_interpolation_only(self):
        """Interpolate along rows only (integer column index)."""
        # col=3, row=1.5 → average of Z_MAP[1,3] and Z_MAP[2,3]
        # = (5.6 + 2.2) / 2 = 3.9
        result = interpolate_normalized(Z_MAP, [3.0, 1.5])
        assert result == pytest.approx(3.9, abs=1e-9)

    def test_column_interpolation_only(self):
        """Interpolate along columns only (integer row index)."""
        # col=3.5, row=1 → average of Z_MAP[1,3] and Z_MAP[1,4]
        # = (5.6 + 3.2) / 2 = 4.4
        result = interpolate_normalized(Z_MAP, [3.5, 1.0])
        assert result == pytest.approx(4.4, abs=1e-9)

    def test_step_by_step_appendix_b(self):
        """Verify intermediate results from Appendix B step-by-step."""
        # R1 = 5.6 + (3.9 - 3) * ((3.2 - 5.6) / (4 - 3)) = 3.44
        r1 = 5.6 + 0.9 * (3.2 - 5.6)
        assert r1 == pytest.approx(3.44, abs=1e-9)

        # R2 = 2.2 + (3.9 - 3) * ((1.6 - 2.2) / (4 - 3)) = 1.66
        r2 = 2.2 + 0.9 * (1.6 - 2.2)
        assert r2 == pytest.approx(1.66, abs=1e-9)

        # Z = 3.44 + (1.7 - 1) * ((1.66 - 3.44) / (2 - 1)) = 2.194
        z = r1 + 0.7 * (r2 - r1)
        assert z == pytest.approx(2.194, abs=1e-9)

        # Engine should match
        result = interpolate_normalized(Z_MAP, [3.9, 1.7])
        assert result == pytest.approx(z, abs=1e-9)

    def test_1d_curve(self):
        """1-D interpolation (single-axis: CURVE)."""
        curve_values = np.array([10.0, 20.0, 30.0, 40.0])
        result = interpolate_normalized(curve_values, [1.5])
        assert result == pytest.approx(25.0, abs=1e-9)

    def test_1d_clamp_low(self):
        """1-D: index below 0 clamps."""
        curve_values = np.array([10.0, 20.0, 30.0])
        result = interpolate_normalized(curve_values, [-5.0])
        assert result == pytest.approx(10.0, abs=1e-9)

    def test_1d_clamp_high(self):
        """1-D: index above max clamps."""
        curve_values = np.array([10.0, 20.0, 30.0])
        result = interpolate_normalized(curve_values, [99.0])
        assert result == pytest.approx(30.0, abs=1e-9)

    def test_dimension_mismatch_raises(self):
        """Wrong number of indices should raise ValueError."""
        with pytest.raises(ValueError, match="Expected 2 indices"):
            interpolate_normalized(Z_MAP, [1.0])


# ---------------------------------------------------------------------------
# Tests: 3-D interpolation (CUBOID)
# ---------------------------------------------------------------------------


class TestInterpolateNormalized3D:
    """Test N-D interpolation beyond 2-D."""

    def test_3d_integer_indices(self):
        """3-D cube: integer indices return exact cell."""
        cube = np.arange(24, dtype=np.float64).reshape((2, 3, 4))
        # indices = [x, y, z] where x→dim2(cols), y→dim1, z→dim0
        # [2, 1, 0] → cube[0, 1, 2] = 6
        result = interpolate_normalized(cube, [2.0, 1.0, 0.0])
        assert result == pytest.approx(cube[0, 1, 2], abs=1e-9)

    def test_3d_interpolation(self):
        """3-D cube: fractional indices interpolate correctly."""
        cube = np.arange(8, dtype=np.float64).reshape((2, 2, 2))
        # All indices at 0.5 → average of all 8 values = 3.5
        result = interpolate_normalized(cube, [0.5, 0.5, 0.5])
        assert result == pytest.approx(3.5, abs=1e-9)

    def test_3d_clamp(self):
        """3-D cube: clamping works on all dimensions."""
        cube = np.arange(8, dtype=np.float64).reshape((2, 2, 2))
        result_lo = interpolate_normalized(cube, [-1.0, -1.0, -1.0])
        result_hi = interpolate_normalized(cube, [99.0, 99.0, 99.0])
        assert result_lo == pytest.approx(cube[0, 0, 0], abs=1e-9)
        assert result_hi == pytest.approx(cube[1, 1, 1], abs=1e-9)


# ---------------------------------------------------------------------------
# Tests: full lookup chain (normalize + interpolate)
# ---------------------------------------------------------------------------


class TestLookupChain:
    """End-to-end: normalize through curves then interpolate the map."""

    def test_appendix_b_full_chain(self):
        """Reproduce the complete Appendix B example."""
        # Step 1: Normalise X input
        x_idx = normalize_axis_input(X_NORM_X, X_NORM_Y, 850.0)
        assert x_idx == pytest.approx(3.9, abs=1e-9)

        # Step 2: Normalise Y input
        y_idx = normalize_axis_input(Y_NORM_X, Y_NORM_Y, 60.0)
        assert y_idx == pytest.approx(1.7, abs=1e-9)

        # Step 3: Interpolate
        z = interpolate_normalized(Z_MAP, [x_idx, y_idx])
        assert z == pytest.approx(2.194, abs=1e-9)

    def test_both_inputs_at_boundary_low(self):
        """Both inputs below curve range → clamp to lowest."""
        x_idx = normalize_axis_input(X_NORM_X, X_NORM_Y, -999.0)
        y_idx = normalize_axis_input(Y_NORM_X, Y_NORM_Y, -999.0)
        # x_idx=2.0, y_idx=0.5
        # First interpolate along cols (dim1) at x_idx=2.0 → exact col 2
        # Then along rows (dim0) at y_idx=0.5 → between row 0 and row 1
        # Z_MAP[0,2]=2.1, Z_MAP[1,2]=1.2 → 2.1 + 0.5*(1.2-2.1) = 1.65
        z = interpolate_normalized(Z_MAP, [x_idx, y_idx])
        expected = 2.1 + 0.5 * (1.2 - 2.1)
        assert z == pytest.approx(expected, abs=1e-9)

    def test_both_inputs_at_boundary_high(self):
        """Both inputs above curve range → clamp to highest."""
        x_idx = normalize_axis_input(X_NORM_X, X_NORM_Y, 99999.0)
        y_idx = normalize_axis_input(Y_NORM_X, Y_NORM_Y, 99999.0)
        z = interpolate_normalized(Z_MAP, [x_idx, y_idx])
        # x_idx=4.9, y_idx=4.2 → clamped to valid map range
        assert isinstance(z, float)
