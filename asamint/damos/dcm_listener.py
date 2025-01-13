#!/usr/bin/env python
"""Damos DCM 2.0 Parser.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

   All Rights Reserved

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License along
   with this program; if not, write to the Free Software Foundation, Inc.,
   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

   s. FLOSS-EXCEPTION.txt
"""

from decimal import Decimal as D

import antlr4

from asamint.logger import Logger


class BaseListener(antlr4.ParseTreeListener):
    """"""

    value = []

    def __init__(self, *args, **kws):
        super().__init__(*args, **kws)
        self.logger = Logger(__name__)

    def getList(self, attr):
        return [x.value for x in attr] if attr else []

    def getTerminal(self, attr):
        return attr().getText() if attr() else ""

    def getText(self, attr):
        return getattr(attr, "text") or ""

    def getNT(self, attr):
        return attr.value if attr else None

    def exitIntegerValue(self, ctx):
        ctx.value = int(ctx.i.text)

    def exitRealzahl(self, ctx):
        if ctx.f:
            ctx.value = D(ctx.f.text)
        elif ctx.i:
            ctx.value = D(ctx.i.text)
        else:
            ctx.value = None

    def exitTextValue(self, ctx):
        ctx.value = ctx.t.text.strip('"') if ctx.t else None

    def exitNameValue(self, ctx):
        ctx.value = ctx.n.text if ctx.n else None

    def _formatMessage(self, msg, location):
        return f"[{location.start.line}:{location.start.column + 1}] {msg}"

    def _log(self, method, msg, location=None):
        if location:
            method(self._formatMessage(msg, location))
        else:
            method(msg)

    def info(self, msg, location=None):
        self._log(self.logger.info, msg, location)

    def warn(self, msg, location=None):
        self._log(self.logger.warn, msg, location)

    def error(self, msg, location=None):
        self._log(self.logger.error, msg, location)

    def debug(self, msg, location=None):
        self._log(self.logger.debug, msg, location)


