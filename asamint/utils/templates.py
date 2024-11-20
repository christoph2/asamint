#!/usr/bin/env python

__copyright__ = """
    pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2009-2024 by Christoph Schueler <github.com/Christoph2,
                                        cpu12.gems@googlemail.com>

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

__author__ = "Christoph Schueler"
__version__ = "0.9"

##
## Convenience functions for Mako Templates.
##

from io import StringIO

from mako import exceptions
from mako.runtime import Context
from mako.template import Template  # nosec


# from csstuff import strings


def indent_text(text: str, left_margin: int = 0) -> str:
    """
    Indents the given text with the specified left margin.

    Args:
        text (str): The input text.
        left_margin (int, optional): The left margin. Defaults to 0.

    Returns:
        str: The indented text.
    """
    return "\n".join([f"{' ' * left_margin}{line}" if line else "" for line in text.splitlines()])


def do_template(
    tmpl: str,
    namespace: str | None = None,
    leftMargin: int = 0,
    rightMargin: int = 80,
    formatExceptions: bool = True,
    encoding: str = "utf-8",
) -> str:
    namespace = namespace or {}
    buf = StringIO()
    ctx = Context(buf, **namespace)
    try:
        tobj = Template(filename=tmpl, output_encoding=encoding, format_exceptions=formatExceptions)  # nosec
        tobj.render_context(ctx)
    except Exception:
        print(exceptions.text_error_template().render())
        return None
    # return strings.reformat(buf.getvalue(), leftMargin, rightMargin)
    return buf.getvalue()


def do_template_from_text(
    tmpl: str,
    namespace: str = None,
    leftMargin: int = 0,
    rightMargin: int = 80,
    formatExceptions: bool = True,
    encoding: str = "utf-8",
) -> str:
    namespace = namespace or {}
    buf = StringIO()
    ctx = Context(buf, **namespace)
    try:
        tobj = Template(text=tmpl, output_encoding=encoding, format_exceptions=formatExceptions)  # nosec
        tobj.render_context(ctx)
    except Exception:
        print(exceptions.text_error_template().render())
        return None
    return indent_text(buf.getvalue(), leftMargin)  # , rightMargin)


def call_def(template, definition, *args, **kwargs):
    return template.get_def(definition).render(*args, **kwargs)
