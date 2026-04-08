"""
Dependent and virtual characteristic evaluation engine (ASAM MCD-2MC Appendix G).

Provides:
- ``DependencyGraph``: build/query the dependency DAG with topological ordering.
- ``DependencyEngine``: evaluate formulas for dependent/virtual characteristics
  and write back results for DEPENDENT_CHARACTERISTIC.
- ``validate_dependency_types``: check input/output type combinations per Tables 29/30.
- Special functions ``min(x)``, ``max(x)``, ``interp(x, a [,b …])`` as defined in G.1.8.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, Optional, Union

import numpy as np

from asamint.adapters.a2l import Characteristic, CompuMethod, Formula, model
from asamint.core.exceptions import CalibrationError

if TYPE_CHECKING:
    from asamint.calibration.api import Calibration

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Characteristic types that are supported by the dependency mechanism (G.1.2)
SUPPORTED_TYPES = frozenset({"VALUE", "CURVE", "MAP", "CUBOID", "CUBE_4", "CUBE_5", "VAL_BLK"})

# Axis types supported for input and dependent characteristics (G.1.2)
SUPPORTED_AXIS_TYPES = frozenset({"STD_AXIS", "COM_AXIS", "FIX_AXIS"})

# Computation method types allowed in dependent characteristics (G.1.7)
ALLOWED_COMPU_METHODS = frozenset({"IDENTICAL", "LINEAR", "RAT_FUNC", "TAB_INTP", "FORM"})

# Types that have axes (CURVE and higher — treated uniformly per G.1.2 Note)
CURVE_LIKE_TYPES = frozenset({"CURVE", "MAP", "CUBOID", "CUBE_4", "CUBE_5"})

# Pattern matching special functions in formula strings (G.1.8)
_MIN_RE = re.compile(r"\bmin\s*\(\s*(\w+)\s*\)", re.IGNORECASE)
_MAX_RE = re.compile(r"\bmax\s*\(\s*(\w+)\s*\)", re.IGNORECASE)
_INTERP_RE = re.compile(
    r"\binterp\s*\(\s*(\w+)\s*(?:,\s*([^)]+))?\s*\)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class DependencyKind(Enum):
    """Whether the characteristic is DEPENDENT (write-back) or VIRTUAL (MC-only)."""

    DEPENDENT = auto()
    VIRTUAL = auto()


@dataclass(frozen=True)
class DependencyEntry:
    """Single entry in the dependency graph."""

    name: str
    formula: str
    input_names: list[str]
    kind: DependencyKind
    dependent_type: str  # Characteristic.type of the dependent parameter


@dataclass
class DependencyGraph:
    """Directed acyclic graph of dependent/virtual characteristics.

    Build once per A2L session; query to get the recalculation order
    when an input characteristic is modified.
    """

    entries: dict[str, DependencyEntry] = field(default_factory=dict)
    # input_name → list of dependent_names that reference it
    reverse_map: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def build(cls, session: Any) -> DependencyGraph:
        """Build the dependency graph from the A2L session.

        Scans all characteristics for ``dependent_characteristic`` and
        ``virtual_characteristic`` blocks and constructs forward / reverse
        maps.
        """
        graph = cls()
        characteristics = session.query(model.Characteristic).all()
        for ch in characteristics:
            if ch.type not in SUPPORTED_TYPES:
                continue

            dep = ch.dependent_characteristic
            virt = ch.virtual_characteristic
            if dep is None and virt is None:
                continue

            if dep is not None:
                entry = DependencyEntry(
                    name=ch.name,
                    formula=dep.formula,
                    input_names=list(dep.characteristic_id),
                    kind=DependencyKind.DEPENDENT,
                    dependent_type=ch.type,
                )
            else:
                entry = DependencyEntry(
                    name=ch.name,
                    formula=virt.formula,
                    input_names=list(virt.characteristic_id),
                    kind=DependencyKind.VIRTUAL,
                    dependent_type=ch.type,
                )

            graph.entries[ch.name] = entry
            for inp in entry.input_names:
                graph.reverse_map[inp].append(ch.name)

        graph._detect_cycles()
        return graph

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        return len(self.entries) == 0

    def dependents_of(self, input_name: str) -> list[str]:
        """Return the direct dependents of *input_name*."""
        return list(self.reverse_map.get(input_name, []))

    def calculation_order(self, modified_name: str) -> list[DependencyEntry]:
        """Return a topologically sorted list of entries that must be
        recalculated when *modified_name* changes.

        The order guarantees that every entry appears after all its inputs
        have been recalculated.
        """
        affected = self._collect_affected(modified_name)
        if not affected:
            return []
        return self._topological_sort(affected)

    def _collect_affected(self, modified_name: str) -> set[str]:
        """BFS to collect all transitively affected dependent names."""
        affected: set[str] = set()
        queue = list(self.reverse_map.get(modified_name, []))
        while queue:
            name = queue.pop(0)
            if name in affected:
                continue
            affected.add(name)
            queue.extend(self.reverse_map.get(name, []))
        return affected

    def _topological_sort(self, affected: set[str]) -> list[DependencyEntry]:
        """Kahn's algorithm restricted to *affected* nodes."""
        in_degree: dict[str, int] = {n: 0 for n in affected}
        for name in affected:
            for inp in self.entries[name].input_names:
                if inp in affected:
                    in_degree[name] += 1

        ready = sorted(n for n, d in in_degree.items() if d == 0)
        result: list[DependencyEntry] = []
        while ready:
            name = ready.pop(0)
            result.append(self.entries[name])
            for dep_name in self.reverse_map.get(name, []):
                if dep_name in in_degree:
                    in_degree[dep_name] -= 1
                    if in_degree[dep_name] == 0:
                        ready.append(dep_name)
                        ready.sort()
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_cycles(self) -> None:
        """Raise ``CalibrationError`` if the graph contains a cycle."""
        WHITE, GRAY, BLACK = 0, 1, 2
        colour: dict[str, int] = {n: WHITE for n in self.entries}

        def visit(name: str, path: list[str]) -> None:
            colour[name] = GRAY
            path.append(name)
            entry = self.entries[name]
            for inp in entry.input_names:
                if inp in colour:
                    if colour[inp] == GRAY:
                        cycle = path[path.index(inp) :]
                        raise CalibrationError(
                            f"Circular dependency detected: {' → '.join(cycle)} → {inp}"
                        )
                    if colour[inp] == WHITE:
                        visit(inp, path)
            path.pop()
            colour[name] = BLACK

        for name in self.entries:
            if colour[name] == WHITE:
                visit(name, [])


