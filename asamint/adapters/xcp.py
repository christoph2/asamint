from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pyxcp.checksum import check as _checksum
from pyxcp.cmdline import ArgumentParser
from pyxcp.cpp_ext.cpp_ext import McObject as PyxcpMcObject
from pyxcp.daq_stim import DaqList, DaqRecorder, DaqToCsv
from pyxcp.daq_stim.optimize import make_continuous_blocks as _make_continuous_blocks
from pyxcp.transport.hdf5_policy import Hdf5OnlinePolicy

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


__all__ = [
    "McObject",
    "ArgumentParser",
    "DaqList",
    "DaqRecorder",
    "DaqToCsv",
    "Hdf5OnlinePolicy",
    "compute_checksum",
    "create_master",
    "make_continuous_blocks",
]
