#!/usr/bin/env python

__copyright__ = """
    pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2009-2018 by Christoph Schueler <cpu12.gems@googlemail.com>

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

import logging
from typing import Tuple

from asamint.core.logging import configure_logging


class Logger:
    """Compatibility wrapper around the central logging configuration."""

    LOGGER_BASE_NAME = "pyxcp"
    FORMAT = "[%(levelname)s (%(name)s)]: %(message)s"

    def __init__(self, name: str, level: int = logging.WARN) -> None:
        self.logger = configure_logging(
            name=f"{self.LOGGER_BASE_NAME}.{name}", level=level
        )
        self.lastMessage: str | None = None
        self.lastSeverity: int | None = None

    def getLastError(self) -> tuple[int | None, str | None]:
        result = (self.lastSeverity, self.lastMessage)
        self.lastSeverity = self.lastMessage = None
        return result

    def log(self, message: str, level: int) -> None:
        self.lastSeverity = level
        self.lastMessage = message
        self.logger.log(level, message)

    def info(self, message: str) -> None:
        self.log(message, logging.INFO)

    def warn(self, message: str) -> None:
        self.log(message, logging.WARN)

    def debug(self, message: str) -> None:
        self.log(message, logging.DEBUG)

    def error(self, message: str) -> None:
        self.log(message, logging.ERROR)

    def critical(self, message: str) -> None:
        self.log(message, logging.CRITICAL)

    def verbose(self) -> None:
        self.logger.setLevel(logging.DEBUG)

    def silent(self) -> None:
        self.logger.setLevel(logging.CRITICAL)

    def setLevel(self, level: int | str) -> None:
        level_map = {
            "INFO": logging.INFO,
            "WARN": logging.WARN,
            "DEBUG": logging.DEBUG,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL,
        }
        if isinstance(level, str):
            level = level_map.get(level.upper(), logging.WARN)
        self.logger.setLevel(level)
