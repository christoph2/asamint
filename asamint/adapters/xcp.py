from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Any

from pyxcp.checksum import check as _checksum
from pyxcp.cmdline import ArgumentParser
from pyxcp.cpp_ext.cpp_ext import McObject as PyxcpMcObject
from pyxcp.daq_stim import DaqList, DaqRecorder, DaqToCsv
from pyxcp.daq_stim.optimize import make_continuous_blocks as _make_continuous_blocks

try:  # pragma: no cover - optional recorder extras
    from pyxcp.recorder.decoder import XcpLogFileDecoder
except ImportError:
    try:
        from pyxcp.recorder import XcpLogFileDecoder  # type: ignore
    except ImportError:  # pragma: no cover - absent recorder support

        class XcpLogFileDecoder:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                msg = "pyxcp recorder support is unavailable; install pyxcp with recorder extras."
                raise ImportError(msg)


try:  # pragma: no cover - optional HDF5 policy
    from pyxcp.transport.hdf5_policy import Hdf5OnlinePolicy
except ImportError:  # pragma: no cover - absent HDF5 policy

    class Hdf5OnlinePolicy:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            msg = (
                "pyxcp Hdf5OnlinePolicy is unavailable; install pyxcp with HDF5 extras."
            )
            raise ImportError(msg)


try:  # pragma: no cover - optional utils
    from pyxcp.utils.cli import StrippingParser
except ImportError:  # pragma: no cover - provide minimal fallback

    class StrippingParser:
        def __init__(self, parser: argparse.ArgumentParser | None = None) -> None:
            self._parser = parser or argparse.ArgumentParser(add_help=False)

        def parse_and_strip(self) -> Any:
            args, remaining = self._parser.parse_known_args()
            import sys

            sys.argv = [sys.argv[0], *remaining]
            return args

        def add_argument(self, *args: Any, **kwargs: Any) -> Any:
            return self._parser.add_argument(*args, **kwargs)


McObject = PyxcpMcObject


def create_master(xcp_config: Any) -> Any:
    """Instantiate a pyXCP Master using the provided configuration."""

    from pyxcp.master import Master

    return Master(xcp_config.transport.layer, config=xcp_config)


def compute_checksum(block: bytes | bytearray, checksum_type: str) -> int:
    """Compute a checksum using pyXCP's checksum helper."""

    return _checksum(block, checksum_type)


def make_continuous_blocks(blocks: Sequence[Any]) -> list[Any]:
    """Merge adjacent memory blocks using pyXCP optimization helper."""

    return _make_continuous_blocks(blocks)


# MAP_TO_ARRAY is used by recorder examples; gracefully fall back if pyarrow extras are missing.
try:  # pragma: no cover - optional recorder extras
    from pyxcp.recorder.converter import MAP_TO_ARRAY
except ImportError:  # pragma: no cover - dependency (pyarrow) may be missing
    MAP_TO_ARRAY = {
        "U8": "B",
        "I8": "b",
        "U16": "H",
        "I16": "h",
        "U32": "L",
        "I32": "l",
        "U64": "Q",
        "I64": "q",
        "F32": "f",
        "F64": "d",
        "F16": "f",
        "BF16": "f",
    }


__all__ = [
    "McObject",
    "ArgumentParser",
    "DaqList",
    "DaqRecorder",
    "DaqToCsv",
    "MAP_TO_ARRAY",
    "StrippingParser",
    "XcpLogFileDecoder",
    "Hdf5OnlinePolicy",
    "compute_checksum",
    "create_master",
    "make_continuous_blocks",
]
