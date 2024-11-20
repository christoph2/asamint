#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2024 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import importlib.resources
import sys
from collections import defaultdict
from functools import lru_cache
from io import FileIO
from pathlib import Path


pyver = sys.version_info


_KEYS = frozenset(["dtds", "templates"])

_DATA_FILES = defaultdict(dict)

for key in _KEYS:
    res = importlib.resources.files(f"asamint.data.{key}").iterdir()
    for pp in res:
        # print(key, pp.name)
        _DATA_FILES[key][pp.name] = pp


def get_template(name: str) -> str:
    """
    Retrieves a template file from the 'templates' directory.

    Parameters:
    name (str): The name of the template file to retrieve.

    Returns:
    str: The content of the template file if found, otherwise an empty string.
    """
    TMPs = _DATA_FILES["templates"]

    if name not in TMPs:
        return ""
    else:
        return TMPs[name].read_text()


@lru_cache
def get_dtd(name: str) -> FileIO:
    """
    Retrieves a DTD file from the 'dtds' directory and returns it as a StringIO object.

    Parameters:
    name (str): The name of the DTD file to retrieve.

    Returns:
    StringIO: A StringIO object containing the content of the DTD file if found, otherwise an empty StringIO object.
    """
    DTDs = _DATA_FILES["dtds"]

    if name not in DTDs:
        return FileIO()
    else:
        return FileIO(DTDs[name])


if pyver.major == 3 and pyver.minor <= 9:
    from typing import Optional, Union

    import pkg_resources

    def read_resource_file(package: str, file_name: str, binary: bool = False) -> Optional[Union[str, bytes]]:
        pth = Path(pkg_resources.resource_filename(package, file_name))
        if binary:
            return pth.read_bytes()
        else:
            return pth.read_text()

else:
    import importlib.resources

    def read_resource_file(package: str, file_name: str, binary: bool = False) -> str | bytes | None:
        st0 = Path(file_name).parts[-1]
        file_name = str(Path(file_name).parent).replace("/", ".").replace("\\", ".")
        for item in importlib.resources.files(f"{package}.{file_name}").iterdir():
            st1 = item.parts[-1]
            if st0 == st1:
                if binary:
                    return item.read_bytes()
                else:
                    return item.read_text()
        return None
