#!/usr/bin/env python
import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from objutils import load

from asamint import calibration
from asamint.adapters.a2l import ModCommon, ModPar, open_a2l_database
from asamint.core.logging import configure_logging

FIXTURE_DIR = Path(__file__).parent


class Boolean:
    def __init__(self, value: bool = False) -> None:
        self.value = value

    def __bool__(self) -> bool:
        return self.value

    def __str__(self) -> str:
        return "true" if self.value else "false"

    __repr__ = __str__
    # def __repr__(self):
    #    return f"bool({self.value})"


def test_boolean():
    b = Boolean(True)
    assert str(b) == "true"


@pytest.fixture
def calibration_context():
    session = open_a2l_database(str(FIXTURE_DIR / "CDF20demo"), encoding="latin1", local=True)
    context = SimpleNamespace(
        session=session,
        mod_common=ModCommon.get(session),
        mod_par=ModPar.get(session) if ModPar.exists(session) else None,
        logger=configure_logging(name="asamint.calibration.tests", level=logging.DEBUG),
    )
    yield context
    close_fn = getattr(session, "close", None)
    if callable(close_fn):
        close_fn()


@pytest.fixture
def image():
    return load("ihex", str(FIXTURE_DIR / "CDF20demo.hex"))


@pytest.fixture
def offline(calibration_context, image):
    return calibration.OfflineCalibration(calibration_context, image, loglevel="DEBUG")


def test_ascii(offline):
    ascii = offline.load_ascii("CDF20.ASCII.N42_wU8")
    # print(ascii)
    assert ascii.phys == "   CDF20 Test String                      "
    value = "ASAMInt is awesome!!!"
    offline.save_ascii("CDF20.ASCII.N42_wU8", value)
    ascii = offline.load_ascii("CDF20.ASCII.N42_wU8")
    # print(ascii)
    assert ascii.phys == "ASAMInt is awesome!!!\x00                    "


def test_block(offline):
    block = offline.load_value_block("CDF20.MATRIX_DIM.N341_wS8")
    # print(block)
    assert np.all(
        np.equal(
            block.raw,
            np.array([[8, 16, 25], [33, 41, 49], [57, 66, 74], [82, 90, 98]]),
        )
    )
    # assert np.all(np.equal(block.phys, np.array([
    #    [0.09765923, 0.19531846, 0.30518509],
    #    [0.40284433,  0.50050356, 0.59816279],
    #    [0.69582202,  0.80568865, 0.90334788],
    #    [1.00100711,  1.09866634, 1.19632557]])
    # ))
    offline.save_value_block("CDF20.MATRIX_DIM.N341_wS8", block.phys)


def load_save_verify_value(conn, param_name, expected_rw, expected_cw):
    value = conn.load_value(param_name)
    assert value.phys == expected_cw
    assert value.raw == expected_rw
    conn.save_value(param_name, value.phys)


def test_value_uword(offline):
    load_save_verify_value(offline, "CDF20.scalar.FW_wU16", 34, 0.4150517288735618)


def test_value_dependent(offline):
    load_save_verify_value(offline, "CDF20.Dependent.Base.FW_wU16", 17, 17.0)


def test_value_bool1(offline):
    load_save_verify_value(offline, "CDF20.BOOLEAN.FW_wU8", 1, "true")
    # load_save_verify_value(offline, "CDF20.BOOLEAN.FW_wU8", 1, True)
    # load_save_verify_value(offline, "CDF20.BOOLEAN.FW_wU8", 1, 1)


def test_value_bool2(offline):
    load_save_verify_value(offline, "CDF20.BOOLEAN.FW_wU8_VTab", 1, "TRUE")


def test_value001(offline):
    load_save_verify_value(offline, "CDF20", 65535, 65535.0)


def test_value002(offline):
    with pytest.raises(calibration.ReadOnlyError):
        load_save_verify_value(offline, "CDF20.Dependent.Ref_1.FW_wU16", 85, 85.0)


def test_value003(offline):
    load_save_verify_value(offline, "CDF20.array.Element[0]", -2048, -2.0)


def test_value004(offline):
    load_save_verify_value(offline, "CDF20.array.Element[1]", 4096, 4.0)


def test_value005(offline):
    load_save_verify_value(offline, "CDF20.array.Element[2]", 7168, 7.0)


def test_value006(offline):
    load_save_verify_value(offline, "CDF20.array.Element[3]", 10240, 10.0)


def test_value007(offline):
    load_save_verify_value(offline, "CDF20.array.Element[4]", 20480, 20.0)


def test_value008(offline):
    load_save_verify_value(offline, "CDF20.scalar.FW_wU16", 34, 0.4150517288735618)


def test_value009(offline):
    load_save_verify_value(offline, "DummyAirMass", 10, 0.0048828125)


def test_value010(offline):
    load_save_verify_value(offline, "DummyOmega", 640, 20.0)


def test_value011(offline):
    load_save_verify_value(offline, "FrequencyPrescaler", 10, 0.001)


def test_value012(offline):
    load_save_verify_value(offline, "SelectColumn", 16384, 0.5)


