from __future__ import annotations

from typing import Any

from pya2l import DB, model
from pya2l.api.inspect import (
    AxisPts,
    Characteristic,
    CompuMethod,
    Group,
    ModCommon,
    ModPar,
    VariantCoding,
    asam_type_size,
)
from pya2l.functions import Formula, fix_axis_par, fix_axis_par_dist


def open_a2l_database(
    a2l_file: str, encoding: str = "latin-1", *, local: bool = True
) -> Any:
    """Open an A2L database via pya2l.DB and return the session."""

    db = DB()
    return db.open_create(a2l_file, encoding=encoding, local=local)


__all__ = [
    "AxisPts",
    "Characteristic",
    "CompuMethod",
    "Formula",
    "Group",
    "ModCommon",
    "ModPar",
    "VariantCoding",
    "asam_type_size",
    "fix_axis_par",
    "fix_axis_par_dist",
    "model",
    "open_a2l_database",
]
