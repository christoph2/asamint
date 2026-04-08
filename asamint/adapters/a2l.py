from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from pya2l import DB, model, path_components
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

inspect = a2l_inspect


def _local_a2ldb_is_current(
    db_path: Path,
    *,
    retries: int = 3,
    retry_delay: float = 0.2,
) -> bool:
    expected_columns = {
        table.name: {column.name for column in table.columns}
        for table in model.Base.metadata.sorted_tables
    }
    for attempt in range(retries + 1):
        try:
            with sqlite3.connect(db_path) as connection:
                table_names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                for table_name, required_columns in expected_columns.items():
                    if table_name not in table_names:
                        return False
                    actual_columns = {
                        row[1]
                        for row in connection.execute(
                            f'PRAGMA table_info("{table_name}")'
                        )
                    }
                    if not required_columns.issubset(actual_columns):
                        return False
        except sqlite3.DatabaseError:
            if attempt == retries:
                return False
            time.sleep(retry_delay)
        else:
            return True
    return False


def _a2l_database_paths(a2l_file: str | Path, *, local: bool) -> tuple[Path, Path]:
    a2l_path, db_path = path_components(
        in_memory=False,
        file_name=str(a2l_file),
        local=local,
    )
    return Path(a2l_path), Path(db_path)


def _import_a2l_fresh(
    db: DB,
    a2l_path: Path,
    db_path: Path,
    *,
    local: bool,
    encoding: str,
) -> Any:
    if db_path.exists():
        try:
            db_path.unlink()
        except PermissionError:
            if _local_a2ldb_is_current(db_path):
                return db.open_existing(str(db_path))
            temp_a2l = a2l_path.with_name(
                f"{a2l_path.stem}_{uuid4().hex}{a2l_path.suffix}"
            )
            shutil.copy2(a2l_path, temp_a2l)
            try:
                return db.import_a2l(str(temp_a2l), local=False, encoding=encoding)
            finally:
                temp_a2l.unlink(missing_ok=True)
    return db.import_a2l(str(a2l_path), local=local, encoding=encoding)


def open_a2l_database(
    a2l_file: str, encoding: str = "latin-1", *, local: bool = True
) -> Any:
    """Open an A2L database via pya2l.DB and return the session."""

    a2l_path, db_path = _a2l_database_paths(a2l_file, local=local)
    db = DB()
    if db_path.exists() and _local_a2ldb_is_current(db_path):
        return db.open_existing(str(db_path))
    return _import_a2l_fresh(
        db,
        a2l_path,
        db_path,
        local=local,
        encoding=encoding,
    )


__all__ = [
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
    "DB",
    "path_components",
]
