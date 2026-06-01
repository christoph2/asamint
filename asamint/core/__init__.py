"""
asamint.core — zentrale Typen und Hilfsfunktionen.

Beinhaltet:
- ByteOrder (ASAM-1.2-konform: MSB_LAST / MSB_FIRST)
- get_data_type(datatype, byte_order) -> str (liefert dtype-key z.B. "uint8_le")
- normalize_asam_byte_order(value) -> Optional[str]
- byte_order(obj, mod_common=None) -> Optional[ByteOrder]
"""

from __future__ import annotations

from enum import IntEnum
from typing import Any, Dict, List, Optional

import numpy as np

from .abc import CalibrationAdapter, CalibrationContext, SupportsLogging
from .deprecation import DeprecatedAlias, deprecated_dir, deprecated_getattr
from .exceptions import (
    AdapterError,
    AsamIntError,
    CalibrationError,
    ConfigurationError,
    FileFormatError,
    LimitViolation,
    RangeError,
    ReadOnlyError,
    VirtualWriteError,
)
from .logging import configure_logging
from .models import (
    CalibrationLimits,
    CalibrationValue,
    GeneralConfig,
    LoggingConfig,
    MeasurementChannel,
)


class ECUByteOrder:
    """
    Utility class to decode ECU-specific byte orders into NumPy arrays.
    Supports 16/32/64-bit integers and floats.
    """

    # ------------------------------------------------------------
    # 1) Byte permutation tables
    # ------------------------------------------------------------
    PERMUTATIONS: dict[str, dict[int, list[int]]] = {
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
    def decode(cls, raw: bytes, byteorder: ByteOrder, dtype: str) -> np.ndarray:
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
        BIG_ENDIAN: Legacy-Alias für MSB_FIRST.
        LITTLE_ENDIAN: Legacy-Alias für MSB_LAST.
    """

    MSB_LAST = 0
    MSB_FIRST = 1
    BIG_ENDIAN = MSB_FIRST
    LITTLE_ENDIAN = MSB_LAST


ASAM_BYTEORDER_ALIASES = {
    "LITTLE_ENDIAN": "MSB_LAST",
    "BIG_ENDIAN": "MSB_FIRST",
}

_ASAM_BYTEORDER_BASES = {
    "MSB_FIRST": ByteOrder.MSB_FIRST,
    "MSB_LAST": ByteOrder.MSB_LAST,
    "MSB_FIRST_MSW_LAST": ByteOrder.MSB_FIRST,
    "MSB_LAST_MSW_FIRST": ByteOrder.MSB_LAST,
}

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
    """Liefert den dtype-Schlüssel für einen ASAM-Datentyp und eine Byte-Order."""

    if datatype not in _DATA_TYPES:
        return _DATA_TYPES["ULONG"][byte_order.value]
    return _DATA_TYPES[datatype][byte_order.value]


def normalize_asam_byte_order(value: Any) -> str | None:
    """Normalize byte-order values to canonical ASAM string names.

    Handles:
    - ``ByteOrder`` enum instances
    - ASAM canonical strings: ``"MSB_LAST"``, ``"MSB_FIRST"``, …
    - Legacy aliases: ``"LITTLE_ENDIAN"``, ``"BIG_ENDIAN"``
    - A2L PROTOCOL_LAYER prefix: ``"BYTE_ORDER_MSB_LAST"`` → ``"MSB_LAST"``
    - Integer-coercible values (mapped via :class:`ByteOrder`)
    """

    if isinstance(value, ByteOrder):
        return "MSB_FIRST" if value == ByteOrder.MSB_FIRST else "MSB_LAST"

    if isinstance(value, str):
        key = value.strip().upper().replace("-", "_").replace(" ", "_")
        # Strip the "BYTE_ORDER_" prefix emitted by the A2L parser for PROTOCOL_LAYER entries,
        # e.g. "BYTE_ORDER_MSB_LAST" → "MSB_LAST".
        if key.startswith("BYTE_ORDER_"):
            key = key[len("BYTE_ORDER_") :]
        key = ASAM_BYTEORDER_ALIASES.get(key, key)
        if key in _ASAM_BYTEORDER_BASES:
            return key
        return None

    try:
        return normalize_asam_byte_order(ByteOrder(int(value)))
    except (ValueError, TypeError):
        return None


def byte_order(
    obj: Any,
    mod_common: Any | None = None,
    protocol_layer_parameters: Any | None = None,
) -> str:
    """Ermittle die Byte-Order eines A2L-Objekts.

    Priorität:
    1. ``obj.byteOrder`` (A2L Characteristic / Measurement)
    2. ``mod_common.byteOrder`` (A2L MOD_COMMON)
    3. ``protocol_layer_parameters.byte_order`` (XCP PROTOCOL_LAYER — Fallback)
    4. Default ``"MSB_LAST"``
    """

    obj_byte_order: str | None = obj.byteOrder if hasattr(obj, "byteOrder") else None
    if obj_byte_order is not None:
        return obj_byte_order

    obj_byte_order = mod_common.byteOrder if mod_common is not None and hasattr(mod_common, "byteOrder") else None
    if obj_byte_order is not None:
        return obj_byte_order

    if protocol_layer_parameters is not None and hasattr(protocol_layer_parameters, "byte_order"):
        normalized = normalize_asam_byte_order(protocol_layer_parameters.byte_order)
        if normalized is not None:
            return normalized

    return "MSB_LAST"


def resolve_byte_order(
    obj: Any | None = None,
    mod_common: Any | None = None,
    protocol_layer_parameters: Any | None = None,
) -> "ByteOrder":
    """Resolve the effective :class:`ByteOrder` from any available context.

    This is a free-standing helper that requires no calibration object and can
    be used wherever raw memory images are processed independently of the A2L
    characteristic hierarchy.

    Priority (first non-``None`` result wins):

    1. ``obj.byteOrder`` — A2L Characteristic / Measurement object.
    2. ``mod_common.byteOrder`` — A2L ``MOD_COMMON`` section.
    3. ``protocol_layer_parameters.byte_order`` — XCP ``PROTOCOL_LAYER``
       (handles the ``"BYTE_ORDER_MSB_LAST"`` prefix automatically).
    4. Default: :attr:`ByteOrder.MSB_LAST`.

    Args:
        obj: An A2L pya2l model object with an optional ``byteOrder`` attribute.
        mod_common: The ``MOD_COMMON`` section object, or ``None``.
        protocol_layer_parameters: An :class:`~asamint.adapters.xcp.XcpProtocolLayerParameters`
            instance, or any object with a ``byte_order`` string attribute, or ``None``.

    Returns:
        The resolved :class:`ByteOrder`.

    Example::

        from asamint.core import resolve_byte_order

        bo = resolve_byte_order(
            mod_common=mc.mod_common,
            protocol_layer_parameters=mc.protocol_layer_parameters,
        )
    """

    # 1. A2L object level
    if obj is not None and hasattr(obj, "byteOrder") and obj.byteOrder is not None:
        normalized = normalize_asam_byte_order(obj.byteOrder)
        if normalized is not None:
            return _ASAM_BYTEORDER_BASES.get(normalized, ByteOrder.MSB_LAST)

    # 2. MOD_COMMON
    if mod_common is not None and hasattr(mod_common, "byteOrder") and mod_common.byteOrder is not None:
        normalized = normalize_asam_byte_order(mod_common.byteOrder)
        if normalized is not None:
            return _ASAM_BYTEORDER_BASES.get(normalized, ByteOrder.MSB_LAST)

    # 3. XCP PROTOCOL_LAYER
    if protocol_layer_parameters is not None and hasattr(protocol_layer_parameters, "byte_order"):
        normalized = normalize_asam_byte_order(protocol_layer_parameters.byte_order)
        if normalized is not None:
            return _ASAM_BYTEORDER_BASES.get(normalized, ByteOrder.MSB_LAST)

    return ByteOrder.MSB_LAST


__all__ = [
    "ByteOrder",
    "ECUByteOrder",
    "get_data_type",
    "normalize_asam_byte_order",
    "byte_order",
    "resolve_byte_order",
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
    "DeprecatedAlias",
]

_DEPRECATED_ALIASES: dict[str, DeprecatedAlias] = {}


def __getattr__(name: str) -> object:
    return deprecated_getattr(name, _DEPRECATED_ALIASES, globals(), __name__)


def __dir__() -> list[str]:
    return deprecated_dir(_DEPRECATED_ALIASES, globals())
