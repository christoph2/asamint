#!/usr/bin/env python
"""
Parse (transport-layer specific) command line parameters
and create a XCP master instance.
"""

import warnings
from dataclasses import dataclass
from typing import Any, List, Optional

from asamint.config import create_application, get_application
from asamint.measurement import finalize_from_daq_csv

warnings.simplefilter("always")


@dataclass
class Option:
    short_opt: str
    long_opt: str = ""
    dest: str = ""
    help: str = ""
    type: str = ""
    default: str = ""


class FakeParser:

    options: list[Option] = []

    def add_argument(
        self,
        short_opt: str,
        long_opt: str = "",
        dest: str = "",
        help: str = "",
        type: str = "",
        default: str = "",
    ):
        warnings.warn(
            "Argument parser extension is currently not supported.",
            DeprecationWarning,
            2,
        )
        self.options.append(Option(short_opt, long_opt, dest, help, type, default))


class ArgumentParser:
    def __init__(self, callout=None, *args, **kws):
        self._parser = FakeParser()
        if callout is not None:
            warnings.warn(
                "callout  argument is currently not supported.", DeprecationWarning, 2
            )

    def run(self, policy=None, transport_layer_interface=None):
        self.application = create_application(self.parser.options)
        # master = Master(
        #    application.transport.layer, config=application, policy=policy, transport_layer_interface=transport_layer_interface
        # )
        master = {"hello": "world! 2.0.0-alpha.14 (development)"}
        return master

    @property
    def parser(self):
        return self._parser


def finalize_daq_csv(
    csv_files: list[str],
    *,
    csv_out: Optional[str] = None,
    hdf5_out: Optional[str] = None,
    units: Optional[dict[str, Optional[str]]] = None,
    project_meta: Optional[dict[str, Any]] = None,
):
    """CLI-friendly wrapper to finalize DAQ CSV outputs into CSV/HDF5 with metadata."""

    if project_meta is None:
        app = get_application()
        project_meta = {
            "author": getattr(app.general, "author", None),
            "company": getattr(app.general, "company", None),
            "department": getattr(app.general, "department", None),
            "project": getattr(app.general, "project", None),
            "shortname": getattr(app.general, "shortname", None),
            "subject": getattr(app.general, "shortname", None),
            "time_source": "local PC reference timer",
        }

    return finalize_from_daq_csv(
        csv_files,
        units=units,
        project_meta=project_meta,
        csv_out=csv_out,
        hdf5_out=hdf5_out,
    )
