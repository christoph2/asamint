#!/usr/bin/env python
# -*- coding: utf-8 -*-
from objutils import load
from objutils import loads

import numpy as np
import pytest

from asamint import calibration


@pytest.fixture
def a2l_db():
    from pya2l import DB

    db = DB()
    db.open_create(file_name="CDF20demo", encoding="latin1")
    yield db
    db.close()
    del db


@pytest.fixture
def image():
    return load("ihex", "CDF20demo.hex")


@pytest.fixture
def offline(a2l_db, image):
    return calibration.OfflineCalibration(a2l_db, image, loglevel="DEBUG")


def test_ascii(offline):
    ascii = offline.load_ascii("CDF20.ASCII.N42_wU8")
    # print(ascii)
    assert ascii.value == "   CDF20 Test String                      "
    value = "ASAMInt is awesome!!!"
    offline.save_ascii("CDF20.ASCII.N42_wU8", value)
    ascii = offline.load_ascii("CDF20.ASCII.N42_wU8")
    # print(ascii)
    assert ascii.value == "ASAMInt is awesome!!!\x00                    "


def test_block(offline):
    block = offline.load_value_block("CDF20.MATRIX_DIM.N341_wS8")
    # print(block)
    assert np.all(np.equal(block.raw_values, np.array([[8, 16, 25], [33, 41, 49], [57, 66, 74], [82, 90, 98]])))
    # assert np.all(np.equal(block.converted_values, np.array([
    #    [0.09765923, 0.19531846, 0.30518509],
    #    [0.40284433,  0.50050356, 0.59816279],
    #    [0.69582202,  0.80568865, 0.90334788],
    #    [1.00100711,  1.09866634, 1.19632557]])
    # ))
