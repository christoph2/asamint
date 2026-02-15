from __future__ import annotations

from typing import Any

from objutils import Image, Section, dump, load
from objutils.exceptions import InvalidAddressError


def open_image(path: str) -> Any:
    """Open an objutils Image."""

    return Image(path)


__all__ = ["open_image", "Image", "Section", "dump", "load", "InvalidAddressError"]
