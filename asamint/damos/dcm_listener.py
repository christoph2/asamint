#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""

"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020 by Christoph Schueler <cpu12.gems.googlemail.com>

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
        super(BaseListener, self).__init__(*args, **kws)
        self.logger = Logger(__name__)

    def getList(self, attr):
        return [x.value for x in attr] if attr else []

    def getTerminal(self, attr):
        return attr().getText() if attr() else ""

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
        return "[{0}:{1}] {2}".format(
            location.start.line, location.start.column + 1, msg
        )

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


class Konservierung:

    def __init__(self, kopf, rumpf):
        self.kopf = kopf
        self.rumpf = rumpf

class KonsKopf:

    def __init__(self, info, func_def, var_def):
        self.info = info
        self.func_def = func_def
        self.var_def = var_def

class Kenngroesse:

    def __init__(self, kw, kwb, kl, kf, gst, kt):
        self.kw = kw
        self.kwb = kwb
        self.kl = kl
        self.kf = kf
        self.gst = gst
        self.kt = kt

class Gruppenstuetzstelle:

    def __init__(self, name, anzahl_x, info, einheit_x, sst_liste_x):
        self.name = name
        self.anzahl_x = anzahl_x
        self.info = info
        self.einheit_x = einheit_x
        self.sst_liste_x = sst_liste_x

class KgrInfo:

    def __init__(self, langname, displayname, var_abhangigkeiten, funktionszugehorigkeit):
        self.langname = langname
        self.displayname = displayname
        self.var_abhangigkeiten = var_abhangigkeiten
        self.funktionszugehorigkeit = funktionszugehorigkeit

class SstListe:

    def __init__(self, category, rs, ts):
        self.category = category
        self.rs = rs
        self.ts = ts

class WertelisteKwb:

    def __init__(self, category, rs, ts):
        self.category = category
        self.rs = rs
        self.ts = ts

class KfZeileListe:

    def __init__(self, category, rs, ts):
        self.category = category
        self.rs = rs
        self.ts = ts


class KfZeileListeR:

    def __init__(self, realzahl, werteliste):
        self.realzahl = realzahl
        self.werteliste = werteliste

class KfZeileListeTx:

    def __init__(self, text, werteliste):
        self.text = text
        self.werteliste = werteliste


class Kennfeld:

    def __init__(self, category, name, anzahl_x, anzahl_y, info, einheit_x, einheit_y, einheit_w, sst_liste_x, kf_zeile_liste):
        self.category = category
        self.name = name
        self.anzahl_x = anzahl_x
        self.anzahl_y = anzahl_y
        self.info = info
        self.einheit_x = einheit_x
        self.einheit_y = einheit_y
        self.einheit_w = einheit_w
        self.sst_liste_x = sst_liste_x
        self.kf_zeile_liste = kf_zeile_liste


class Kennlinie:

    def __init__(self, category, name, anzahl_x, info, einheit_x, einheit_w, sst_liste_x, werteliste):
        self.category = category
        self.name = name
        self.anzahl_x = anzahl_x
        self.info = info
        self.einheit_x = einheit_x
        self.einheit_w = einheit_w
        self.sst_liste_x = sst_liste_x
        self.werteliste = werteliste

class Kennwert:

    def __init__(self, category, name, info, einheit_w, realzahl, text):
        self.category = category
        self.name = name
        self.info = info
        self.einheit_w = einheit_w
        self.realzahl = realzahl
        self.text = text

class Kenntext:

    def __init__(self, name, info, text):
        self.name = name
        self.info = info
        self.text = text

class KennwerteBlock:
    def __init__(self, name, anzahl_x, info, einheit_w, werteliste_kwb):
        self.name = name
        self.anzahl_x = anzahl_x
        self.info = info
        self.einheit_w = einheit_w
        self.werteliste_kwb = werteliste_kwb

class ModZeile:

    def __init__(self, anf, fort):
        self.anf = anf
        self.fort = fort

class ModAnfZeile:

    def __init__(self, name, wert):
        self.name = name
        self.wert = wert

class FunktionsZeile:

    def __init__(self, name, version, langname):
        self.name = name
        self.version = version
        self.langname = langname

class VariantenKrit:

    def __init__(self, name, werte):
        self.name = name
        self.werte = werte

