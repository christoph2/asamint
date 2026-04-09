#!/usr/bin/env python
from asamint.core.deprecation import DeprecatedAlias, deprecated_dir, deprecated_getattr
from asamint.measurement.mdf import MDFCreator, Datasource

__all__ = ["MDFCreator", "Datasource"]

_DEPRECATED_ALIASES: dict[str, DeprecatedAlias] = {}


def __getattr__(name: str) -> object:
    return deprecated_getattr(name, _DEPRECATED_ALIASES, globals(), __name__)


def __dir__() -> list[str]:
    return deprecated_dir(_DEPRECATED_ALIASES, globals())
