#!/usr/bin/env python

import logging
import os
import sys

from objutils import load
from pya2l.api.inspect import Characteristic, VariantCoding

from asamint import AsamMC
from asamint.calibration import CalibrationData, phys, raw
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

    from pya2l.api import inspect

    _ = inspect.Module(mc.session)

    vc = VariantCoding(mc.session)
    # print(vc)
    _ = vc.get_citerion_values("VariantCoding")
    _ = vc.valid_combinations(["ValveVariantCoding"])
    _ = vc.variants("vcurctrl_func_appli[7].axis_dithf_temperature")

    image = load("ihex", "K02.hex")
    api = Calibration(mc, image, pc, logger)

    # var_select = api.load("VALVE_VARIANT_CODING_SELECTOR")
    # print(f"Variable selection: {var_select}")

    for name in (
        "AkgLin_MKup_P1P2P3_kl[K1]",
        "Kra_NMot_P_Reg_Gang_5_kl",
        "Kas_JAntrieb_ko",
        "ip_crlc_tig_inv_mdl",
        "Akm_QualMKupGrd_ka",
        "amm_KPDetektionTable",
        "ip_fac_wup_tig_im_mdl",
        "ip_fac_pow_put_ctl_p_d_stat",
    ):
        show_parameter(api, name)


if __name__ == "__main__":
    main()
