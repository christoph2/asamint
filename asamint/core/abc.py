from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


class SupportsLogging(Protocol):
    """Protokoll für Komponenten mit Logger-Attribut."""

    @property
    @abstractmethod
    def logger(self) -> Any:  # pragma: no cover - Interface
        raise NotImplementedError


class CalibrationContext(ABC):
    """Abstrakte Basisklasse für Kalibrierungs-Kontexte."""

    @abstractmethod
    def load(self, name: str) -> Any:
        """Lese einen Kalibrierparameter."""
        raise NotImplementedError

    @abstractmethod
    def save(self, name: str, value: Any) -> None:
        """Schreibe einen Kalibrierparameter."""
        raise NotImplementedError

    @abstractmethod
    def update(self) -> None:
        """Persistiere Änderungen (z. B. Hexfile oder XCP)."""
        raise NotImplementedError


@runtime_checkable
class CalibrationAdapter(Protocol):
    """Adapter-Protokoll für externe Backends (pyXCP, objutils, ...)."""

    def read_numeric(
        self, address: int, dtype: Any, bit_mask: int | None = None
    ) -> Any:
        """Lese skalaren Wert aus dem Backend."""
        ...

    def write_numeric(self, address: int, value: Any, dtype: Any) -> None:
        """Schreibe skalaren Wert in das Backend."""
        ...

    def read_ndarray(
        self,
        addr: int,
        length: int,
        dtype: Any,
        shape: tuple[int, ...] | None = None,
        order: str | None = None,
        bit_mask: int | None = None,
    ) -> Any:  # noqa: E501
        """Lese Array aus dem Backend."""
        ...

    def write_ndarray(self, addr: int, array: Any, order: str | None = None) -> None:
        """Schreibe Array in das Backend."""
        ...
