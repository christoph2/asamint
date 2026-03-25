from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable

import numpy as np


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
    """Adapter-Protokoll für ASAM-orientierte Backends (pyXCP, objutils, ...)."""

    def read_asam_numeric(
        self,
        address: int,
        dtype: str,
        byte_order: str = "MSB_LAST",
        **kws: Any,
    ) -> int | float:
        """Lese skalaren ASAM-Wert aus dem Backend."""
        ...

    def write_asam_numeric(
        self,
        address: int,
        value: int | float,
        dtype: str,
        byte_order: str = "MSB_LAST",
        **kws: Any,
    ) -> None:
        """Schreibe skalaren ASAM-Wert in das Backend."""
        ...

    def read_asam_ndarray(
        self,
        addr: int,
        length: int,
        dtype: str,
        shape: tuple[int, ...] | None = None,
        order: str | None = None,
        byte_order: str = "MSB_LAST",
        **kws: Any,
    ) -> np.ndarray:
        """Lese ASAM-Array aus dem Backend."""
        ...

    def write_asam_ndarray(
        self,
        addr: int,
        array: np.ndarray,
        dtype: str,
        byte_order: str = "MSB_LAST",
        order: str | None = None,
        **kws: Any,
    ) -> None:
        """Schreibe ASAM-Array in das Backend."""
        ...

    def read_asam_string(
        self,
        address: int,
        dtype: str,
        length: int = -1,
        **kws: Any,
    ) -> str:
        """Lese ASAM-String aus dem Backend."""
        ...

    def write_asam_string(
        self,
        address: int,
        value: str,
        dtype: str,
        **kws: Any,
    ) -> None:
        """Schreibe ASAM-String in das Backend."""
        ...
