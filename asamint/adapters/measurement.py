#!/usr/bin/env python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Protocol, TYPE_CHECKING

from asamint.core.logging import configure_logging

if TYPE_CHECKING:
    from asamint.measurement import RunResult


logger = configure_logging(__name__)


class MeasurementPersist(Protocol):
    def __call__(
        self,
        *,
        data: dict[str, Any],
        units: Optional[dict[str, Optional[str]]] = None,
        project_meta: Optional[dict[str, Any]] = None,
        output_path: str | Path | None = None,
        **kwargs: Any,
    ) -> "RunResult":
        ...


@dataclass
class MeasurementFormat:
    name: str
    persist: MeasurementPersist
    creator_factory: Callable[[dict[str, Any]], Any] | None = None
    description: str | None = None
    default_extension: str | None = None

    @property
    def supports_live_capture(self) -> bool:
        return self.creator_factory is not None


_registry: Dict[str, MeasurementFormat] = {}


def _normalize(name: str) -> str:
    return name.strip().upper()


def register_measurement_format(fmt: MeasurementFormat) -> None:
    key = _normalize(fmt.name)
    _registry[key] = fmt
    logger.debug("Registered measurement format '%s'", key)


def get_measurement_format(name: str) -> MeasurementFormat:
    key = _normalize(name)
    try:
        return _registry[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported measurement format '{name}'.") from exc


def available_measurement_formats() -> list[str]:
    return sorted(_registry.keys())

