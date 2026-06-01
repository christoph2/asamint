import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Optional

from pyxcp.checksum import check as _checksum
from pyxcp.cmdline import ArgumentParser
from pyxcp.cpp_ext.cpp_ext import McObject as PyxcpMcObject
from pyxcp.daq_stim import DaqList, DaqRecorder, DaqToCsv
from pyxcp.daq_stim.optimize import make_continuous_blocks as _make_continuous_blocks


@dataclass(slots=True)
class XcpTimeouts:
    t1: int
    t2: int
    t3: int
    t4: int
    t5: int
    t6: int
    t7: int


@dataclass(slots=True)
class BlockModeMaster:
    """Master Block Mode parameters (MAX_BS and MIN_ST from AML MASTER struct)."""

    max_bs: int
    """Maximum block size (MAX_BS): maximum number of command packets the master may send without waiting."""
    min_st: int
    """Minimum separation time (MIN_ST): minimum time in 100 µs units between two command packets."""

    @classmethod
    def from_raw(cls, raw: list[int]) -> "BlockModeMaster":
        """Parse from AML-decoded list ``[MAX_BS, MIN_ST]``."""
        return cls(max_bs=int(raw[0]), min_st=int(raw[1]))


@dataclass(slots=True)
class BlockMode:
    """BLOCK entry of COMMUNICATION_MODE_SUPPORTED (AML taggedstruct BLOCK)."""

    slave: bool = False
    """True if Slave Block Mode is supported."""
    master: Optional[BlockModeMaster] = None
    """Master Block Mode parameters, or None if not supported."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BlockMode":
        """Parse from AML-decoded dict, e.g. ``{'MASTER': [43, 0], 'SLAVE': True}``."""
        slave: bool = bool(data.get("SLAVE", False))
        master_raw = data.get("MASTER")
        master: Optional[BlockModeMaster] = BlockModeMaster.from_raw(master_raw) if master_raw is not None else None
        return cls(slave=slave, master=master)


@dataclass(slots=True)
class CommunicationModeSupported:
    """Decoded representation of the AML ``COMMUNICATION_MODE_SUPPORTED`` taggedunion.

    AML definition::

        "COMMUNICATION_MODE_SUPPORTED" taggedunion {
          "BLOCK" taggedstruct {
            "SLAVE";
            "MASTER" struct { uchar; uchar; };
          };
          "INTERLEAVED" uchar;
        };

    Example dict produced by the A2L parser::

        {'BLOCK': {'MASTER': [43, 0], 'SLAVE': True}}
    """

    block: Optional[BlockMode] = None
    """BLOCK mode configuration, or None if not present."""
    interleaved: Optional[int] = None
    """INTERLEAVED queue size, or None if not present."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CommunicationModeSupported":
        """Build a :class:`CommunicationModeSupported` from an AML-decoded dict.

        Args:
            data: Raw dict as returned by the A2L parser, e.g.
                  ``{'BLOCK': {'MASTER': [43, 0], 'SLAVE': True}}``.

        Returns:
            Populated :class:`CommunicationModeSupported` instance.
        """
        block: Optional[BlockMode] = None
        interleaved: Optional[int] = None

        block_raw = data.get("BLOCK")
        if block_raw is not None:
            block = BlockMode.from_dict(block_raw)

        interleaved_raw = data.get("INTERLEAVED")
        if interleaved_raw is not None:
            interleaved = int(interleaved_raw)

        return cls(block=block, interleaved=interleaved)


class CalPagResource(IntEnum):
    """CAL/PAG resource activity level (AML enum with three states)."""

    NOT_ACTIVE = 0
    ACTIVE = 1
    GETTER_ONLY = 2  # Setter methods not allowed


class ResourceActivity(IntEnum):
    """Generic on/off resource flag used for DAQ, STIM, and PGM resources."""

    NOT_ACTIVE = 0
    ACTIVE = 1


class ReadAccess(IntEnum):
    """Read-access permission for a memory page (AML MEMORY_ACCESS enum)."""

    NOT_ALLOWED = 0
    ALLOWED = 1


class WriteAccess(IntEnum):
    """Write-access permission for a memory page (AML MEMORY_ACCESS enum)."""

    NOT_ALLOWED = 0
    ALLOWED = 1


