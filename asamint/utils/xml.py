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
__author__  = 'Christoph Schueler'


from decimal import (
        Decimal as D, InvalidOperation
)

from lxml import etree
from lxml.etree import SubElement, Comment


def create_elem(parent, name, text = None, attrib = {}):
    """

    """
    elem = SubElement(parent, name, attrib)
    if text:
        elem.text = text
    return elem

def xml_comment(parent, text):
    """
    """
    parent.append(Comment(text))

def as_numeric(element):
    """Try to convert ELEMENT text to decimal floating-point.
    """
    text = element.text
    try:
        return D(text)
    except InvalidOperation:
        return text
