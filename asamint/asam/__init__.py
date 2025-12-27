#!/usr/bin/env python
""" """

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
__author__ = "Christoph Schueler"

import os
import time
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

import numpy as np
from pya2l import DB, model
from pya2l.api.inspect import (
    CompuMethod,
    Group,
    ModCommon,
    ModPar,
    VariantCoding,
    asam_type_size,
)

# from . epk import Epk
from asamint.config import get_application
from asamint.utils import current_timestamp


def create_xcp_master():
    from pyxcp.master import Master

    from asamint.config import get_application

    app = get_application()
    xcp_config = app.xcp
    master = Master(
        xcp_config.transport.layer,
        config=xcp_config,
        # policy=policy, transport_layer_interface=transport_layer_interface
    )
    return master


@dataclass
class Group:
    name: str
    sub_groups: list[Group] = field(default_factory=list)


class Directory:
    """Maintains A2L FUNCTION and  GROUP hierachy."""

    def __init__(self, session):
        self.session = session
        self.group_by_name = {
            g.groupName: g for g in self.session.query(model.Group).all()
        }
        self.function_by_name = {
            f.name: f for f in self.session.query(model.Function).all()
        }

    def get_group(self, name: str):
        return self.group_by_name.get(name)

    def get_function(self, name: str):
        return self.function_by_name.get(name)