@dataclass(slots=True)
class MemoryAccess:
    """One MEMORY_ACCESS entry inside an ECU state (AML block MEMORY_ACCESS).

    AML definition::

        block "MEMORY_ACCESS" struct {
          uchar;  /* SEGMENT_NUMBER */
          uchar;  /* PAGE_NUMBER    */
          enum { "READ_ACCESS_NOT_ALLOWED"=0, "READ_ACCESS_ALLOWED"=1 };
          enum { "WRITE_ACCESS_NOT_ALLOWED"=0, "WRITE_ACCESS_ALLOWED"=1 };
        };
    """

    segment_number: int
    page_number: int
    read_access: ReadAccess
    write_access: WriteAccess

    @classmethod
    def from_raw(cls, raw: list[int]) -> "MemoryAccess":
        """Parse from AML-decoded list ``[segment_number, page_number, read_access, write_access]``."""
        return cls(
            segment_number=int(raw[0]),
            page_number=int(raw[1]),
            read_access=ReadAccess(int(raw[2])),
            write_access=WriteAccess(int(raw[3])),
        )


@dataclass(slots=True)
class EcuState:
    """One STATE block inside ECU_STATES (AML block STATE).

    AML definition (abbreviated)::

        block "STATE" struct {
          uchar;       /* STATE_NUMBER                */
          char[100];   /* STATE_NAME                  */
          taggedstruct { "ECU_SWITCHED_TO_DEFAULT_PAGE"; };
          enum { "NOT_ACTIVE"=0, "ACTIVE"=1, "GETTER_ONLY"=2 };  /* CAL/PAG */
          enum { "NOT_ACTIVE"=0, "ACTIVE"=1 };                    /* DAQ     */
          enum { "NOT_ACTIVE"=0, "ACTIVE"=1 };                    /* STIM    */
          enum { "NOT_ACTIVE"=0, "ACTIVE"=1 };                    /* PGM     */
          taggedstruct { (block "MEMORY_ACCESS" struct { ... })*; };
        };

    The A2L parser represents a STATE entry as a list::

        [state_number, state_name,
         {'ECU_SWITCHED_TO_DEFAULT_PAGE': True},
         cal_pag_int, daq_int, stim_int, pgm_int,
         {'MEMORY_ACCESS': [[seg, page, read, write], ...]}]
    """

    state_number: int
    """Numeric state identifier (STATE_NUMBER, uchar)."""
    state_name: str
    """Human-readable state name (STATE_NAME, char[100])."""
    ecu_switched_to_default_page: bool
    """True when the ECU_SWITCHED_TO_DEFAULT_PAGE flag is present in the optional taggedstruct."""
    cal_pag_resource: CalPagResource
    """CAL/PAG resource activity."""
    daq_resource: ResourceActivity
    """DAQ resource activity."""
    stim_resource: ResourceActivity
    """STIM resource activity."""
    pgm_resource: ResourceActivity
    """PGM resource activity."""
    memory_accesses: list[MemoryAccess] = field(default_factory=list)
    """List of MEMORY_ACCESS entries (may be empty)."""

    @classmethod
    def from_raw(cls, raw: list[Any]) -> "EcuState":
        """Parse one STATE entry from an AML-decoded list.

        Args:
            raw: List as produced by the A2L parser for a single STATE block.
                 Expected layout: ``[state_number, state_name, flags_dict,
                 cal_pag_int, daq_int, stim_int, pgm_int, memory_dict]``.
                 Trailing fields may be absent for older A2L files.

        Returns:
            Populated :class:`EcuState` instance.
        """
        state_number: int = int(raw[0])
        state_name: str = str(raw[1])

        flags: dict[str, Any] = raw[2] if len(raw) > 2 and isinstance(raw[2], dict) else {}
        ecu_switched_to_default_page: bool = bool(flags.get("ECU_SWITCHED_TO_DEFAULT_PAGE", False))

        cal_pag_resource = CalPagResource(int(raw[3])) if len(raw) > 3 else CalPagResource.NOT_ACTIVE
        daq_resource = ResourceActivity(int(raw[4])) if len(raw) > 4 else ResourceActivity.NOT_ACTIVE
        stim_resource = ResourceActivity(int(raw[5])) if len(raw) > 5 else ResourceActivity.NOT_ACTIVE
        pgm_resource = ResourceActivity(int(raw[6])) if len(raw) > 6 else ResourceActivity.NOT_ACTIVE

        memory_accesses: list[MemoryAccess] = []
        if len(raw) > 7 and isinstance(raw[7], dict):
            for ma_raw in raw[7].get("MEMORY_ACCESS", []):
                memory_accesses.append(MemoryAccess.from_raw(ma_raw))

        return cls(
            state_number=state_number,
            state_name=state_name,
            ecu_switched_to_default_page=ecu_switched_to_default_page,
            cal_pag_resource=cal_pag_resource,
            daq_resource=daq_resource,
            stim_resource=stim_resource,
            pgm_resource=pgm_resource,
            memory_accesses=memory_accesses,
        )


