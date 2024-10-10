#!/usr/bin/env python
import numpy as np
import pytest
from objutils import load

from asamint import calibration


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
    assert np.all(
        np.equal(
            block.raw_values,
            np.array([[8, 16, 25], [33, 41, 49], [57, 66, 74], [82, 90, 98]]),
        )
    )
    # assert np.all(np.equal(block.converted_values, np.array([
    #    [0.09765923, 0.19531846, 0.30518509],
    #    [0.40284433,  0.50050356, 0.59816279],
    #    [0.69582202,  0.80568865, 0.90334788],
    #    [1.00100711,  1.09866634, 1.19632557]])
    # ))
    offline.save_value_block("CDF20.MATRIX_DIM.N341_wS8", block.converted_values)


def load_save_verify_value(conn, param_name, expected_rw, expected_cw):
    value = conn.load_value(param_name)
    assert value.converted_value == expected_cw
    assert value.raw_value == expected_rw
    conn.save_value(param_name, value.converted_value)


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
    load_save_verify_value(offline, "CDF20.array.Element[0]", 248, 0.2421875)


def test_value004(offline):
    load_save_verify_value(offline, "CDF20.array.Element[1]", 16, 0.015625)


def test_value005(offline):
    load_save_verify_value(offline, "CDF20.array.Element[2]", 28, 0.02734375)


def test_value006(offline):
    load_save_verify_value(offline, "CDF20.array.Element[3]", 40, 0.0390625)


def test_value007(offline):
    load_save_verify_value(offline, "CDF20.array.Element[4]", 80, 0.078125)


def test_value008(offline):
    load_save_verify_value(offline, "CDF20.scalar.FW_wU16", 34, 0.4150517288735618)


def test_value009(offline):
    load_save_verify_value(offline, "DummyAirMass", 2560, 1.25)


def test_value010(offline):
    load_save_verify_value(offline, "DummyOmega", 32770, 1024.0625)


def test_value011(offline):
    load_save_verify_value(offline, "FrequencyPrescaler", 2560, 0.256)


def test_value012(offline):
    load_save_verify_value(offline, "SelectColumn", 64, 0.001953125)


def test_value013(offline):
    load_save_verify_value(offline, "Select_param_set", 1, 1.0)


def test_value014(offline):
    with pytest.raises(calibration.RangeError):
        load_save_verify_value(offline, "SignalAmplitude", -32746, -255.828125)


def test_value015(offline):
    load_save_verify_value(offline, "SignalForm", 3, "Sin")


def test_value016(offline):
    load_save_verify_value(offline, "SignalOffset", 25, 0.1953125)


def test_value017(offline):
    load_save_verify_value(offline, "Soll_Lambda", 128, 1.0)


def test_value018(offline):
    load_save_verify_value(offline, "ThrottleRefInputTest", 19456, 152.0)


def test_value019(offline):
    load_save_verify_value(offline, "f_Kd_1", 25104, 0.005985260009765625)


def test_value020(offline):
    load_save_verify_value(offline, "f_Kd_2", 25104, 0.005985260009765625)


def test_value021(offline):
    load_save_verify_value(offline, "f_Ki_1", 16, 0.00390625)


def test_value022(offline):
    load_save_verify_value(offline, "f_Ki_2", 48, 0.01171875)


def test_value023(offline):
    load_save_verify_value(offline, "f_Kp_1", 52236, 1.5941162109375)


def test_value024(offline):
    load_save_verify_value(offline, "f_Kp_2", 26150, 0.79803466796875)


def test_value025(offline):
    load_save_verify_value(offline, "inj_offset", -4074, -0.0004856586456298828)


def test_value026(offline):
    load_save_verify_value(offline, "inv_c_kumsrl", -29127, -1820.4375)


def load_save_verify_axis_pts(conn, param_name, expected_rw, expected_cw):
    value = conn.load_axis_pts(param_name)
    assert np.allclose(value.converted_values, expected_cw)
    assert np.array_equal(value.raw_values, expected_rw)
    # conn.save_axis_pts(param_name, value.converted_value)


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
            156,
            166,
            176,
            186,
            196,
            206,
            216,
            226,
            236,
            246,
            0,
            10,
            20,
            30,
            40,
            50,
            60,
            70,
            80,
            90,
            100,
        ],
        [
            1.21875,
            1.296875,
            1.375,
            1.453125,
            1.53125,
            1.609375,
            1.6875,
            1.765625,
            1.84375,
            1.921875,
            0.0,
            0.078125,
            0.15625,
            0.234375,
            0.3125,
            0.390625,
            0.46875,
            0.546875,
            0.625,
            0.703125,
            0.78125,
        ],
    )


def test_axis_pts004(offline):
    load_save_verify_axis_pts(
        offline,
        "LUT2D_1_x_table",
        [166, 186, 206, 226, 246, 10, 30, 50, 70, 90],
        [
            1.296875,
            1.453125,
            1.609375,
            1.765625,
            1.921875,
            0.078125,
            0.234375,
            0.390625,
            0.546875,
            0.703125,
        ],
    )


def test_axis_pts005(offline):
    load_save_verify_axis_pts(offline, "LUT2D_1_y_table", [181, 231, 75], [1.4140625, 1.8046875, 0.5859375])


def test_axis_pts006(offline):
    load_save_verify_axis_pts(
        offline,
        "Rec2Sine_x_table",
        [
            0,
            11266,
            22276,
            33542,
            44552,
            55818,
            1293,
            12559,
            23569,
            34835,
            46101,
            57111,
            2842,
            13852,
            25118,
            36128,
            47394,
            58404,
            4135,
        ],
        [
            0.0,
            7.07863657,
            13.99642359,
            21.07506016,
            27.99284718,
            35.07148375,
            0.81241586,
            7.89105243,
            14.80883945,
            21.88747602,
            28.96611258,
            35.88389961,
            1.78568126,
            8.70346829,
            15.78210485,
            22.69989188,
            29.77852844,
            36.69631547,
            2.59809712,
        ],
    )
    pass


def test_axis_pts0XX(offline):
    # load_save_verify_axis_pts(offline, "CDF20.axis.X_AXIS_xU16", [], [])
    pass
