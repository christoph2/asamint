from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any, TypeAlias
from uuid import uuid4

import pya2l
from pya2l import model
from pya2l.a2lparser import path_components
from pya2l.api import inspect as a2l_inspect
from pya2l.api.inspect import (
    AxisPts,
    Characteristic,
    CompuMethod,
    Group,
    Measurement,
    ModCommon,
    ModPar,
    VariantCoding,
    asam_type_size,
)
from pya2l.functions import Formula, fix_axis_par, fix_axis_par_dist

A2LDBSession: TypeAlias = Any  # pya2l DB session (SQLAlchemy ORM Session)

inspect = a2l_inspect


class ManagedA2LSession:
    """Wraps a :class:`pya2l.model.A2LDatabase` and ensures :meth:`close` properly
    disposes the underlying SQLAlchemy engine to prevent ``ResourceWarning`` about
    unclosed SQLite connections."""

    def __init__(self, database: model.A2LDatabase) -> None:
        self._database: model.A2LDatabase | None = database

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Close the session *and* dispose the SQLAlchemy engine."""
        if self._database is not None:
            self._database.close()
            self._database = None

    def __enter__(self) -> ManagedA2LSession:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Transparent delegation to the underlying SessionProxy
    # ------------------------------------------------------------------ #

    def __getattr__(self, name: str) -> Any:
        if self._database is None:
            raise RuntimeError("A2L database session has already been closed.")
        return getattr(self._database.session, name)

    def __repr__(self) -> str:
        return f"ManagedA2LSession(database={self._database!r})"


def _local_a2ldb_is_current(
    db_path: Path,
    *,
    retries: int = 3,
    retry_delay: float = 0.2,
) -> bool:
    expected_columns = {table.name: {column.name for column in table.columns} for table in model.Base.metadata.sorted_tables}
    for attempt in range(retries + 1):
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(db_path)
            table_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            for table_name, required_columns in expected_columns.items():
                if table_name not in table_names:
                    return False
                actual_columns = {row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")')}
                if not required_columns.issubset(actual_columns):
                    return False
        except sqlite3.DatabaseError:
            if attempt == retries:
                return False
            time.sleep(retry_delay)
        else:
            return True
        finally:
            if connection is not None:
                connection.close()
    return False


def _a2l_database_paths(a2l_file: str | Path, *, local: bool) -> tuple[Path, Path]:
    a2l_path, db_path = path_components(
        in_memory=False,
        file_name=str(a2l_file),
        local=local,
    )
    return Path(a2l_path), Path(db_path)


def _open_managed(db_path: Path) -> ManagedA2LSession:
    """Wrap an existing ``.a2ldb`` file in a :class:`ManagedA2LSession`."""
    database = model.A2LDatabase(str(db_path))
    return ManagedA2LSession(database)


def _import_a2l_fresh(
    a2l_path: Path,
    db_path: Path,
    *,
    local: bool,
    encoding: str,
) -> ManagedA2LSession:
    """Import an A2L file and return a :class:`ManagedA2LSession`.

    If the target ``.a2ldb`` is locked by another process, fall back to either
    opening the existing (current) database or importing via a temporary copy.
    """
    if db_path.exists():
        try:
            db_path.unlink()
        except PermissionError:
            if _local_a2ldb_is_current(db_path):
                return _open_managed(db_path)
            temp_a2l = a2l_path.with_name(f"{a2l_path.stem}_{uuid4().hex}{a2l_path.suffix}")
            shutil.copy2(a2l_path, temp_a2l)
            try:
                # import_a2l returns a SessionProxy; wrap it properly by going
                # through A2LDatabase so we control engine disposal.
                pya2l.import_a2l(str(temp_a2l), local=False, encoding=encoding, progress_bar=False)
            finally:
                temp_a2l.unlink(missing_ok=True)
            # find the resulting .a2ldb next to the temp file (local=False → next to a2l)
            _, tmp_db_path = _a2l_database_paths(temp_a2l, local=False)
            if tmp_db_path.exists() and not db_path.exists():
                tmp_db_path.rename(db_path)
            return _open_managed(db_path)
    pya2l.import_a2l(str(a2l_path), local=local, encoding=encoding, progress_bar=False)
    return _open_managed(db_path)


def open_a2l_database(a2l_file: str, encoding: str = "latin-1", *, local: bool = True) -> ManagedA2LSession:
    """Open an A2L database and return a :class:`ManagedA2LSession`.

    The returned session properly disposes the underlying SQLAlchemy engine
    when :meth:`ManagedA2LSession.close` is called, preventing
    ``ResourceWarning`` about unclosed SQLite connections.
    """
    a2l_path, db_path = _a2l_database_paths(a2l_file, local=local)
    if db_path.exists() and _local_a2ldb_is_current(db_path):
        return _open_managed(db_path)
    return _import_a2l_fresh(
        a2l_path,
        db_path,
        local=local,
        encoding=encoding,
    )


__all__ = [
    "A2LDBSession",
    "ManagedA2LSession",
    "a2l_inspect",
    "AxisPts",
    "Characteristic",
    "CompuMethod",
    "Formula",
    "Group",
    "Measurement",
    "ModCommon",
    "ModPar",
    "VariantCoding",
    "asam_type_size",
    "fix_axis_par",
    "fix_axis_par_dist",
    "model",
    "open_a2l_database",
    "inspect",
    "path_components",
]
