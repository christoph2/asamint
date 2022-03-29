#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""XML helper classes and functions."""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021 by Christoph Schueler <cpu12.gems.googlemail.com>

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


from decimal import Decimal as D, InvalidOperation

from lxml import etree
from lxml.etree import SubElement, Comment, _Comment, _ProcessingInstruction


def element_name(tree):
    """ """
    return tree.tag.lower().replace("-", "_")


def create_elem(parent, name: str, text: str = None, attrib: dict = None):
    """ """
    elem = SubElement(parent, name, attrib or {})
    if text:
        elem.text = text
    return elem


def xml_comment(parent, text: str):
    """Add XML comment to an element."""
    parent.append(Comment(text))


def as_numeric(element):
    """Try to convert ELEMENT text to decimal floating-point."""
    text = element.text
    try:
        return D(text)
    except InvalidOperation:
        return text


class XMLTraversor:
    """Visitable XML tree."""

    def __init__(self, file_name):
        self.doc = etree.parse(file_name)
        self.doc_root = self.doc.getroot()

    @property
    def root(self):
        return self.doc_root

    def generic_visit(self, tree):
        children = tree.getchildren()
        if not children:
            if not isinstance(tree.text, str):
                return None
            else:
                return {element_name(tree): tree.text}
        result = []
        for child in children:
            result.append(self.visit(child))
        return {element_name(tree): result}

    def visit(self, tree):
        if not isinstance(tree.tag, str):
            if isinstance(tree, _Comment):
                return {"_com_ment_": str(tree)}
            elif isinstance(tree, _ProcessingInstruction):
                print("PI", tree.text, tree.target)
                return {
                    "ProcessingInstruction": (
                        tree.text,
                        tree.target,
                    )
                }
            else:
                raise TypeError("Not handled node type '{}'".format(type(tree)))
                return
        method = "visit_{}".format(tree.tag.lower().replace("-", "_"))
        visitor = getattr(self, method, self.generic_visit)
        return visitor(tree)

    def visit_children(self, tree):
        result = []
        for child in tree.getchildren():
            result.append(self.visit(child))
        return result

    def run(self):
        return self.visit(self.root)
