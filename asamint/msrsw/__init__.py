#!/usr/bin/env python
"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2024 by Christoph Schueler <cpu12.gems.googlemail.com>

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

__author__ = """Christoph Schueler"""
__email__ = "cpu12.gems@googlemail.com"

import os
from pprint import pprint

import numpy as np
import pya2l.model as model
from lxml import etree  # nosec

from asamint.utils import slicer
from asamint.utils.xml import create_elem


class MSRMixIn:
    """ """

    DOCTYPE = None
    DTD = None
    EXTENSION = None

    def __init__(self, *args, **kws):
        self.sub_trees = {}
        super().__init__(*args, **kws)

    def write_tree(self, file_name):
        """ """
        print("validating...", file_name)
        # self.validate()
        file_name = self.generate_filename(self.EXTENSION)
        file_name = self.sub_dir("parameters") / file_name
        self.logger.info(f"Saving tree to {file_name}")
        with open(file_name, "wb") as of:
            of.write(
                etree.tostring(
                    self.root,
                    encoding="UTF-8",
                    pretty_print=True,
                    xml_declaration=True,
                    doctype=self.DOCTYPE,
                )
            )

    def validate(self):
        """ """
        dtd = etree.DTD(self.DTD)
        if not dtd.validate(self.root):
            pprint(dtd.error_log)

    def output_1darray(self, elem, name=None, values=[], numeric=True, paired=False):
        """ """
        if name:
            cont = create_elem(elem, name)
        else:
            cont = elem
        if numeric:
            tag = "V"
        else:
            tag = "VT"
        if paired:
            if isinstance(values, np.ndarray):
                parts = np.split(values, values.size // 2)
            else:
                parts = slicer(values, 2)
            for part in parts:
                vg = create_elem(cont, "VG")
                create_elem(vg, tag, text=str(part[0]))
                create_elem(vg, tag, text=str(part[1]))
        else:
            for value in values:
                create_elem(cont, tag, text=str(value))

    def sdg(self, parent, name, *elements):
        """Create a Special Data Group.

        Parameters
        ----------
        parent: `etree.Element`

        name: str
            Name of SDG

        elements: list of tuples (tag, text)
        """
        sdg = create_elem(parent, "SDG", attrib={"GID": name})
        for tag, text in elements:
            create_elem(sdg, "SD", text=text, attrib={"GID": tag})

    @staticmethod
    def common_elements(elem, short_name, long_name=None, category=None):
        """ """
        create_elem(elem, "SHORT-NAME", short_name)
        if long_name:
            create_elem(elem, "LONG-NAME", long_name)
        if category:
            create_elem(elem, "CATEGORY", category)

    def msrsw_header(self, category, suffix):
        """ """
        proj = self.query(model.Project).first()
        project_name = proj.name
        project_comment = proj.longIdentifier

        root = etree.Element("MSRSW")
        create_elem(root, "SHORT-NAME", text=f"{project_name}_{suffix}")
        create_elem(root, "CATEGORY", category)
        sw_systems = create_elem(root, "SW-SYSTEMS")
        sw_system = create_elem(sw_systems, "SW-SYSTEM")
        self.common_elements(sw_system, project_name, project_comment)
        self.sub_trees["SW-SYSTEM"] = sw_system
        return root
