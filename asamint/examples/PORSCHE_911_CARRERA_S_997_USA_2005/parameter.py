#!/usr/bin/env python

import logging
import os
import sys

from objutils import load

from asamint import AsamMC
from asamint.calibration import CalibrationData
from asamint.calibration.api import Calibration, ParameterCache
from asamint.cdf import DB
from asamint.cmdline import ArgumentParser

sys.argv.extend(["-c", "asamint_conf.py"])


logger = logging.getLogger(__name__)


def show_parameter(api: Calibration, name: str) -> None:
    try:
        value = api.load(name)
    except ValueError:
        print(f"Skipping unavailable characteristic: {name}")
        return
    print(f"{name}: {value}")


def main():
    ap = ArgumentParser(use_xcp=False)
    ap.run()

    mc = AsamMC()
    pc = ParameterCache()

    image = load("ihex", "0711_013.hex")
    api = Calibration(mc, image, pc, logger)

    for name in (
        "SKS06ESUB",
        "CAETAE",
        "ATISLATM",
        "DMIFAVSG",
        "ABOLRAR",
        "SGIDK2_DAT",
    ):
        show_parameter(api, name)

    # var7 = api.load("ip_fac_pow_put_ctl_p_d_stat")
    # print(f"Variable 7: {var7}")

    # cdm = CalibrationData(mc)
    # cdm.load_hex_file()
    # cdm.load_characteristics()
    # cdm.close()


if __name__ == "__main__":
    main()
