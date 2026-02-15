from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any


def open_mdf(path: str | Path) -> Any:
    """Open an MDF file using asammdf."""

    from asammdf import MDF

    return MDF(str(path))


def save_mdf(mdf_obj: Any, dest: str | Path) -> None:
    """Persist an MDF object to disk."""

    mdf_obj.save(str(dest))


def mdf_channels(mdf_obj: Any) -> Iterable[Any]:
    """Iterate over channels in an MDF."""

    return mdf_obj.channels_db.values()