def ecu_states_from_raw(raw: list[Any]) -> list[EcuState]:
    """Convert the raw A2L-parser output for ECU_STATES into a typed list.

    Args:
        raw: List of STATE entries as returned by the A2L parser. Each entry
             is itself a list matching the layout described in :class:`EcuState`.

    Returns:
        List of :class:`EcuState` instances, preserving order.
    """
    return [EcuState.from_raw(entry) for entry in raw]


@dataclass(slots=True)
class XcpProtocolLayerParameters:
    protocol_layer_version: str
    timeouts: XcpTimeouts
    max_cto: int
    max_dto: int
    byte_order: str
    address_granularity: str
    optional_cmds: set[str] = field(default_factory=set)
    optional_level1_cmds: set[str] = field(default_factory=set)
    seed_and_key_external_function: set[str] = field(default_factory=set)
    ecu_states: list[EcuState] = field(default_factory=list)
    communication_mode_supported: Optional[CommunicationModeSupported] = None


# ---------------------------------------------------------------------------
# Paging types — try to use pyxcp's own definitions; fall back to local ones
# ---------------------------------------------------------------------------

try:
    from pyxcp.types import PagePropertiesInfo
except ImportError:  # pragma: no cover — older pyxcp without PagePropertiesInfo

    @dataclass
    class PagePropertiesInfo:  # type: ignore[no-redef]
        """Decoded page-property flags (fallback definition for older pyxcp).

        Mirrors ``pyxcp.types.PagePropertiesInfo``; kept in sync manually.
        """

        ecu_access_with_xcp: bool
        ecu_access_without_xcp: bool
        xcp_read_access_with_ecu: bool
        xcp_read_access_without_ecu: bool
        xcp_write_access_with_ecu: bool
        xcp_write_access_without_ecu: bool

        @property
        def ecu_access(self) -> bool:
            """True if the ECU can access the page at all."""
            return self.ecu_access_with_xcp or self.ecu_access_without_xcp

        @property
        def xcp_read_access(self) -> bool:
            """True if the XCP master can read from the page at all."""
            return self.xcp_read_access_with_ecu or self.xcp_read_access_without_ecu

        @property
        def xcp_write_access(self) -> bool:
            """True if the XCP master can write to the page at all."""
            return self.xcp_write_access_with_ecu or self.xcp_write_access_without_ecu


try:
    from pyxcp.master.calibration import (
        CAL_PAGE_MODE_ALL,
        CAL_PAGE_MODE_ECU,
        CAL_PAGE_MODE_XCP,
        Calibration as XcpCalibration,
        Page as XcpPage,
        Segment as XcpSegment,
    )
except ImportError:  # pragma: no cover — older pyxcp without full calibration module
    CAL_PAGE_MODE_ECU: int = 0x01
    CAL_PAGE_MODE_XCP: int = 0x02
    CAL_PAGE_MODE_ALL: int = 0x80
    XcpCalibration = None  # type: ignore[assignment,misc]
    XcpPage = None  # type: ignore[assignment,misc]
    XcpSegment = None  # type: ignore[assignment,misc]

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
            msg = "pyxcp Hdf5OnlinePolicy is unavailable; install pyxcp with HDF5 extras."
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


def create_master(config: Any) -> Any:
    """Instantiate a pyXCP Master using the provided configuration."""

    from pyxcp.master import Master

    if hasattr(config, "transport"):
        layer = config.transport.layer
    else:
        # If it's a traitlets Config object, we need to extract the layer from the Transport section
        layer = config.Transport.layer

    mst = Master(layer, config=config)
    mst.__enter__()
    return mst


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
    "CAL_PAGE_MODE_ALL",
    "CAL_PAGE_MODE_ECU",
    "CAL_PAGE_MODE_XCP",
    "DaqList",
    "DaqRecorder",
    "DaqToCsv",
    "MAP_TO_ARRAY",
    "PagePropertiesInfo",
    "StrippingParser",
    "XcpCalibration",
    "XcpLogFileDecoder",
    "XcpPage",
    "XcpSegment",
    "Hdf5OnlinePolicy",
    "compute_checksum",
    "create_master",
    "make_continuous_blocks",
]
