#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `asam_integration_package` package."""

import pytest

from asammdf import MDF, Signal
from  asamint.mdf import create_mdf, MDFCreator
import asamint
from pya2l import DB

db = DB()
session = db.open_existing("ASAP2_Demo_V161")

mdf = MDF(version = "4.10")
create_mdf(session_obj = session, mdf_obj = mdf, mdf_filename = "ASAP2_Demo_V161.mf4")


mxx = MDFCreator(session_obj = session, mdf_obj = mdf, mdf_filename = "ASAP2_Demo_V161.mf4")
