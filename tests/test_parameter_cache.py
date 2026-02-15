#!/usr/bin/env python
import pytest

from asamint.calibration.api import ParameterCache


class DummyCalibration:
    def __init__(self) -> None:
        self.value_calls: list[str] = []
        self.dto_calls: list[str] = []

    def load_curve_or_map(self, name: str, category: str, num_axes: int) -> str:
        return f"{category}-{num_axes}-{name}"

    def load_axis_pts(self, name: str) -> str:
        return f"axis-{name}"

    def load_value(self, name: str) -> str:
        self.value_calls.append(name)
        return f"val-{name}"

    def load_value_dto(self, name: str) -> str:
        self.dto_calls.append(name)
        return f"dto-{name}"

    def load_ascii(self, name: str) -> str:
        return f"ascii-{name}"

    def load_value_block(self, name: str) -> str:
        return f"blk-{name}"


@pytest.fixture
def parameter_cache() -> ParameterCache:
    cache = ParameterCache()
    cache.set_parent(DummyCalibration())
    return cache


def test_parameter_cache_caches_and_invalidates(
    parameter_cache: ParameterCache,
) -> None:
    # First access populates caches
    first = parameter_cache.values["A"]
    second = parameter_cache.values["A"]
    assert first == "val-A"
    assert second == "val-A"
    assert parameter_cache.parent.value_calls == ["A"]  # type: ignore[attr-defined]

    dto_first = parameter_cache.value_dtos["B"]
    dto_second = parameter_cache.value_dtos["B"]
    assert dto_first == "dto-B"
    assert dto_second == "dto-B"
    assert parameter_cache.parent.dto_calls == ["B"]  # type: ignore[attr-defined]

    # Invalidate should force reload for both value and DTO caches
    parameter_cache.invalidate("A")
    parameter_cache.invalidate("B")

    refreshed = parameter_cache.values["A"]
    refreshed_dto = parameter_cache.value_dtos["B"]
    assert refreshed == "val-A"
    assert refreshed_dto == "dto-B"
    assert parameter_cache.parent.value_calls == ["A", "A"]  # type: ignore[attr-defined]
    assert parameter_cache.parent.dto_calls == ["B", "B"]  # type: ignore[attr-defined]
