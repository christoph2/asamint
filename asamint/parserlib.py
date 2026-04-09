#!/usr/bin/env python

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2010-2020 by Christoph Schueler <cpu12.gems.googlemail.com>

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
__version__ = "0.1.0"


import importlib
import logging
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Optional

import antlr4
from antlr4.error.ErrorListener import ErrorListener

logger = logging.getLogger(__name__)


# from pya2l import model


class MyErrorListener(ErrorListener):
    def __init__(self) -> None:
        super().__init__()

    def syntaxError(self, recognizer: Any, offendingSymbol: Any, line: int, column: int, msg: str, e: Any) -> None:
        logger.error("line %d:%d %s", line, column, msg)


class ParserWrapper:
    """"""

    def __init__(self, grammarName: str, startSymbol: str, listener: Optional[type] = None, debug: bool = False) -> None:
        self.debug = debug
        self.grammarName = grammarName
        self.startSymbol = startSymbol
        self.lexerModule, self.lexerClass = self._load("Lexer")
        self.parserModule, self.parserClass = self._load("Parser")
        self.listener = listener

    def _load(self, name: str) -> tuple[ModuleType, type]:
        className = f"{self.grammarName}{name}"
        moduleName = f"asamint.parsers.{className}"
        module = importlib.import_module(moduleName)
        klass = getattr(module, className)
        return (
            module,
            klass,
        )

    def parse(self, input: antlr4.InputStream, trace: bool = False) -> Any:
        lexer = self.lexerClass(input)
        tokenStream = antlr4.CommonTokenStream(lexer)
        parser = self.parserClass(tokenStream)
        parser.setTrace(trace)
        meth = getattr(parser, self.startSymbol)
        self._syntaxErrors = parser._syntaxErrors
        tree = meth()
        if self.listener:
            listener = self.listener()
            walker = antlr4.ParseTreeWalker()
            walker.walk(listener, tree)
            listener.result = getattr(tree, "phys", None)
            return listener

    def parseFromFile(self, filename: str | Path, encoding: str = "latin-1", trace: bool = False) -> Any:
        if filename == ":memory:":
            self.fnbase = ":memory:"
        else:
            self.fnbase = Path(filename).stem
        return self.parse(ParserWrapper.stringStream(filename, encoding), trace)

    def parseFromString(self, buf: str, encoding: str = "latin-1", trace: bool = False, dbname: str = ":memory:") -> Any:
        self.fnbase = dbname
        return self.parse(antlr4.InputStream(buf), trace)

    @staticmethod
    def stringStream(fname: str | Path, encoding: str = "latin-1") -> antlr4.InputStream:
        with open(fname, encoding=encoding) as fh:
            return antlr4.InputStream(fh.read())

    def _getNumberOfSyntaxErrors(self) -> int:
        return self._syntaxErrors

    numberOfSyntaxErrors = property(_getNumberOfSyntaxErrors)
