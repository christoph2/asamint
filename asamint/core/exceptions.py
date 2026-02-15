from __future__ import annotations

from dataclasses import dataclass


class AsamIntError(Exception):
    """Basisklasse für asamint-spezifische Fehler."""


class ConfigurationError(AsamIntError):
    """Fehler in der Anwendungskonfiguration."""


class AdapterError(AsamIntError):
    """Fehler in Adaptern zu externen Bibliotheken."""


class CalibrationError(AsamIntError):
    """Allgemeiner Fehler beim Kalibrieren."""


class ReadOnlyError(CalibrationError):
    """Schreibzugriff auf ein schreibgeschütztes Objekt."""


class RangeError(CalibrationError):
    """Wert außerhalb der spezifizierten Grenzen."""


class FileFormatError(AsamIntError):
    """Fehlerhafte oder unerwartete Dateistruktur."""


@dataclass(slots=True)
class LimitViolation(RangeError):
    """Detailierte Limitverletzung mit Soll/Ist-Information."""

    name: str
    lower_limit: float | None
    upper_limit: float | None
    value: float

    def __str__(self) -> str:
        limits = []
        if self.lower_limit is not None:
            limits.append(f"lower={self.lower_limit}")
        if self.upper_limit is not None:
            limits.append(f"upper={self.upper_limit}")
        limit_str = ", ".join(limits) if limits else "no limits"
        return f"{self.name}: {self.value} outside ({limit_str})"
