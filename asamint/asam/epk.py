from typing import Optional, Tuple

from objutils import load


class Epk:

    def __init__(self, calibration) -> None:
        self.calibration = calibration
        self.asam_mc = calibration.asam_mc

    def epk_address_and_length(self) -> Optional[tuple[int, int]]:
        if self.asam_mc.mod_par is None or self.asam_mc.mod_par.epk is None:
            return None
        epk_addr = self.asam_mc.mod_par.addrEpk[0]
        epk_len = len(self.asam_mc.mod_par.epk)
        return epk_addr, epk_len

    def from_hexfile(self, file_name: str = "", hexfile_type: str = "") -> Optional[str]:
        """Read EPK from given file.

        Parameters
        ----------
        file_name : str, optional
        """
        res = self.epk_address_and_length()
        if res is None:
            return None
        epk_addr, epk_len = res
        if file_name:
            image = load(hexfile_type, open(f"{file_name}", "rb"))
        else:
            image = self.calibration.image
        value = image.read_string(addr=epk_addr, length=epk_len)
        return value

    def from_a2l(self) -> Optional[str]:
        """Read EPK from A2L database."""
        if self.asam_mc.mod_par is None:
            return None
        elif self.asam_mc.mod_par.epk is None:
            return None
        else:
            epk = self.asam_mc.mod_par.epk
            return epk

    def check_epk_xcp(self, xcp_master):
        """Compare EPK (EPROM Kennung) from A2L with EPK from ECU.

        Returns
        -------
            - True:     EPKs are matching.
            - False:    EPKs are not matching.
            - None:     EPK not configured in MOD_COMMON.
        """
        res = self.epk_address_and_length()
        if res is None:
            return None
        epk_addr, epk_len = res
        xcp_master.setMta(epk_addr)
        epk_xcp = xcp_master.pull(epk_len)
        epk_xcp = epk_xcp[:epk_len].decode("ascii")
        ok = epk_xcp == epk_a2l
        if not ok:
            self.logger.warning(f"EPK is invalid -- A2L: '{self.mod_par.epk}' XCP: '{epk_xcp}'.")
        else:
            self.logger.info("OK, matching EPKs.")
        return ok