class AsamMC:
    """
    Parameters
    ----------

    Note: if `mdf_filename` is None, automatic filename generation kicks in and the file gets written
    to `measurements/` sub-directory.

    The other consequence is ...

    Also note the consequences:
        - Filename generation means always create a new file.
        - If `mdf_filename` is not None, **always overwrite** file.
    """

    EXPERIMENT_PARAMETER_MAP = {
        #                           Type     Req'd   Default
        "SUBJECT": (str, True, ""),
        "DESCRIPTION": (str, False, ""),  # Long description, used as header comment.
        "SHORTNAME": (str, True, ""),  # Contributes to filename generation.
    }

    SUB_DIRS = {  # Could be made cofigurable.
        "measurements": "measurements",
        "parameters": "parameters",
        "hexfiles": "hexfiles",
        "logs": "logs",
        "code": "code",
    }

    def __init__(self, *args, **kws):
        self.config = get_application()
        self.logger = self.config.log

        self.shortname = self.config.general.shortname
        self.a2l_encoding = self.config.general.a2l_encoding
        self.a2l_dynamic = self.config.general.a2l_dynamic
        self.a2l_file = self.config.general.a2l_file
        self.author = self.config.general.author
        self.company = self.config.general.company
        self.department = self.config.general.department
        self.project = self.config.general.project
        self.master_hexfile = self.config.general.master_hexfile
        self.master_hexfile_type = self.config.general.master_hexfile_type

        # Build a compatibility shim for legacy experiment_config using the new config system.
        # This replaces the old external experiment_config dict and provides reasonable defaults
        # sourced from the new traitlets-based config where possible.
        try:
            default_subject = f"SUBJ_{self.shortname}" if self.shortname else ""
        except Exception:
            default_subject = ""
        self.experiment_config = {
            # Common experiment metadata
            "SUBJECT": default_subject,
            "DESCRIPTION": "",
            "SHORTNAME": self.shortname or "",
            # MDF-related defaults
            "TIME_SOURCE": "local PC reference timer",
            # Selections; callers can still override by providing names explicitly at runtime
            "MEASUREMENTS": [],
            "FUNCTIONS": [],
            "GROUPS": [],
        }
        self.xcp_master = create_xcp_master()
        self.xcp_connected = False
        if not self.a2l_dynamic:
            self.open_create_session(
                self.a2l_file,
                encoding=self.a2l_encoding,
            )
        self.cond_create_directories()
        self.mod_common = ModCommon.get(self.session)
        self.mod_par = ModPar.get(self.session) if ModPar.exists(self.session) else None
        self.variant_coding = VariantCoding.get(
            self.session, module_name=self.mod_par.modpar.module.name
        )
        self.directory = Directory(self.session)
        self.on_init(self.config, *args, **kws)

    def __del__(self) -> None:
        self.close()

    def cond_create_directories(self) -> None:
        """ """
        SUB_DIRS = [
            "experiments",
            "measurements",
            "parameters",
            "hexfiles",
            "logs",
            "code",
        ]
        for dir_name in SUB_DIRS:
            if not os.access(dir_name, os.F_OK):
                self.logger.info(f"Creating directory {dir_name!r}")
                os.mkdir(dir_name)

    def open_create_session(self, a2l_file, encoding="latin-1"):
        db = DB()
        self.opened = False
        self.session = db.open_create(a2l_file, encoding=encoding, local=True)
        self.opened = True

    def on_init(self, config, *args, **kws):
        pass

    def loadConfig(self, project_config, experiment_config):
        """Load configuration data."""

    def sub_dir(self, name) -> Path:
        return Path(self.SUB_DIRS.get(name))

    def generate_filename(self, extension, extra=None):
        """Automatically generate filename from configuration plus timestamp."""
        project = self.shortname
        subject = f"SUBJ_{self.shortname}"  # self.experiment_config.get("SHORTNAME")
        if extra:
            return f"{project}_{subject}{current_timestamp()}_{extra}{extension}"
        else:
            return f"{project}_{subject}{current_timestamp()}{extension}"

    def xcp_connect(self):
        if not self.xcp_connected:
            if self.xcp_master is None:
                self.xcp_master = create_xcp_master()
            self.xcp_master.connect()
            self.xcp_connected = True

    def close(self):
        if getattr(self, "xcp_connected", False) and self.xcp_master:
            try:
                self.xcp_master.disconnect()
            finally:
                self.xcp_master.close()
                self.xcp_connected = False
                self.xcp_master = None
        if getattr(self, "opened", False):
            self.session.close()
            self.opened = False

    @property
    def query(self):
        return self.session.query

    def byte_order(self, obj):
        """Get byte-order for A2L element.

        Parameters
        ----------
        obj: (`AxisPts` | `AxisDescr` | `Measurement` | `Characteristic`) instance.

        Returns
        -------
        `ByteOrder`:
            If element has no BYTE_ORDER, lookup MOD_COMMON else ByteOrder.BIG_ENDIAN
        """
        return (
            ByteOrder.BIG_ENDIAN
            if obj.byteOrder
            or self.mod_common.byteOrder in ("MSB_FIRST", "LITTLE_ENDIAN")
            else ByteOrder.LITTLE_ENDIAN
        )

    def _numpy_dtype_for_asam(self, datatype: str, bo: Any) -> np.dtype:
        """Map ASAM data types to numpy dtypes.

        Parameters
        ----------
        datatype: str
            ASAM data type name (e.g. 'UBYTE', 'FLOAT32_IEEE')
        bo: ByteOrder or Any
            Byte order to use.

        Returns
        -------
        np.dtype:
        """
        endian = "<" if bo == ByteOrder.LITTLE_ENDIAN else ">"
        match datatype:
            case "UBYTE":
                return np.dtype(endian + "u1")
            case "SBYTE":
                return np.dtype(endian + "i1")
            case "UWORD":
                return np.dtype(endian + "u2")
            case "SWORD":
                return np.dtype(endian + "i2")
            case "ULONG":
                return np.dtype(endian + "u4")
            case "SLONG":
                return np.dtype(endian + "i4")
            case "A_UINT64":
                return np.dtype(endian + "u8")
            case "A_INT64":
                return np.dtype(endian + "i8")
            case "FLOAT32_IEEE":
                return np.dtype(endian + "f4")
            case "FLOAT64_IEEE":
                return np.dtype(endian + "f8")
            case _:
                # Fallback: treat as 32-bit unsigned
                return np.dtype(endian + "u4")

    def acquire_via_pyxcp(
        self,
        master: Any,
        duration_s: float | None = None,
        samples: int | None = None,
        period_s: float = 0.01,
    ) -> dict[str, Any]:
        """Acquire measurement samples via a pyxcp Master by periodic polling.

        This is a simple polling-based acquisition for compatibility. For
        higher performance consider using DAQ/ODT configuration in pyxcp.

        Returns a dict compatible with save_measurements():
        {"TIMESTAMPS": np.ndarray, <meas_name>: np.ndarray, ...}
        """
        if not hasattr(self, "measurement_variables") or not self.measurement_variables:
            raise ValueError(
                "No measurements selected - call add_measurements() or set MEASUREMENTS in config."
            )

        if (duration_s is None) == (samples is None):
            raise ValueError("Provide either duration_s or samples, but not both")

        # Build per-measurement access info
        meas_info: list[dict[str, Any]] = []
        for m in self.measurement_variables:
            try:
                dtype = self._numpy_dtype_for_asam(m.dataType, self.byte_order(m))
                nbytes = int(asam_type_size(m.dataType))
                addr = m.address
                info = {
                    "name": m.name,
                    "dtype": dtype,
                    "nbytes": nbytes,
                    "address": addr,
                    "bitMask": m.bitMask,
                    "bitOperation": m.bitOperation,
                    "compuMethod": m.compuMethod,
                }
                meas_info.append(info)
            except Exception as e:
                self.logger.error(
                    f"Cannot prepare measurement '{getattr(m, 'name', '?')}': {e}"
                )

        # Determine number of samples
        if samples is None:
            samples = max(1, int(round(duration_s / period_s)))  # type: ignore[arg-type]

        # Buffers
        buffers: dict[str, list[Any]] = {mi["name"]: [] for mi in meas_info}
        ts: list[float] = []

        t0 = time.perf_counter()
        for k in range(samples):
            t_now = time.perf_counter() - t0
            ts.append(t_now)
            for mi in meas_info:
                try:
                    data = master.upload(mi["address"], mi["nbytes"])  # returns bytes
                    val = np.frombuffer(data, dtype=mi["dtype"], count=1)[0]
                    # Apply bit operations
                    if mi["bitMask"] is not None:
                        val = val & mi["bitMask"]
                    bo = mi["bitOperation"]
                    if bo and bo.get("amount"):
                        amount = bo["amount"]
                        if bo.get("direction") == "L":
                            val = val << amount
                        else:
                            val = val >> amount
                    buffers[mi["name"]].append(val)
                except Exception as e:
                    self.logger.error(f"pyxcp upload failed for {mi['name']}: {e}")
                    buffers[mi["name"]].append(np.nan)
            # Sleep remaining time in period
            t_elapsed = time.perf_counter() - t0
            t_target = (k + 1) * period_s
            delay = t_target - t_elapsed
            if delay > 0:
                time.sleep(delay)

        # Return RAW internal values; conversion to physical happens in save_measurements()
        result: dict[str, Any] = {"TIMESTAMPS": np.asarray(ts)}
        for m in self.measurement_variables:
            raw_vals = np.asarray(buffers[m.name])
            result[m.name] = raw_vals
        return result

    def calculate_physical_values(self, internal_values, cm_object):
        """Calculate pyhsical value representation from raw, ECU-internal values.

        Parameters
        ----------
        internal_values: array-like

        cm_object: `CompuMethod` instance

        Returns
        -------
        array-like:
        """
        if (
            cm_object is None
            or isinstance(cm_object, (CompuMethod, str))
            and cm_object
            in (
                "NO_COMPU_METHOD",
                "",
            )
        ):
            return internal_values
        if hasattr(cm_object, "conversionType") and cm_object.conversionType in (
            "IDENTICAL",
            "NO_COMPU_METHOD",
        ):
            return internal_values

        try:
            if hasattr(cm_object, "name"):
                name = cm_object.name
            else:
                name = str(cm_object)

            if name == "NO_COMPU_METHOD":
                return internal_values

            calculator = CompuMethod(self.session, name)
            return calculator.int_to_physical(internal_values)
        except Exception:
            return internal_values


DATA_TYPES = {
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


class ByteOrder(IntEnum):
    LITTLE_ENDIAN = 0
    BIG_ENDIAN = 1


def get_data_type(datatype: str, byte_order: ByteOrder) -> str:
    """ """
    return DATA_TYPES[datatype][byte_order]