# ---------------------------------------------------------------------------
# Type combination validation (ASAM Appendix G, Tables 29 / 30 / 32)
# ---------------------------------------------------------------------------

# Allowed (frozenset-of-input-types, dependent-type) combinations.
# CURVE stands for all curve-like types (MAP, CUBOID, etc.) — they must match.
_SINGLE_INPUT_COMBOS: set[tuple[str, str]] = {
    ("VALUE", "VALUE"),
    ("CURVE_LIKE", "VALUE"),
    ("CURVE_LIKE", "CURVE_LIKE"),
    ("VAL_BLK", "VALUE"),
    ("VAL_BLK", "VAL_BLK"),
}


def _normalise_type(t: str) -> str:
    """Map CURVE/MAP/CUBOID/CUBE_4/CUBE_5 → ``CURVE_LIKE``."""
    return "CURVE_LIKE" if t in CURVE_LIKE_TYPES else t


@dataclass
class ValidationResult:
    """Result of dependency type validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_dependency_types(
    graph: DependencyGraph,
    session: Any,
) -> ValidationResult:
    """Validate all dependency entries against ASAM Appendix G rules.

    Checks:
    - Supported characteristic types (G.1.2)
    - Allowed input/output combinations (Tables 29/30)
    - Axis compatibility for multi-CURVE inputs
    - Forbidden ASCII type
    - Axis type restrictions (no RES_AXIS, no CURVE_AXIS)
    - Computation method restrictions (G.1.7)
    """
    result = ValidationResult(valid=True)
    for entry in graph.entries.values():
        _validate_entry(entry, session, result)
    return result


def _validate_entry(
    entry: DependencyEntry, session: Any, result: ValidationResult
) -> None:
    """Validate a single dependency entry."""
    dep_type = entry.dependent_type

    if dep_type not in SUPPORTED_TYPES or dep_type == "ASCII":
        result.valid = False
        result.errors.append(f"{entry.name}: unsupported dependent type '{dep_type}'")
        return

    input_types = _resolve_input_types(entry, session, result)
    if not input_types:
        return

    _check_input_types(entry, input_types, result)
    _check_type_combinations(entry, input_types, result)
    _check_axis_compatibility(entry, input_types, session, result)
    _check_compu_method(entry, session, result)
    _check_axis_types(entry, session, result)


def _resolve_input_types(
    entry: DependencyEntry, session: Any, result: ValidationResult
) -> list[str]:
    """Resolve the type of each input characteristic."""
    input_types: list[str] = []
    for inp_name in entry.input_names:
        try:
            inp_ch = Characteristic.get(session, inp_name)
            input_types.append(inp_ch.type)
        except (ValueError, AttributeError):
            result.valid = False
            result.errors.append(f"{entry.name}: input '{inp_name}' not found")
    return input_types


def _check_input_types(
    entry: DependencyEntry, input_types: list[str], result: ValidationResult
) -> None:
    """Check that each input type is supported and not ASCII."""
    for inp_name, inp_type in zip(entry.input_names, input_types):
        if inp_type not in SUPPORTED_TYPES:
            result.valid = False
            result.errors.append(
                f"{entry.name}: input '{inp_name}' has unsupported type '{inp_type}'"
            )
        if inp_type == "ASCII":
            result.valid = False
            result.errors.append(
                f"{entry.name}: input '{inp_name}' is ASCII (not allowed)"
            )

    # G.1.2: no mixing CURVE_LIKE and VAL_BLK
    norm_inputs = {_normalise_type(t) for t in input_types}
    if "CURVE_LIKE" in norm_inputs and "VAL_BLK" in norm_inputs:
        result.valid = False
        result.errors.append(
            f"{entry.name}: CURVE and VAL_BLK must not be mixed in the same formula"
        )


def _check_type_combinations(
    entry: DependencyEntry, input_types: list[str], result: ValidationResult
) -> None:
    """Check input/dependent combinations per Tables 29/30."""
    norm_dep = _normalise_type(entry.dependent_type)
    for inp_type in input_types:
        norm_inp = _normalise_type(inp_type)
        if (norm_inp, norm_dep) not in _SINGLE_INPUT_COMBOS:
            result.valid = False
            result.errors.append(
                f"{entry.name}: unsupported combination "
                f"input={inp_type} → dependent={entry.dependent_type}"
            )


def _check_axis_compatibility(
    entry: DependencyEntry,
    input_types: list[str],
    session: Any,
    result: ValidationResult,
) -> None:
    """Check axis count/size for multi-CURVE or multi-VAL_BLK inputs."""
    # CURVE_LIKE inputs: same #axes and shape
    curve_inputs = [
        (n, t) for n, t in zip(entry.input_names, input_types) if t in CURVE_LIKE_TYPES
    ]
    if len(curve_inputs) > 1:
        try:
            first = Characteristic.get(session, curve_inputs[0][0])
            for inp_name, _ in curve_inputs[1:]:
                ch = Characteristic.get(session, inp_name)
                if len(ch.axisDescriptions) != len(first.axisDescriptions):
                    result.valid = False
                    result.errors.append(
                        f"{entry.name}: inputs {curve_inputs[0][0]} and {inp_name} "
                        f"have different number of axes"
                    )
                if ch.fnc_np_shape != first.fnc_np_shape:
                    result.valid = False
                    result.errors.append(
                        f"{entry.name}: inputs {curve_inputs[0][0]} and {inp_name} "
                        f"have different axis sizes"
                    )
        except (ValueError, AttributeError) as exc:
            result.warnings.append(
                f"{entry.name}: could not verify axis compatibility: {exc}"
            )

    # VAL_BLK inputs: same size
    vblk_inputs = [n for n, t in zip(entry.input_names, input_types) if t == "VAL_BLK"]
    if len(vblk_inputs) > 1:
        try:
            first = Characteristic.get(session, vblk_inputs[0])
            for inp_name in vblk_inputs[1:]:
                ch = Characteristic.get(session, inp_name)
                if ch.fnc_np_shape != first.fnc_np_shape:
                    result.valid = False
                    result.errors.append(
                        f"{entry.name}: VAL_BLK inputs {vblk_inputs[0]} and {inp_name} "
                        f"have different sizes"
                    )
        except (ValueError, AttributeError) as exc:
            result.warnings.append(
                f"{entry.name}: could not verify VAL_BLK size compatibility: {exc}"
            )


def _check_compu_method(
    entry: DependencyEntry, session: Any, result: ValidationResult
) -> None:
    """G.1.7: check computation method type."""
    try:
        dep_ch = Characteristic.get(session, entry.name)
        if dep_ch.compuMethod != "NO_COMPU_METHOD":
            cm_type = dep_ch.compuMethod.conversionType
            if cm_type not in ALLOWED_COMPU_METHODS:
                result.warnings.append(
                    f"{entry.name}: computation method '{cm_type}' is not recommended "
                    f"(allowed: {', '.join(sorted(ALLOWED_COMPU_METHODS))})"
                )
    except (ValueError, AttributeError):
        pass


def _check_axis_types(
    entry: DependencyEntry, session: Any, result: ValidationResult
) -> None:
    """G.1.2: axis type restrictions for curve-like dependents."""
    if entry.dependent_type not in CURVE_LIKE_TYPES:
        return
    try:
        dep_ch = Characteristic.get(session, entry.name)
        for ax in dep_ch.axisDescriptions:
            if hasattr(ax, "attribute") and ax.attribute not in SUPPORTED_AXIS_TYPES:
                result.valid = False
                result.errors.append(
                    f"{entry.name}: axis type '{ax.attribute}' is not supported "
                    f"(allowed: {', '.join(sorted(SUPPORTED_AXIS_TYPES))})"
                )
    except (ValueError, AttributeError):
        pass


# ---------------------------------------------------------------------------
# Special functions (G.1.8)
# ---------------------------------------------------------------------------


def _eval_min(values: np.ndarray) -> float:
    """G.1.8.1 — ``min(x)``: minimum value of a CURVE or VAL_BLK."""
    return float(np.min(values))


def _eval_max(values: np.ndarray) -> float:
    """G.1.8.2 — ``max(x)``: maximum value of a CURVE or VAL_BLK."""
    return float(np.max(values))


def _eval_interp_1d(
    axis_values: np.ndarray,
    fnc_values: np.ndarray,
    position: float,
) -> float:
    """G.1.8.3 — 1-D interpolation (CURVE)."""
    return float(np.interp(position, axis_values, fnc_values))


def _eval_interp_nd(
    axes: list[np.ndarray],
    fnc_values: np.ndarray,
    positions: list[float],
) -> float:
    """G.1.8.3 — N-D interpolation (MAP, CUBOID, …).

    Uses successive 1-D interpolations along each axis (multilinear).
    """
    result = fnc_values.astype(float)
    # Interpolate from the last axis to the first
    for dim in reversed(range(len(axes))):
        axis = axes[dim]
        pos = positions[dim]
        # Clamp
        pos = np.clip(pos, axis[0], axis[-1])
        # Find bracketing indices
        idx = np.searchsorted(axis, pos, side="right") - 1
        idx = np.clip(idx, 0, len(axis) - 2)
        lo, hi = axis[idx], axis[idx + 1]
        frac = (pos - lo) / (hi - lo) if hi != lo else 0.0
        # Interpolate along this dimension
        slices_lo = [slice(None)] * result.ndim
        slices_hi = [slice(None)] * result.ndim
        slices_lo[dim] = idx
        slices_hi[dim] = idx + 1
        result = result[tuple(slices_lo)] * (1.0 - frac) + result[tuple(slices_hi)] * frac
    return float(result)


# ---------------------------------------------------------------------------
# Formula evaluation helpers
# ---------------------------------------------------------------------------


def _detect_special_function(formula: str) -> Optional[tuple[str, str, list[float]]]:
    """Detect if a formula consists entirely of a special function call.

    Returns ``(func_name, param_name, extra_args)`` or ``None``.
    """
    stripped = formula.strip()

    m = _MIN_RE.fullmatch(stripped)
    if m:
        return ("min", m.group(1), [])

    m = _MAX_RE.fullmatch(stripped)
    if m:
        return ("max", m.group(1), [])

    m = _INTERP_RE.fullmatch(stripped)
    if m:
        param_name = m.group(1)
        extra_raw = m.group(2) or ""
        extra_args = [float(x.strip()) for x in extra_raw.split(",") if x.strip()]
        return ("interp", param_name, extra_args)

    return None


# ---------------------------------------------------------------------------
# DependencyEngine
# ---------------------------------------------------------------------------


@dataclass
class EvaluationResult:
    """Result of evaluating a single dependent/virtual characteristic."""

    name: str
    physical_value: Union[float, np.ndarray]
    kind: DependencyKind


class DependencyEngine:
    """Evaluates dependent and virtual characteristics.

    Requires a reference to the ``Calibration`` instance for loading input
    values and accessing the A2L session / system constants.
    """

    def __init__(self, calibration: Calibration, graph: DependencyGraph) -> None:
        self._cal = calibration
        self._graph = graph

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, entry: DependencyEntry) -> EvaluationResult:
        """Evaluate a single dependency entry and return the physical result."""
        special = _detect_special_function(entry.formula)
        if special is not None:
            return self._evaluate_special(entry, *special)
        return self._evaluate_formula(entry)

    def recalculate_dependents(self, modified_name: str) -> list[EvaluationResult]:
        """Recalculate all characteristics affected by a change to *modified_name*.

        For DEPENDENT characteristics the result is written back to the image.
        For VIRTUAL characteristics only the parameter cache is updated.

        Returns the list of evaluation results in calculation order.
        """
        order = self._graph.calculation_order(modified_name)
        if not order:
            return []

        results: list[EvaluationResult] = []
        for entry in order:
            try:
                result = self.evaluate(entry)
                results.append(result)

                if entry.kind == DependencyKind.DEPENDENT:
                    self._write_back(entry, result)
                self._update_cache(entry, result)
            except (ValueError, TypeError, KeyError, CalibrationError) as exc:
                logger.error(
                    "Failed to recalculate dependent characteristic %r: %s",
                    entry.name,
                    exc,
                )
        return results

    # ------------------------------------------------------------------
    # Formula evaluation
    # ------------------------------------------------------------------

    def _evaluate_formula(self, entry: DependencyEntry) -> EvaluationResult:
        """Evaluate a standard arithmetic formula."""
        input_values = self._load_input_values(entry)

        system_constants = {}
        if self._cal.mod_par is not None:
            system_constants = self._cal.mod_par.systemConstants

        fx = Formula(formula=entry.formula, system_constants=system_constants)
        result = fx.int_to_physical(*input_values)

        # Coerce result type for VALUE dependents (always scalar)
        if entry.dependent_type == "VALUE" and isinstance(result, np.ndarray):
            result = result.item() if result.size == 1 else float(np.sum(result))

        return EvaluationResult(
            name=entry.name,
            physical_value=result,
            kind=entry.kind,
        )

    def _evaluate_special(
        self,
        entry: DependencyEntry,
        func_name: str,
        param_name: str,
        extra_args: list[float],
    ) -> EvaluationResult:
        """Evaluate a special function (min, max, interp)."""
        values, axes = self._load_input_array(param_name)

        if func_name == "min":
            result = _eval_min(values)
        elif func_name == "max":
            result = _eval_max(values)
        elif func_name == "interp":
            if axes is not None and len(axes) >= 1:
                if len(axes) == 1:
                    result = _eval_interp_1d(axes[0], values.ravel(), extra_args[0])
                else:
                    result = _eval_interp_nd(axes, values, extra_args[: len(axes)])
            else:
                raise CalibrationError(
                    f"interp() requires a CURVE-like input, got {param_name}"
                )
        else:
            raise CalibrationError(f"Unknown special function: {func_name}")

        return EvaluationResult(
            name=entry.name,
            physical_value=result,
            kind=entry.kind,
        )

    # ------------------------------------------------------------------
    # Input loading
    # ------------------------------------------------------------------

    def _load_input_values(self, entry: DependencyEntry) -> list[Any]:
        """Load physical values for all inputs of an entry.

        Returns scalars for VALUE inputs, numpy arrays for CURVE/MAP/VAL_BLK.
        """
        values: list[Any] = []
        for inp_name in entry.input_names:
            inp_type = self._cal.characteristic_category(inp_name)
            if inp_type == "VALUE":
                obj = self._load_or_cached("VALUE", inp_name)
                values.append(obj.phys if hasattr(obj, "phys") else obj)
            elif inp_type == "VAL_BLK":
                obj = self._load_or_cached("VAL_BLK", inp_name)
                values.append(obj.phys if hasattr(obj, "phys") else obj)
            elif inp_type in CURVE_LIKE_TYPES:
                obj = self._load_or_cached(inp_type, inp_name)
                values.append(obj.phys if hasattr(obj, "phys") else obj)
            else:
                raise CalibrationError(
                    f"Unsupported input type '{inp_type}' for '{inp_name}'"
                )
        return values

    def _load_input_array(
        self, param_name: str
    ) -> tuple[np.ndarray, Optional[list[np.ndarray]]]:
        """Load the function values (and optionally axes) for an array-like input."""
        inp_type = self._cal.characteristic_category(param_name)
        obj = self._load_or_cached(inp_type, param_name)

        if inp_type == "VAL_BLK":
            return (np.asarray(obj.phys), None)

        if inp_type in CURVE_LIKE_TYPES:
            axes = [np.asarray(ax.phys) for ax in obj.axes]
            return (np.asarray(obj.phys), axes)

        raise CalibrationError(
            f"min/max/interp requires CURVE or VAL_BLK, got {inp_type} for '{param_name}'"
        )

    def _load_or_cached(self, category: str, name: str) -> Any:
        """Load a parameter from cache or via the Calibration API."""
        from asamint.calibration.api import ParameterCache

        cache = self._cal.parameter_cache
        if isinstance(cache, ParameterCache):
            cat_cache = cache[category]
            if cat_cache is not None:
                return cat_cache[name]

        # Fallback: load directly
        if category == "VALUE":
            return self._cal.load_value(name)
        elif category == "VAL_BLK":
            return self._cal.load_value_block(name)
        elif category == "CURVE":
            return self._cal.load_curve_or_map(name, "CURVE", 1)
        elif category == "MAP":
            return self._cal.load_curve_or_map(name, "MAP", 2)
        elif category == "CUBOID":
            return self._cal.load_curve_or_map(name, "CUBOID", 3)
        elif category == "CUBE_4":
            return self._cal.load_curve_or_map(name, "CUBE_4", 4)
        elif category == "CUBE_5":
            return self._cal.load_curve_or_map(name, "CUBE_5", 5)
        else:
            raise CalibrationError(f"Cannot load category '{category}' for '{name}'")

    # ------------------------------------------------------------------
    # Write-back / cache update
    # ------------------------------------------------------------------

    def _write_back(self, entry: DependencyEntry, result: EvaluationResult) -> None:
        """Write a DEPENDENT characteristic result back to the image.

        Bypasses read-only and limits checks since the ASAM spec mandates
        that the MC-System writes calculated values to the controller.
        """
        from asamint.calibration.api import ExecutionPolicy

        phys = result.physical_value
        if entry.dependent_type == "VALUE":
            self._cal.save_value(
                entry.name,
                phys,
                readOnlyPolicy=ExecutionPolicy.IGNORE,
                limitsPolicy=ExecutionPolicy.IGNORE,
            )
        elif entry.dependent_type == "VAL_BLK":
            self._cal.save_value_block(
                entry.name,
                np.asarray(phys),
                readOnlyPolicy=ExecutionPolicy.IGNORE,
            )
        elif entry.dependent_type in CURVE_LIKE_TYPES:
            existing = self._load_or_cached(entry.dependent_type, entry.name)
            existing._phys = np.asarray(phys)
            self._cal.save_curve_or_map(
                entry.name,
                existing,
                readOnlyPolicy=ExecutionPolicy.IGNORE,
            )
        else:
            logger.warning(
                "Cannot write back dependent type %r for %r",
                entry.dependent_type,
                entry.name,
            )

    def _update_cache(self, entry: DependencyEntry, result: EvaluationResult) -> None:
        """Update the parameter cache after evaluation."""
        from asamint.calibration.api import ParameterCache

        cache = self._cal.parameter_cache
        if not isinstance(cache, ParameterCache):
            return

        cache.invalidate(entry.name)