class Dcm20Listener(BaseListener):


    def exitKonservierung(self, ctx):
        ctx.value = Konservierung(self.getNT(ctx.kopf), self.getNT(ctx.rumpf))

    def exitKons_kopf(self, ctx):
        ctx.value = KonsKopf(self.getNT(ctx.info), self.getNT(ctx.func_def), self.getNT(ctx.var_def))

    def exitModulkopf_info(self, ctx):
        ctx.value = self.getList(ctx.m)

    def exitMod_zeile(self, ctx):
        ctx.value = ModZeile(self.getNT(ctx.anf), self.getList(ctx.fort))

    def exitMod_anf_zeile(self, ctx):
        ctx.value = ModAnfZeile(self.getNT(ctx.n), self.getNT(ctx.w))

    def exitMod_fort_zeile(self, ctx):
        ctx.value = self.getNT(ctx.w)

    def exitMod_ele_name(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitMod_ele_wert(self, ctx):
        ctx.value = self.getNT(ctx.t)

    def exitFunktionsdef(self, ctx):
        ctx.value = self.getList(ctx.f)

    def exitFunktionszeile(self, ctx):
        ctx.value = FunktionsZeile(self.getNT(ctx.n), self.getNT(ctx.v), self.getNT(ctx.l))

    def exitFkt_version(self, ctx):
        ctx.value = self.getNT(ctx.t)

    def exitFkt_langname(self, ctx):
        ctx.value = self.getNT(ctx.t)

    def exitVariantendef(self, ctx):
        ctx.value = self.getList(ctx.v)

    def exitVariantenkrit(self, ctx):
        ctx.value = VariantenKrit(self.getNT(ctx.n), self.getList(ctx.w))

    def exitKrit_name(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitKrit_wert(self, ctx):
        ctx.value = self.getNT(ctx.n)

    def exitKons_rumpf(self, ctx):
        ctx.value = self.getList(ctx.k)

    def exitKenngroesse(self, ctx):
        ctx.value = Kenngroesse(
            self.getNT(ctx.kw),
            self.getNT(ctx.kwb),
            self.getNT(ctx.kl),
            self.getNT(ctx.kf),
            self.getNT(ctx.gst),
            self.getNT(ctx.kt)
        )

    def exitKennwert(self, ctx):
        r = self.getNT(ctx.r)
        t = self.getNT(ctx.t)
        if r is None:
            category = "TEXT"
        else:
            category = "REAL"
        ctx.value = Kennwert(category, ctx.n.value, self.getNT(ctx.info), self.getNT(ctx.ew), r, t)

    def exitKennwerteblock(self, ctx):
        ctx.value = KennwerteBlock(
            ctx.n.value, ctx.ax.value, self.getNT(ctx.info), self.getNT(ctx.ew), self.getList(ctx.w)
        )

    def exitKennlinie(self, ctx):
        ctx.value = Kennlinie(
            ctx.cat.text, ctx.n.value, ctx.ax.value, self.getNT(ctx.info), self.getNT(ctx.ex),
            self.getNT(ctx.ew), self.getList(ctx.sst), self.getList(ctx.wl)
        )

    def exitKennfeld(self, ctx):
        ctx.value = Kennfeld(
            ctx.cat.text, ctx.n.value, ctx.ax.value, ctx.ay.value, self.getNT(ctx.info), self.getNT(ctx.ex),
            self.getNT(ctx.ey), self.getNT(ctx.ew), self.getList(ctx.sst), ctx.kf.value
        )

    def exitGruppenstuetzstellen(self, ctx):
        ctx.value = Gruppenstuetzstelle(
            ctx.n.value, self.getNT(ctx.nx), self.getNT(ctx.info), self.getNT(ctx.ex), self.getList(ctx.sl)
        )

    def exitKenntext(self, ctx):
        ctx.value = Kenntext(ctx.n.value, self.getNT(ctx.info), self.getNT(ctx.t))

    def exitKgr_info(self, ctx):
        ctx.value = KgrInfo(self.getNT(ctx.lname), self.getNT(ctx.dname), self.getNT(ctx.var), self.getNT(ctx.fkt))

    def exitEinheit_x(self, ctx):
        ctx.value = ctx.t.value

    def exitEinheit_y(self, ctx):
        ctx.value = ctx.t.value

    def exitEinheit_w(self, ctx):
        ctx.value = ctx.t.value

    def exitLangname(self, ctx):
        ctx.value = ctx.t.value

    def exitDisplayname(self, ctx):
        t = ctx.t.value
        n = ctx.n.value
        if t is None:
            value = n
        else:
            value = t
        ctx.value = value

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
        ctx.value = WertelisteKwb(category, rs, ts)

    def exitSst_liste_x(self, ctx):
        rs = self.getList(ctx.r)
        ts = self.getList(ctx.t)
        if rs:
            category = "REAL"
        else:
            category = "TEXT"
        ctx.value = SstListe(category, rs, ts)

    def exitKf_zeile_liste(self, ctx):
        rs = self.getList(ctx.r)
        ts = self.getList(ctx.t)
        if rs:
            category = "REAL"
        else:
            category = "TEXT"
        ctx.value = KfZeileListe(category, rs, ts)

    def exitKf_zeile_liste_r(self, ctx):
        ctx.value = KfZeileListeR(ctx.r.value, self.getList(ctx.w))

    def exitKf_zeile_liste_tx(self, ctx):
        ctx.value = KfZeileListeTx(ctx.t.value, self.getList(ctx.w))
