#!/usr/bin/env python
"""DAMOS DCM 2.0 format — export and import."""

from __future__ import annotations

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

from pathlib import Path
from typing import Any

from .dcm_exporter import DcmExporter, export_to_dcm
from asamint.calibration import CalibrationData
from asamint.utils.data import read_resource_file
from asamint.utils.templates import do_template_from_text


def import_dcm(source: str | Path, *, encoding: str = "latin-1") -> dict[str, Any]:
    """Parse a DCM 2.0 file or string and return the structured data.

    Parameters
    ----------
    source
        File path (``str`` or ``Path``) to a ``.dcm`` file **or** a raw DCM
        text string.  If *source* is a ``Path`` or points to an existing file
        it is read from disk; otherwise it is treated as inline DCM text.
    encoding
        Character encoding used when reading from a file (default: latin-1).

    Returns
    -------
    dict
        Nested dictionary with keys ``"kopf"``, ``"rumpf"``, and ``"version"``.
    """
    from asamint.damos._dcm_parser import parse_string  # noqa: PLC0415

    path = Path(source) if not isinstance(source, Path) else source
    if path.exists():
        text = path.read_text(encoding=encoding)
    else:
        text = str(source)
    return parse_string(text) or {}


class DCMCreator(CalibrationData):
    """ """

    EXTENSION = ".dcm"
    TEMPLATE = read_resource_file("asamint", "data/templates/dcm.tmpl", binary=False)

    def on_init(self, config, *args, **kws) -> None:
        super().on_init(config, *args, **kws)
        self.loadConfig(config)

    def save(self) -> None:

        namespace = {
            "params": self._parameters,
            "dataset": self.project_config,
            "experiment": self.experiment_config,
        }

        res = do_template_from_text(self.TEMPLATE, namespace, formatExceptions=False, encoding="latin-1")
        file_name = self.generate_filename(self.EXTENSION)
        self.logger.info(f"Saving tree to {file_name}")
        with open(f"{file_name}", "w") as of:
            of.write(res)
