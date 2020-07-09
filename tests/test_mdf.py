#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `asam_integration_package` package."""

import pytest

import asamint

db = asamint.mdf.DB()
session = db.open_existing("ASAP2_Demo_V161")

mdf = asamint.mdf.mdf.MDF(name = "ASAP2_Demo_V161", version = "4.10")
mdf.save()

