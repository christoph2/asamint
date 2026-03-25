#!/usr/bin/env python

import sys

from asamint import AsamMC
from asamint.calibration import CalibrationData
from asamint.cmdline import ArgumentParser

sys.argv.extend(["-c", "asamint_conf.py"])


def main():
    ap = ArgumentParser(use_xcp=False)
    ap.run()

    mc = AsamMC()
    cdm = CalibrationData(mc)
    cdm.load_hex_file()
    cdm.close()


if __name__ == "__main__":
    main()