def test_value013(offline):
    load_save_verify_value(offline, "Select_param_set", 1, 1.0)


def test_value014(offline):
    load_save_verify_value(offline, "SignalAmplitude", 5760, 45.0)


def test_value015(offline):
    load_save_verify_value(offline, "SignalForm", 3, "Sin")


def test_value016(offline):
    load_save_verify_value(offline, "SignalOffset", 6400, 50.0)


def test_value017(offline):
    load_save_verify_value(offline, "Soll_Lambda", 128, 1.0)


def test_value018(offline):
    load_save_verify_value(offline, "ThrottleRefInputTest", 76, 0.59375)


def test_value019(offline):
    load_save_verify_value(offline, "f_Kd_1", 4194, 0.0009999275207519531)


def test_value020(offline):
    load_save_verify_value(offline, "f_Kd_2", 4194, 0.0009999275207519531)


def test_value021(offline):
    load_save_verify_value(offline, "f_Ki_1", 4096, 1.0)


def test_value022(offline):
    load_save_verify_value(offline, "f_Ki_2", 12288, 3.0)


def test_value023(offline):
    load_save_verify_value(offline, "f_Kp_1", 3276, 0.0999755859375)


def test_value024(offline):
    load_save_verify_value(offline, "f_Kp_2", 9830, 0.29998779296875)


def test_value025(offline):
    load_save_verify_value(offline, "inj_offset", 5872, 0.0006999969482421875)


def test_value026(offline):
    load_save_verify_value(offline, "inv_c_kumsrl", 14734, 920.875)


def load_save_verify_axis_pts(conn, param_name, expected_rw, expected_cw):
    value = conn.load_axis_pts(param_name)
    assert np.allclose(value.phys, expected_cw)
    assert np.array_equal(value.raw, expected_rw)
    # conn.save_axis_pts(param_name, value.phys)


def test_axis_pts001(offline):
    load_save_verify_axis_pts(
        offline,
        "CDF20.axis.X_AXIS_xU16",
        [52, 55, 56, 64, 66],
        [52.0, 55.0, 56.0, 64.0, 66.0],
    )


def test_axis_pts002(offline):
    load_save_verify_axis_pts(
        offline,
        "CDF20.axis.X_RE_AXIS_xS8",
        [10, 2, 18, 3, 33, 4, 51, 5, 52, 6, 68, 7, 85, 8],
        [10.0, 2.0, 18.0, 3.0, 33.0, 4.0, 51.0, 5.0, 52.0, 6.0, 68.0, 7.0, 85.0, 8.0],
    )


def test_axis_pts003(offline):
    load_save_verify_axis_pts(
        offline,
        "LUT1D_1_x_table",
        [
            -25600,
            -23040,
            -20480,
            -17920,
            -15360,
            -12800,
            -10240,
            -7680,
            -5120,
            -2560,
            0,
            2560,
            5120,
            7680,
            10240,
            12800,
            15360,
            17920,
            20480,
            23040,
            25600,
        ],
        [
            -200.0,
            -180.0,
            -160.0,
            -140.0,
            -120.0,
            -100.0,
            -80.0,
            -60.0,
            -40.0,
            -20.0,
            0.0,
            20.0,
            40.0,
            60.0,
            80.0,
            100.0,
            120.0,
            140.0,
            160.0,
            180.0,
            200.0,
        ],
    )


def test_axis_pts004(offline):
    load_save_verify_axis_pts(
        offline,
        "LUT2D_1_x_table",
        [-23040, -17920, -12800, -7680, -2560, 2560, 7680, 12800, 17920, 23040],
        [
            -180.0,
            -140.0,
            -100.0,
            -60.0,
            -20.0,
            20.0,
            60.0,
            100.0,
            140.0,
            180.0,
        ],
    )


def test_axis_pts005(offline):
    load_save_verify_axis_pts(offline, "LUT2D_1_y_table", [-19200, -6400, 19200], [-150.0, -50.0, 150.0])


def test_axis_pts006(offline):
    load_save_verify_axis_pts(
        offline,
        "Rec2Sine_x_table",
        [
            0,
            556,
            1111,
            1667,
            2222,
            2778,
            3333,
            3889,
            4444,
            5000,
            5556,
            6111,
            6667,
            7222,
            7778,
            8333,
            8889,
            9444,
            10000,
        ],
        [
            0.0,
            0.34934510306139527,
            0.6980618875921046,
            1.0474069906535,
            1.3961237751842093,
            1.7454688782456045,
            2.094185662776314,
            2.4435307658377092,
            2.7922475503684185,
            3.1415926534298135,
            3.490937756491209,
            3.8396545410219183,
            4.188999644083314,
            4.537716428614023,
            4.8870615316754185,
            5.235778316206128,
            5.585123419267522,
            5.933840203798232,
            6.283185306859627,
        ],
    )


def test_axis_pts0XX(offline):
    # load_save_verify_axis_pts(offline, "CDF20.axis.X_AXIS_xU16", [], [])
    pass
