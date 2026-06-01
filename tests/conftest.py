"""Shared pytest fixtures for the asamint test suite.

All fixtures here are automatically available to every test module under
``tests/``.  Fixtures are session- or function-scoped as appropriate:

* **Session-scoped** (loaded once per pytest run):
  ``fixture_dir``, ``cdf20demo_session``, ``asap2_demo_session``

* **Function-scoped** (fresh per test):
  ``calibration_context``, ``hex_image``

Import policy
-------------
External libraries (pya2l, objutils, ...) are accessed **exclusively** via
``asamint.adapters``.  Tests must never import pyxcp, pya2l, objutils or
asammdf directly.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from asamint.adapters.a2l import ModCommon, ModPar, open_a2l_database
from asamint.adapters.objutils import load
from asamint.core.logging import configure_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Absolute path to the directory that contains all test data files.
#: Use this instead of defining ``FIXTURE_DIR = Path(__file__).parent`` in
#: each test module.
FIXTURE_DIR: Path = Path(__file__).parent


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    """Return the absolute path to the test data directory.

    Provides the same value as the module-level constant ``FIXTURE_DIR``
    but through pytest's dependency injection, making it usable in
    parametrize markers that need a path at collection time.
    """
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def cdf20demo_session() -> Iterator[Any]:
    """Open the CDF20demo A2L database (session-scoped, shared across tests).

    Yields a :class:`~asamint.adapters.a2l.ManagedA2LSession` that is
    closed automatically after all tests finish.
    """
    session = open_a2l_database(
        str(FIXTURE_DIR / "CDF20demo"),
        encoding="latin1",
        local=True,
    )
    try:
        yield session
    finally:
        close_fn = getattr(session, "close", None)
        if callable(close_fn):
            close_fn()


@pytest.fixture(scope="session")
def asap2_demo_session() -> Iterator[Any]:
    """Open the ASAP2_Demo_V161 A2L database (session-scoped).

    Yields a :class:`~asamint.adapters.a2l.ManagedA2LSession`.
    """
    session = open_a2l_database(
        str(FIXTURE_DIR / "ASAP2_Demo_V161"),
        encoding="latin1",
        local=True,
    )
    try:
        yield session
    finally:
        close_fn = getattr(session, "close", None)
        if callable(close_fn):
            close_fn()


@pytest.fixture()
def calibration_context(cdf20demo_session: Any) -> SimpleNamespace:
    """Return a calibration context namespace backed by the CDF20demo A2L.

    Contains:
    * ``session``   — the A2L database session
    * ``mod_common`` — parsed MOD_COMMON block (or ``None``)
    * ``mod_par``   — parsed MOD_PAR block (or ``None``)
    * ``logger``    — a DEBUG-level logger for calibration tests

    This replaces the per-module ``@pytest.fixture`` definitions that were
    duplicated across ``test_calibration.py``, ``test_dependent.py``,
    ``test_online_calibration.py`` and ``test_virtual_characteristic.py``.
    """
    return SimpleNamespace(
        session=cdf20demo_session,
        mod_common=ModCommon.get(cdf20demo_session),
        mod_par=ModPar.get(cdf20demo_session) if ModPar.exists(cdf20demo_session) else None,
        logger=configure_logging(name="asamint.calibration.tests", level=logging.DEBUG),
    )


@pytest.fixture()
def hex_image() -> Any:
    """Load the CDF20demo Intel-HEX memory image via the objutils adapter.

    Returns an :class:`~objutils.image.Image` instance ready for use with
    :class:`~asamint.calibration.api.OfflineCalibration`.
    """
    return load("ihex", str(FIXTURE_DIR / "CDF20demo.hex"))
