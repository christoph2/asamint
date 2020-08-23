#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020 by Christoph Schueler <cpu12.gems.googlemail.com>

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
__email__ = 'cpu12.gems@googlemail.com'

from lxml.etree import (Comment, Element, ElementTree, DTD, SubElement, XMLSchema, parse, tounicode)
from lxml import etree

from asamint.utils import create_elem

class Creator:

    def __init__(self, session_obj):
        self.session_obj = session_obj
        self.sub_trees = {}
        self.root = self._toplevel_boilerplate()

        self.on_init()

        self.tree = ElementTree(self.root)

    def on_init(self):
        raise NotImplementedError()

    @property
    def query(self):
        return self.session_obj.query

    def output_1darray(self, elem, name = None, values = [], numeric = True):
        if name:
            cont = create_elem(elem, name)
        else:
            cont = elem
        if numeric:
            tag = "V"
        else:
            tag = "VT"
        for value in values:
            create_elem(cont, tag, text = str(value))

    @staticmethod
    def common_elements(elem, short_name, long_name = None, category = None):
        create_elem(elem, "SHORT-NAME", short_name)
        if long_name:
            create_elem(elem, "LONG-NAME", long_name)
        if category:
            create_elem(elem, "CATEGORY", category)
