#!/usr/bin/env python
"""API stability tests for asamint.api."""

from __future__ import annotations

import importlib

import pytest


def test_api_exports_are_resolvable() -> None:
    import asamint.api as api_module

    for name in api_module.__all__:
        assert hasattr(api_module, name), f"Missing export: {name}"


def test_api_unknown_attribute_raises() -> None:
    import asamint.api as api_module

    with pytest.raises(AttributeError):
        _ = api_module._missing_api_symbol_  # type: ignore[attr-defined]


def test_api_default_deprecated_alias_warns() -> None:
    import asamint.api as api_module
    import asamint.measurement as measurement_module

    with pytest.warns(DeprecationWarning):
        resolved = api_module.available_measurement_formats  # type: ignore[attr-defined]

    assert resolved is measurement_module.available_measurement_formats


def test_api_deprecated_alias_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    import asamint.api as api_module

    alias_name = "OldCalibration"
    alias = api_module.DeprecatedAlias(
        target="Calibration",
        remove_in_version="9.9.9",
        replacement="Calibration",
    )
    monkeypatch.setitem(api_module._DEPRECATED_ALIASES, alias_name, alias)

    with pytest.warns(DeprecationWarning):
        resolved = getattr(api_module, alias_name)

    assert resolved is api_module.Calibration


# ------------------------------------------------------------------
# Subpackage deprecation hooks
# ------------------------------------------------------------------

_SUBPACKAGES_WITH_HOOKS = [
    "asamint.adapters",
    "asamint.cdf",
    "asamint.core",
    "asamint.cvx",
    "asamint.hdf5",
    "asamint.mdf",
    "asamint.measurement",
]


@pytest.mark.parametrize("module_path", _SUBPACKAGES_WITH_HOOKS)
def test_subpackage_has_deprecation_hook(module_path: str) -> None:
    mod = importlib.import_module(module_path)
    assert hasattr(mod, "_DEPRECATED_ALIASES"), f"{module_path} missing _DEPRECATED_ALIASES"
    assert isinstance(mod._DEPRECATED_ALIASES, dict)


@pytest.mark.parametrize("module_path", _SUBPACKAGES_WITH_HOOKS)
def test_subpackage_unknown_attribute_raises(module_path: str) -> None:
    mod = importlib.import_module(module_path)
    with pytest.raises(AttributeError, match="has no attribute"):
        getattr(mod, "_nonexistent_symbol_42_")  # noqa: B009


@pytest.mark.parametrize("module_path", _SUBPACKAGES_WITH_HOOKS)
def test_subpackage_dir_includes_all(module_path: str) -> None:
    mod = importlib.import_module(module_path)
    d = dir(mod)
    for name in getattr(mod, "__all__", []):
        assert name in d, f"{name} not in dir({module_path})"


@pytest.mark.parametrize("module_path", _SUBPACKAGES_WITH_HOOKS)
def test_subpackage_deprecated_alias_warns(module_path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from asamint.core.deprecation import DeprecatedAlias

    mod = importlib.import_module(module_path)
    sentinel = object()
    monkeypatch.setattr(mod, "_test_sentinel_", sentinel, raising=False)
    alias = DeprecatedAlias(
        target="_test_sentinel_",
        remove_in_version="99.0.0",
        replacement="_test_sentinel_",
    )
    monkeypatch.setitem(mod._DEPRECATED_ALIASES, "_old_name_", alias)

    with pytest.warns(DeprecationWarning, match="_old_name_"):
        resolved = getattr(mod, "_old_name_")  # noqa: B009

    assert resolved is sentinel
