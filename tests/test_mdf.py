#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `asam_integration_package` package."""

import pytest

from asammdf import MDF, Signal
import asamint
from pya2l import DB

db = DB()
session = db.open_existing("ASAP2_Demo_V161")

#mdf = MDF(name = "ASAP2_Demo_V161", version = "4.10")
mdf = MDF(version = "4.10")
mdf.save("ASAP2_Demo_V161.mf4")

