#!/usr/bin/env python
"""
Parse (transport-layer specific) command line parameters
and create a XCP master instance.
"""

import warnings
from dataclasses import dataclass
from typing import List

from asamint.config import create_application


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
            warnings.warn("callout  argument is currently not supported.", DeprecationWarning, 2)

    def run(self, policy=None, transport_layer_interface=None):
        application = create_application(self.parser.options)
        # master = Master(
        #    application.transport.layer, config=application, policy=policy, transport_layer_interface=transport_layer_interface
        # )
        master = {"hello": "world! 2.0.0-alpha.14 (development)"}
        return master

    @property
    def parser(self):
        return self._parser
