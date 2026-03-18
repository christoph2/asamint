"""
asamint.core — zentrale Typen und Hilfsfunktionen.

Beinhaltet:
- ByteOrder (ASAM-1.2-konform: MSB_LAST / MSB_FIRST)
- get_data_type(datatype, byte_order) -> str (liefert dtype-key z.B. "uint8_le")
- byte_order(obj, mod_common=None) -> Optional[ByteOrder]
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, Optional, Tuple

from .abc import CalibrationAdapter, CalibrationContext, SupportsLogging
from .exceptions import (
    AdapterError,
    AsamIntError,
    CalibrationError,
    ConfigurationError,
    FileFormatError,
    LimitViolation,
    RangeError,
    ReadOnlyError,
)
from .logging import configure_logging
from .models import (
    CalibrationLimits,
    CalibrationValue,
    GeneralConfig,
    LoggingConfig,
    MeasurementChannel,
)


import numpy as np
from typing import Literal, Dict, List

ByteOrder = Literal[
    "MSB_FIRST",
    "MSB_LAST",
    "MSB_FIRST_MSW_LAST",
    "MSB_LAST_MSW_FIRST",
]

class ECUByteOrder:
    """
    Utility class to decode ECU-specific byte orders into NumPy arrays.
    Supports 16/32/64-bit integers and floats.
    """

    # ------------------------------------------------------------
    # 1) Byte permutation tables
    # ------------------------------------------------------------
    PERMUTATIONS: Dict[str, Dict[int, List[int]]] = {
        "MSB_FIRST": {
            2: [0, 1],
            4: [0, 1, 2, 3],
            8: [0, 1, 2, 3, 4, 5, 6, 7],
        },
        "MSB_LAST": {
            2: [1, 0],
            4: [3, 2, 1, 0],
            8: [7, 6, 5, 4, 3, 2, 1, 0],
        },
        "MSB_FIRST_MSW_LAST": {
            4: [1, 0, 3, 2],
            8: [1, 0, 3, 2, 5, 4, 7, 6],
        },
        "MSB_LAST_MSW_FIRST": {
            4: [2, 3, 0, 1],
            8: [6, 7, 4, 5, 2, 3, 0, 1],
        },
    }

    # ------------------------------------------------------------
    # 2) Endianness mapping for NumPy dtype prefixes
    # ------------------------------------------------------------
    ENDIAN_PREFIX = {
        "MSB_FIRST": ">",
        "MSB_LAST": "<",
        "MSB_FIRST_MSW_LAST": ">",
        "MSB_LAST_MSW_FIRST": "<",
    }

    # ------------------------------------------------------------
    # 3) Public decode function
    # ------------------------------------------------------------
    @classmethod
    def decode(cls, raw: bytes, byteorder: ByteOrder, dtype: str):
        """
        Decode raw ECU bytes into a NumPy array.

        Parameters
        ----------
        raw : bytes
            Raw byte stream from ECU.
        byteorder : ByteOrder
            ECU byte order variant.
        dtype : str
            NumPy dtype without endianness prefix, e.g. "i2", "u4", "f8".

        Returns
        -------
        np.ndarray
        """
        size = np.dtype(dtype).itemsize
        if size not in cls.PERMUTATIONS[byteorder]:
            raise ValueError(f"Byte order {byteorder} not supported for {size} bytes")

        perm = cls.PERMUTATIONS[byteorder][size]
        endian = cls.ENDIAN_PREFIX[byteorder]

        # Convert to uint8 array
        arr = np.frombuffer(raw, dtype=np.uint8)

        if arr.size % size != 0:
            raise ValueError("Raw data size is not a multiple of dtype size")

        arr = arr.reshape(-1, size)

        # Apply permutation
        reordered = arr[:, perm].tobytes()

        # Interpret as final dtype
        final_dtype = np.dtype(endian + dtype)
        return np.frombuffer(reordered, dtype=final_dtype)

class ByteOrder(IntEnum):
    """ASAM Byte-Order gemäß ASAM 1.2.

    MSB_LAST entspricht dem Intel-/Little-Endian-Layout, MSB_FIRST dem
    Motorola-/Big-Endian-Layout. Legacy-Schlüsselwörter werden als Aliase
    beibehalten, sind aber semantisch auf die ASAM-Definition gemappt.

    Attributes:
        MSB_LAST: Intel-Format (Little-Endian).
        MSB_FIRST: Motorola-Format (Big-Endian).
        BIG_ENDIAN: Legacy-Alias für MSB_LAST.
        LITTLE_ENDIAN: Legacy-Alias für MSB_FIRST.
    """

    MSB_LAST = 0
    MSB_FIRST = 1
    BIG_ENDIAN = MSB_LAST
    LITTLE_ENDIAN = MSB_FIRST


_DATA_TYPES: dict[str, tuple[str, str]] = {
    "UBYTE": ("uint8_le", "uint8_be"),
    "SBYTE": ("int8_le", "int8_be"),
    "UWORD": ("uint16_le", "uint16_be"),
    "SWORD": ("int16_le", "int16_be"),
    "ULONG": ("uint32_le", "uint32_be"),
    "SLONG": ("int32_le", "int32_be"),
    "A_UINT64": ("uint64_le", "uint64_be"),
    "A_INT64": ("int64_le", "int64_be"),
    "FLOAT32_IEEE": ("float32_le", "float32_be"),
    "FLOAT64_IEEE": ("float64_le", "float64_be"),
}


def get_data_type(datatype: str, byte_order: ByteOrder) -> str:
    """Liefert den dtype-Schlüssel für einen ASAM-Datentyp und eine Byte-Order.

    Args:
        datatype: ASAM-Datentyp (z. B. "UWORD", "FLOAT32_IEEE").
        byte_order: ByteOrder-Enum.

    Returns:
        dtype-Schlüssel wie "uint16_le" oder "float32_be".

    Raises:
        KeyError: Wenn der Datentyp unbekannt ist und kein Fallback existiert.
    """
    if datatype not in _DATA_TYPES:
        return _DATA_TYPES["ULONG"][byte_order.value]
    return _DATA_TYPES[datatype][byte_order.value]


def byte_order(  # noqa: C901
    obj: Any, mod_common: Any | None = None
) -> ByteOrder | None:
    """Ermittle die Byte-Order eines A2L-Objekts (optional Fallback mod_common).

    Reihenfolge:
    1. Attribute des Objekts: byte_order, byteOrder, BYTE_ORDER.
    2. Fallback auf mod_common mit denselben Attributnamen.
    3. None, wenn nichts definiert.

    Unterstützt Enum-Werte, Strings (MSB_FIRST/MSB_LAST, LITTLE_ENDIAN/BIG_ENDIAN)
    sowie numerische Werte 0/1.

    Args:
        obj: A2L-Objekt mit optionalem Byte-Order-Attribut.
        mod_common: Optionales MOD_COMMON-Objekt als Fallback.

    Returns:
        Gefundene ByteOrder oder None.
    """
    attr_names = ("byte_order", "byteOrder", "BYTE_ORDER")
    candidate: Any = None

    for name in attr_names:
        if hasattr(obj, name):
            candidate = getattr(obj, name)
            if candidate is not None:
                break

    if candidate is None and mod_common is not None:
        for name in attr_names:
            if hasattr(mod_common, name):
                candidate = getattr(mod_common, name)
                if candidate is not None:
                    break

    if candidate is None:
        return None

    if isinstance(candidate, ByteOrder):
        return candidate

    if isinstance(candidate, str):
        key = candidate.strip().upper().replace("-", "_").replace(" ", "_")
        mapping = {
            "MSB_FIRST": ByteOrder.MSB_FIRST,
            "MSB_LAST": ByteOrder.MSB_LAST,
            "LITTLE_ENDIAN": ByteOrder.LITTLE_ENDIAN,
            "BIG_ENDIAN": ByteOrder.BIG_ENDIAN,
        }
        return mapping.get(key)

    try:
        return ByteOrder(int(candidate))
    except (ValueError, TypeError):
        return None


__all__ = [
    "ByteOrder",
    "get_data_type",
    "byte_order",
    "AdapterError",
    "AsamIntError",
    "CalibrationError",
    "ConfigurationError",
    "FileFormatError",
    "LimitViolation",
    "RangeError",
    "ReadOnlyError",
    "configure_logging",
    "CalibrationAdapter",
    "CalibrationContext",
    "SupportsLogging",
    "GeneralConfig",
    "LoggingConfig",
    "CalibrationLimits",
    "CalibrationValue",
    "MeasurementChannel",
]