class Dcm20Listener(BaseListener):
    def exitKonservierung(self, ctx):
        ctx.value = {"kopf": self.getNT(ctx.kopf), "rumpf": self.getNT(ctx.rumpf), "version": ctx.version.value}

    def exitFile_format(self, ctx):
        if ctx.version is None:
            ctx.value = {}
        else:
            ctx.value = float(ctx.version.text)

    def exitKons_kopf(self, ctx):
        ctx.value = {
            "info": self.getNT(ctx.info),
            "func_def": self.getNT(ctx.func_def),
            "var_def": self.getNT(ctx.var_def),
        }

    def exitModulkopf_info(self, ctx):
        ctx.value = self.getList(ctx.m)

    def exitMod_zeile(self, ctx):
        ctx.value = {"anf": self.getNT(ctx.anf), "fort": self.getList(ctx.fort)}

    def exitMod_anf_zeile(self, ctx):
        ctx.value = {"name": self.getNT(ctx.n), "wert": self.getNT(ctx.w)}

    def exitMod_fort_zeile(self, ctx):
        ctx.value = self.getNT(ctx.w)

    def exitMod_ele_name(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitMod_ele_wert(self, ctx):
        ctx.value = self.getNT(ctx.t)

    def exitFunktionsdef(self, ctx):
        ctx.value = self.getList(ctx.f)

    def exitFunktionszeile(self, ctx):
        ctx.value = {
            "name": self.getNT(ctx.n),
            "version": self.getNT(ctx.v),
            "langname": self.getNT(ctx.l),
        }

    def exitFkt_version(self, ctx):
        ctx.value = self.getNT(ctx.t)

    def exitFkt_langname(self, ctx):
        ctx.value = self.getNT(ctx.t)

    def exitVariantendef(self, ctx):
        ctx.value = self.getList(ctx.v)

    def exitVariantenkrit(self, ctx):
        ctx.value = {"name": self.getNT(ctx.n), "werte": self.getList(ctx.w)}

    def exitKrit_name(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitKrit_wert(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitKons_rumpf(self, ctx):
        ctx.value = self.getList(ctx.k)

    def exitKenngroesse(self, ctx):
        ctx.value = {
            "kw": self.getNT(ctx.kw),
            "kwb": self.getNT(ctx.kwb),
            "kl": self.getNT(ctx.kl),
            "kf": self.getNT(ctx.kf),
            "gst": self.getNT(ctx.gst),
            "kt": self.getNT(ctx.kt),
        }

    def exitKennwert(self, ctx):
        r = self.getNT(ctx.r)
        t = self.getNT(ctx.t)
        if r is None:
            category = "TEXT"
        else:
            category = "REAL"
        ctx.value = {
            "category": category,
            "name": ctx.n.value,
            "info": self.getNT(ctx.info),
            "einheit_w": self.getNT(ctx.ew),
            "realzahl": r,
            "text": t,
        }

    def exitKennwerteblock(self, ctx):
        ctx.value = {
            "name": self.getNT(ctx.n),
            "anzahl_x": self.getNT(ctx.ax),
            "anzahl_y": self.getNT(ctx.ay) or 0,
            "info": self.getNT(ctx.info),
            "einheit_w": self.getNT(ctx.ew),
            "werteliste_kwb": self.getList(ctx.w),
        }

    def exitKennlinie(self, ctx):
        ctx.value = {
            "category": self.getText(ctx.cat),
            "name": self.getNT(ctx.n),
            "anzahl_x": self.getNT(ctx.ax),
            "info": self.getNT(ctx.info),
            "einheit_x": self.getNT(ctx.ex),
            "einheit_w": self.getNT(ctx.ew),
            "sst_liste_x": self.getList(ctx.sst),
            "werteliste": self.getList(ctx.wl),
        }

    def exitKennfeld(self, ctx):
        ctx.value = {
            "category": self.getText(ctx.cat),
            "name": self.getNT(ctx.n),
            "anzahl_x": self.getNT(ctx.ax),
            "anzahl_y": self.getNT(ctx.ay),
            "info": self.getNT(ctx.info),
            "einheit_x": self.getNT(ctx.ex),
            "einheit_y": self.getNT(ctx.ey),
            "einheit_w": self.getNT(ctx.ew),
            "sst_liste_x": self.getList(ctx.sst),
            "kf_zeile_liste": ctx.kf.value,
        }

    def exitGruppenstuetzstellen(self, ctx):
        ctx.value = {
            "name": self.getNT(ctx.n),
            "anzahl_x": self.getNT(ctx.nx),
            "info": self.getNT(ctx.info),
            "einheit_x": self.getNT(ctx.ex),
            "sst_liste_x": self.getList(ctx.sl),
        }

    def exitKenntext(self, ctx):
        ctx.value = {
            "name": self.getNT(ctx.n),
            "info": self.getNT(ctx.info),
            "text": self.getNT(ctx.t),
        }

    def exitKgr_info(self, ctx):
        ctx.value = {
            "langname": self.getNT(ctx.lname),
            "displayname": self.getNT(ctx.dname),
            "var_abhangigkeiten": self.getNT(ctx.var),
            "funktionszugehorigkeit": self.getNT(ctx.fkt),
        }

    def exitEinheit_x(self, ctx):
        ctx.value = ctx.t.value

    def exitEinheit_y(self, ctx):
        ctx.value = ctx.t.value

    def exitEinheit_w(self, ctx):
        ctx.value = ctx.t.value

    def exitLangname(self, ctx):
        ctx.value = ctx.t.value

    def exitDisplayname(self, ctx):
        t = self.getNT(ctx.t)  # ctx.t.value
        n = self.getNT(ctx.n)  # ctx.n.value
        ctx.value = {"name_value": n, "text_value": t}

    def exitVar_abhangigkeiten(self, ctx):
        ctx.value = self.getList(ctx.v)

    def exitVar_abh(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitFunktionszugehorigkeit(self, ctx):
        ctx.value = self.getList(ctx.n)

    def exitAnzahl_x(self, ctx):
        ctx.value = ctx.i.value

    def exitAnzahl_y(self, ctx):
        ctx.value = ctx.i.value

    def exitWerteliste(self, ctx):
        ctx.value = self.getList(ctx.r)

    def exitWerteliste_kwb(self, ctx):
        rs = self.getList(ctx.r)
        ts = self.getList(ctx.t)
        if rs:
            category = "WERT"
        else:
            category = "TEXT"
        ctx.value = {"category": category, "rs": rs, "ts": ts}

    def exitSst_liste_x(self, ctx):
        rs = self.getList(ctx.r)
        ts = self.getList(ctx.t)
        if rs:
            category = "REAL"
        else:
            category = "TEXT"
        ctx.value = {"category": category, "rs": rs, "ts": ts}

    def exitKf_zeile_liste(self, ctx):
        rs = self.getList(ctx.r)
        ts = self.getList(ctx.t)
        if rs:
            category = "REAL"
        else:
            category = "TEXT"
        ctx.value = {"category": category, "rs": rs, "ts": ts}

    def exitKf_zeile_liste_r(self, ctx):
        ctx.value = {"realzahl": ctx.r.value, "werteliste": self.getList(ctx.w)}

    def exitKf_zeile_liste_tx(self, ctx):
        ctx.value = {"text": ctx.t.value, "werteliste": self.getList(ctx.w)}
