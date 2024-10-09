#!/usr/bin/env python

__copyright__ = """
    pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2009-20210 by Christoph Schueler <cpu12.gems@googlemail.com>

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
"""

import io
import json
import pathlib
from collections.abc import MutableMapping

import toml


def read_configuration(conf):
    """Read a configuration file either in TOML format."""
    if conf:
        if isinstance(conf, io.IOBase):
            conf = toml.load(conf)
            return conf
        if isinstance(conf, dict):
            return dict(conf)
        pth = pathlib.Path(conf.name)
        suffix = pth.suffix.lower()
        if suffix == ".json":
            reader = json
        elif suffix == ".toml":
            reader = toml
        else:
            reader = None
        if reader:
            return reader.loads(conf.read())
        else:
            return {}
    else:
        return {}


class Configuration(MutableMapping):
    """ """

    def __init__(self, parameters, config):
        self.parameters = parameters
        self.config = config
        for key, (tp, required, default) in self.parameters.items():
            if key in self.config:
                if not isinstance(self.config[key], tp):
                    raise TypeError(f"Parameter {key} requires {tp}")
            else:
                if required:
                    raise AttributeError(f"{key} must be specified in config!")
                else:
                    self.config[key] = default

    def __getitem__(self, key):
        return self.config[key]

    def __setitem__(self, key, value):
        self.config[key] = value

    def __delitem__(self, key):
        del self.config[key]

    def __iter__(self):
        return iter(self.config)

    def __len__(self):
        return len(self.config)

    def __repr__(self):
        return f"{self.config}"

    __str__ = __repr__
