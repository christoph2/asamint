#!/usr/bin/env python
"""API stability tests for asamint.api."""
from __future__ import annotations

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
