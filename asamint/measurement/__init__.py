#!/usr/bin/env python

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

   All Rights Reserved

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License along
   with this program; if not, write to the Free Software Foundation, Inc.,
   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

   s. FLOSS-EXCEPTION.txt
"""

import csv
import json
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from collections.abc import Iterable

from pya2l import model
from pyxcp.daq_stim import DaqList, DaqRecorder, DaqToCsv  # type: ignore
from pyxcp.master import Master  # type: ignore

from asamint.config import get_application
from asamint.hdf5 import HDF5Creator
from asamint.mdf import MDFCreator

PYXCP_TYPES = {
    "UBYTE": "U8",
    "SBYTE": "I8",
    "UWORD": "U16",
    "SWORD": "I16",
    "ULONG": "U32",
    "SLONG": "I32",
    "A_UINT64": "U64",
    "A_INT64": "I64",
    "FLOAT16_IEEE": "F16",
    "FLOAT32_IEEE": "F32",
    "FLOAT64_IEEE": "F64",
}


def group_measurements(
    session, group_name: str, exclude: Optional[Union[list[str], set[str]]] = None
) -> list[tuple[str, int, int, str]]:
    result = []
    if exclude:
        exclude = set(exclude)
    else:
        exclude = set()
    res = session.query(model.Group).filter(model.Group.groupName == group_name).first()
    for meas_name in res.ref_measurement.identifier:
        if meas_name in exclude:
            continue
        meas = (
            session.query(model.Measurement)
            .filter(model.Measurement.name == meas_name)
            .first()
        )
        result.append(
            (
                meas_name,
                meas.ecu_address.address,
                (
                    meas.ecu_address_extension.extension
                    if meas.ecu_address_extension
                    else 0
                ),
                PYXCP_TYPES[meas.datatype],
            )
        )
    return result


def resolve_measurements_by_names(
    session,
    names: Iterable[str],
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> list[tuple[str, int, int, str]]:
    """
    Resolve a list of A2L measurement names to pyXCP DAQ measurement tuples.

    Returns list of tuples: (name, address, extension, type_str)
    Unknown names are skipped.
    """
    result: list[tuple[str, int, int, str]] = []
    if exclude:
        exclude = set(exclude)
    else:
        exclude = set()
    for meas_name in names:
        if meas_name in exclude:
            continue
        meas = (
            session.query(model.Measurement)
            .filter(model.Measurement.name == meas_name)
            .first()
        )
        if not meas:
            # skip unknown
            continue
        # Some A2L may not define address extension
        ext = meas.ecu_address_extension.extension if meas.ecu_address_extension else 0
        dtype = PYXCP_TYPES.get(meas.datatype)
        if not dtype:
            # Fallback for unlisted types (treat like U32)
            dtype = "U32"
        result.append((meas_name, meas.ecu_address.address, ext, dtype))
    return result


def names_from_group(
    session,
    group_name: str,
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> list[str]:
    """
    Return measurement names contained in a given A2L Group.

    Unknown/missing group returns an empty list.
    """
    names: list[str] = []
    try:
        if exclude:
            exclude_set = set(exclude)
        else:
            exclude_set = set()
        res = (
            session.query(model.Group)
            .filter(model.Group.groupName == group_name)
            .first()
        )
        if not res:
            return names
        for meas_name in res.ref_measurement.identifier:
            if meas_name in exclude_set:
                continue
            names.append(meas_name)
    except Exception:
        # be permissive; return what we have
        pass
    return names


def daq_list_from_names(
    session,
    list_name: str,
    event_num: int,
    stim: bool,
    enable_timestamps: bool,
    names: Iterable[str],
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> DaqList:
    """Create a DaqList from explicit measurement names.

    The address, extension, and type are looked up from the A2L database.
    Unknown names are ignored.
    """
    meas = resolve_measurements_by_names(session, names, exclude)
    return DaqList(
        name=list_name,
        event_num=event_num,
        stim=stim,
        enable_timestamps=enable_timestamps,
        measurements=meas,
    )


def daq_list_from_group(
    session,
    list_name: str,
    event_num: int,
    stim: bool,
    enable_timestamps: bool,
    group_name: str,
    exclude: Optional[Union[list[str], set[str]]] = None,
) -> DaqList:
    """
        DaqList(
        name="pwm_stuff",
        event_num=2,
        stim=False,
        enable_timestamps=True,
        measurements=[
            ("channel1", 0x1BD004, 0, "F32"),
            ("period", 0x001C0028, 0, "F32"),
            ("channel2", 0x1BD008, 0, "F32"),
            ("PWMFiltered", 0x1BDDE2, 0, "U8"),
            ("PWM", 0x1BDDDF, 0, "U8"),
            ("Triangle", 0x1BDDDE, 0, "I8"),
        ],
        priority=0,
        prescaler=1,
    ),
    """
    grp_measurements = group_measurements(session, group_name, exclude)
    return DaqList(
        name=list_name,
        event_num=event_num,
        stim=stim,
        enable_timestamps=enable_timestamps,
        measurements=grp_measurements,
    )


def build_daq_lists(
    session,
    groups: list[dict[str, Any]],
) -> list[DaqList]:
    """
    Build multiple DaqList objects from a group specification.

    Each group dict supports two modes:
      - Explicit names: {"name": str, "event_num": int, "variables": [str,...], "stim": bool=False, "enable_timestamps": bool=True}
      - A2L Group:      {"name": str, "event_num": int, "group_name": str, "stim": bool=False, "enable_timestamps": bool=True}

    Returns a list of DaqList ready to be passed to pyXCP for allocation.
    """
    result: list[DaqList] = []
    for g in groups:
        list_name = g.get("name")
        if not list_name:
            raise ValueError("Group spec requires 'name'.")
        event_num = g.get("event_num")
        if event_num is None:
            raise ValueError(f"Group '{list_name}' requires 'event_num'.")
        stim = bool(g.get("stim", False))
        enable_ts = bool(g.get("enable_timestamps", True))

        if "variables" in g and g["variables"]:
            dl = daq_list_from_names(
                session,
                list_name=list_name,
                event_num=event_num,
                stim=stim,
                enable_timestamps=enable_ts,
                names=g["variables"],
                exclude=g.get("exclude"),
            )
        elif "group_name" in g and g["group_name"]:
            dl = daq_list_from_group(
                session,
                list_name=list_name,
                event_num=event_num,
                stim=stim,
                enable_timestamps=enable_ts,
                group_name=g["group_name"],
                exclude=g.get("exclude"),
            )
        else:
            raise ValueError(
                f"Group '{list_name}' must define either 'variables' or 'group_name'."
            )
        result.append(dl)
    return result


# -------------------------------
# High-level acquisition (MVP)
# -------------------------------
