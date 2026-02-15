from __future__ import annotations

from typing import Any


def open_a2l_database(
    a2l_file: str, encoding: str = "latin-1", *, local: bool = True
) -> Any:
    """Open an A2L database via pya2l.DB and return the session."""

    from pya2l import DB

    db = DB()
    return db.open_create(a2l_file, encoding=encoding, local=local)
