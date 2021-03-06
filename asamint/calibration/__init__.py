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

from collections import OrderedDict
import os

import numpy as np

from asamint.asam import AsamBaseType

from asamint.asam import TYPE_SIZES, get_section_reader
from asamint.utils import SINGLE_BITS, ffs, current_timestamp
from asamint.utils.optimize import McObject, make_continuous_blocks
from asamint.calibration import model as cmod

from pya2l.api.inspect import Characteristic, AxisPts
from pya2l.functions import CompuMethod, fix_axis_par, fix_axis_par_dist

import pya2l.model as model

from objutils import dump, load, Image, Section

AXES = ("x", "y", "z", "4", "5")

class CalibrationData(AsamBaseType):
    """Fetch calibration parameters from HEX file or XCP slave and create an in-memory representation.

    Parameters
    ----------
    project_config

    experiment_config

    Note
    ----
    This is meant as a base-class for CDF, DCM, ...
    Don't use directly.
    """

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self.a2l_epk = self.epk_from_a2l()
        self._parameters = {
            k: OrderedDict() for k in (
                "AXIS_PTS", "VALUE", "VAL_BLK", "ASCII", "CURVE", "MAP", "CUBOID", "CUBE_4", "CUBE_5"
            )
        }

    def load_hex(self):
        self._load_axis_pts()
        self._load_values()
        self._load_asciis()
        self._load_value_blocks()
        self._load_curves()
        self._load_maps()
        self._load_cubes()

    def check_epk_xcp(self, xcp_master):
        """Compare EPK (EPROM Kennung) from A2L with EPK from ECU.

        Returns
        -------
            - True:     EPKs are matching.
            - False:    EPKs are not matching.
            - None:     EPK not configured in MOD_COMMON.
        """
        if not self.a2l_epk:
            return None
        epk_a2l, epk_addr = self.a2l_epk
        xcp_master.setMta(epk_addr)
        epk_xcp = xcp_master.pull(len(epk_a2l)).decode("ascii")
        ok = epk_xcp == epk_a2l
        if not ok:
            self.logger.warn("EPK is invalid -- A2L: '{}' got '{}'.".format(self.mod_par.epk, epk))
        else:
            self.logger.info("OK, found matching EPK.")
        return ok

    def epk_from_a2l(self):
        """Read EPK from A2L database.

        Returns
        -------
        tuple: (epk, address)
        """
        if self.mod_par.addrEpk is None:
            return None
        elif self.mod_par.epk is None:
            return None
        else:
            addr = self.mod_par.addrEpk[0]
            epk = self.mod_par.epk
            return (epk, addr)

    def save_parameters(self, xcp_master = None, hexfile: str = None, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------
        xcp_master:

        hexfile: str
            if None, `MASTER_HEXFILE` and `MASTER_HEXFILE_TYPE` from project_config is used.

        hexfile_type: "ihex" | "srec"
        """
        if xcp_master:
            image = self.upload_parameters(xcp_master)
            image.file_name = None
            self.logger.info("Using image from XCP slave")
        else:
            if not hexfile:
                hexfile = self.project_config.get("MASTER_HEXFILE")
                hexfile_type = self.project_config.get("MASTER_HEXFILE_TYPE")
            with open("{}".format(hexfile), "rb") as inf:
                image = load(hexfile_type, inf)
            image.file_name = hexfile
            self.logger.info("Using image from HEX file '{}'".format(hexfile))
        if not image:
            raise ValueError("")
        else:
            self._image = image
        self.load_hex()
        self.save()

    def upload_parameters(self, xcp_master, save_to_file: bool = True, hexfile_type: str = "ihex"):
        """
        Parameters
        ----------

        xcp_master:

        save_to_file: bool

        hexfile_type: "ihex" | "srec"


        Returns
        -------
        `Image`

        """
        if hexfile_type:
            hexfile_type = hexfile_type.lower()
        if not hexfile_type in ("ihex", "srec"):
            raise ValueError("'file_type' must be either 'ihex' or 'srec'")
        result = []
        a2l_epk = self.a2l_epk
        if a2l_epk:
            epk, address = a2l_epk
            result.append(McObject("EPK", address, len(epk)))
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            ax = AxisPts.get(self.session, a.name)
            mem_size = ax.total_allocated_memory
            result.append(McObject(
                ax.name, ax.address, mem_size)
            )
        characteristics = self.query(model.Characteristic).order_by(model.Characteristic.type, model.Characteristic.address).all()
        for c in characteristics:
            chx = Characteristic.get(self.session, c.name)
            mem_size = chx.total_allocated_memory
            result.append(McObject(
                chx.name, chx.address, mem_size)
            )
        blocks = make_continuous_blocks(result)
        sections = []
        for block in blocks:
            xcp_master.setMta(block.address)
            mem = xcp_master.pull(block.length)
            sections.append(Section(start_address = block.address, data = mem))
        img = Image(sections = sections, join = False)
        if save_to_file:
            file_name = "CalParams{}.{}".format(current_timestamp(), "hex" if hexfile_type == "ihex" else "srec")
            file_name = os.path.join(self.sub_dir("hexfiles"), file_name)
            with open("{}".format(file_name), "wb") as outf:
                dump(hexfile_type, outf, img, row_length = 32)
            self.logger.info("CalParams written to {}".format(file_name))
        return img

    def _load_asciis(self):
        for chx in self.characteristics("ASCII"):
            self.logger.debug("Processing ASCII '{}' @ 0x{:08x}".format(chx.name, chx.address))
            if chx.matrixDim:
                length = chx.matrixDim["x"]
            else:
                length = chx.number
            value = self.image.read_string(chx.address, length = length)
            self._parameters["ASCII"][chx.name] = cmod.Ascii(
                name = chx.name,
                comment = chx.longIdentifier,
                category = "ASCII",
                value = value,
                displayIdentifier = chx.displayIdentifier,
                length = length
            )

    def _load_value_blocks(self):
        for chx in self.characteristics("VAL_BLK"):
            self.logger.debug("Processing VAL_BLK '{}' @ 0x{:08x}".format(chx.name, chx.address))
            reader = get_section_reader(chx.fnc_asam_dtype, self.byte_order(chx))
            raw_values = self.image.read_ndarray(
                addr = chx.address,
                length = chx.fnc_allocated_memory,
                dtype = reader,
                shape = chx.fnc_np_shape,
                order = chx.fnc_np_order,
                bit_mask = chx.bitMask
            )
            converted_values = self.int_to_physical(chx, raw_values)
            self._parameters["VAL_BLK"][chx.name] = cmod.ValueBlock(
                name = chx.name,
                comment = chx.longIdentifier,
                category = "VAL_BLK",
                raw_values = raw_values,
                converted_values = converted_values,
                displayIdentifier = chx.displayIdentifier,
                shape = chx.fnc_np_shape,
                unit = chx.physUnit,
            )

    def _load_values(self):
        for chx in self.characteristics("VALUE"):
            self.logger.debug("Processing VALUE '{}' @ 0x{:08x}".format(chx.name, chx.address))
            # CALIBRATION_ACCESS
            # READ_ONLY
            fnc_asam_dtype = chx.fnc_asam_dtype
            fnc_np_dtype = chx.fnc_np_dtype
            reader = get_section_reader(fnc_asam_dtype, self.byte_order(chx))
            if chx.bitMask:
                raw_value = self.image.read_numeric(chx.address, reader, bit_mask = chx.bitMask)
                raw_value >>= ffs(chx.bitMask) # Right-shift to get rid of trailing zeros (s. ASAM 2-MC spec).
                is_bool = True if chx.bitMask in SINGLE_BITS else False
            else:
                raw_value = self.image.read_numeric(chx.address, reader)
                is_bool = False
            if chx.physUnit is None and chx._conversionRef != "NO_COMPU_METHOD":
                unit = chx.compuMethod.unit
            else:
                unit = chx.physUnit
            converted_value = self.int_to_physical(chx, raw_value)

            if isinstance(converted_value, (int, float)):
                if is_bool:
                    category = "BOOLEAN"
                    converted_value = "true" if bool(converted_value) else "false"
                else:
                    category = "VALUE"
            else:
                category = "TEXT"
            if chx.dependentCharacteristic:
                category = "DEPENDENT_VALUE"
            self._parameters["VALUE"][chx.name] = cmod.Value(
                name = chx.name,
                comment = chx.longIdentifier,
                category = category,
                raw_value = raw_value,
                converted_value = converted_value,
                displayIdentifier = chx.displayIdentifier,
                unit = unit,
            )


    def _load_axis_pts(self):
        for item in self.axis_points():
            ap = AxisPts.get(self.session, item.name)
            mem_size = ap.total_allocated_memory
            self.logger.debug("Processing AXIS_PTS '{}' @ 0x{:08x}".format(ap.name, ap.address))
            rl_values = self.read_record_layout_values(ap, "x")
            self.record_layout_correct_offsets(ap)
            virtual = False
            axis = ap.record_layout_components.axes("x")
            paired = False
            if 'axisRescale' in axis:
                category = "RES_AXIS"
                paired = True
                if 'noRescale' in rl_values:
                    no_rescale_pairs = rl_values["noRescale"]
                else:
                    no_rescale_pairs = axis['maxNumberOfRescalePairs']
                index_incr = axis['axisRescale']['indexIncr']
                count = no_rescale_pairs * 2
                attr = "axisRescale"
            elif 'axisPts' in axis:
                category = "COM_AXIS"
                if 'noAxisPts' in rl_values:
                    no_axis_points = rl_values['noAxisPts']
                else:
                    no_axis_points = axis['maxAxisPoints']
                index_incr = axis['axisPts']['indexIncr']
                count = no_axis_points
                attr = "axisPts"
            elif 'offset' in axis:
                category = "FIX_AXIS"
                virtual = True  # Virtual / Calculated axis.
                offset = rl_values.get("offset")
                dist_op = rl_values.get("distOp")
                shift_op = rl_values.get("shiftOp")
                if 'noAxisPts' in rl_values:
                    no_axis_points = rl_values['noAxisPts']
                else:
                    no_axis_points = axis['maxAxisPoints']
                if (dist_op or shift_op) is None:
                    raise TypeError("Malformed AXIS_PTS '{}', neither DIST_OP nor SHIFT_OP specified.".format(ap))
                if not dist_op is None:
                    raw_values = fix_axis_par_dist(offset, dist_op, no_axis_points)
                else:
                    raw_values = fix_axis_par(offset, shift_op, no_axis_points)
            else:
                raise TypeError("Malformed AXIS_PTS '{}'.".format(ap))
            if not virtual:
                raw_values = self.read_nd_array(ap, "x", attr, count)
                if index_incr == 'INDEX_DECR':
                    raw_values = raw_values[::-1]
                    reversed_storage = True
                else:
                    reversed_storage = False
            converted_values = self.int_to_physical(ap, raw_values)
            if ap._conversionRef != "NO_COMPU_METHOD":
                unit = ap.compuMethod.refUnit
            else:
                unit = None
            self._parameters["AXIS_PTS"][ap.name] = cmod.AxisPts(
                name = ap.name,
                comment = ap.longIdentifier,
                category = category,
                raw_values = raw_values,
                converted_values = converted_values,
                displayIdentifier = ap.displayIdentifier,
                paired = paired,
                unit = unit,
                reversed_storage = reversed_storage
            )

    def _load_curves(self):
        self._load_curves_and_maps("CURVE", 1)

    def _load_maps(self):
        self._load_curves_and_maps("MAP", 2)

    def _load_cubes(self):
        self._load_curves_and_maps("CUBOID", 3)
        self._load_curves_and_maps("CUBE_4", 4)
        self._load_curves_and_maps("CUBE_5", 5)

    def _order_curves(self, curves):
        """Remove forward references from CURVE list."""
        curves = list(curves)[: : 1]    # Don't destroy the generator, make a copy.
        curves_by_name = {c.name: (pos, c) for pos, c in enumerate(curves)}
        while True:
            ins_pos = 0
            for curr_pos in range(len(curves)):
                curve = curves[curr_pos]
                axis_descr = curve.axisDescriptions[0]
                if axis_descr.attribute == "CURVE_AXIS":
                    if axis_descr.curveAxisRef.name in curves_by_name:
                        ref_pos, ref_curve = curves_by_name.get(axis_descr.curveAxisRef.name)
                        if ref_pos > curr_pos:
                            # Swap
                            t_curve = curves[ins_pos]
                            curves[ins_pos] = curves[ref_pos]
                            curves[ref_pos] = t_curve
                            curves_by_name[curves[ins_pos].name] = (ins_pos, curves[ins_pos])
                            curves_by_name[curves[ref_pos].name] = (ref_pos, curves[ref_pos])
                            ins_pos += 1
            if ins_pos == 0:
                break   # No more swaps, we're done.
        return curves

    def _load_curves_and_maps(self, category: str, num_axes:int):
        characteristics = self.characteristics(category)
        if num_axes == 1:
             # CURVEs may reference other CURVEs, so some ordering is required.
            characteristics = self._order_curves(characteristics)
        for chx in characteristics:
            self.logger.debug("Processing {} '{}' @ 0x{:08x}".format(category, chx.name, chx.address))
            chx_cm = chx.compuMethod
            fnc_cm = CompuMethod(self.session, chx_cm)
            fnc_unit = chx.compuMethod.unit
            fnc_datatype = chx.record_layout_components.fncValues["datatype"]
            self.record_layout_correct_offsets(chx)
            num_func_values = 1
            shape = []
            axes = []
            for axis_idx in range(num_axes):
                axis_descr = chx.axisDescriptions[axis_idx]
                axis_name = AXES[axis_idx]
                maxAxisPoints = axis_descr.maxAxisPoints
                axis_pts_cm = axis_descr.compuMethod
                if axis_pts_cm != "NO_COMPU_METHOD":
                    axis_cm = CompuMethod(self.session, axis_pts_cm)
                else:
                    axis_cm = None
                if axis_cm:
                    axis_unit = axis_descr.compuMethod.unit
                axis_attribute = axis_descr.attribute
                axis = chx.record_layout_components.axes(axis_name)
                fix_no_axis_pts = chx.deposit.fixNoAxisPts.get(axis_name)
                rl_values = self.read_record_layout_values(chx, axis_name)
                curve_axis_ref = None
                axis_pts_ref = None
                reversed_storage = False
                flipper = []
                if fix_no_axis_pts:
                    no_axis_points = fix_no_axis_pts
                else:
                    if 'noAxisPts' in rl_values:
                        no_axis_points = rl_values['noAxisPts']
                    elif 'noRescale' in rl_values:
                        no_axis_points = rl_values['noRescale']
                    else:
                        no_axis_points = maxAxisPoints
                if axis_attribute == "FIX_AXIS":
                    if axis_descr.fixAxisParDist:
                        par_dist = axis_descr.fixAxisParDist
                        raw_axis_values = fix_axis_par_dist(par_dist['offset'], par_dist['distance'], par_dist['numberapo'])
                    elif axis_descr.fixAxisParList:
                        raw_axis_values = axis.fixAxisParList
                    elif axis_descr.fixAxisPar:
                        par = axis_descr.fixAxisPar
                        raw_axis_values = fix_axis_par(par['offset'], par['shift'], par['numberapo'])
                    no_axis_points = len(raw_axis_values)
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                    #print("FIX_AXIS", chx.name, hex(chx.address), chx.record_layout_components.fncValues , end ="\n\n")
                    #print("\tNO_AXIS_PTS", no_axis_points, end = " ")
                elif axis_attribute == "STD_AXIS":
                    #print("*** STD-AXIS", chx.name, hex(chx.address), chx.record_layout_components.fncValues , end ="\n\n")
                    raw_axis_values = self.read_nd_array(chx, "x", "axisPts", no_axis_points)
                    index_incr = axis['axisPts']['indexIncr']
                    if index_incr == 'INDEX_DECR':
                        raw_axis_values = raw_axis_values[::-1]
                        reversed_storage = True
                    converted_axis_values = axis_cm.int_to_physical(raw_axis_values)
                elif axis_attribute == "RES_AXIS":
                    ref_obj = self._parameters["AXIS_PTS"][axis_descr.axisPtsRef.name]
                    #no_axis_points = min(no_axis_points, len(ref_obj.raw_values) // 2)
                    #print("*** RES-AXIS", chx.name, hex(chx.address), axis_descr.axisPtsRef.name, ref_obj.raw_values[1::2], end ="\n\n")
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw_values)
                    reversed_storage = ref_obj.reversed_storage
                elif axis_attribute == "CURVE_AXIS":
                    ref_obj = self._parameters["CURVE"][axis_descr.curveAxisRef.name]
                    #print("*** CURVE-AXIS", chx.name, hex(chx.address), axis_descr.curveAxisRef.name, end ="\n\n")
                    curve_axis_ref = axis_descr.curveAxisRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw_values)
                    reversed_storage = ref_obj.axes[0].reversed_storage
                elif axis_attribute == "COM_AXIS":
                    ref_obj = self._parameters["AXIS_PTS"][axis_descr.axisPtsRef.name]
                    #print("*** COM-AXIS", chx.name, hex(chx.address), axis_descr.axisPtsRef.name, end ="\n\n")
                    axis_pts_ref = axis_descr.axisPtsRef.name
                    raw_axis_values = None
                    converted_axis_values = None
                    axis_unit = None
                    no_axis_points = len(ref_obj.raw_values)
                    reversed_storage = ref_obj.reversed_storage
                num_func_values *= no_axis_points
                shape.append(no_axis_points)
                if reversed_storage:
                    flipper.append(axis_idx)
                axes.append(cmod.AxisContainer(
                    category = axis_attribute,
                    unit = axis_unit,
                    reversed_storage = reversed_storage,
                    raw_values = raw_axis_values,
                    converted_values = converted_axis_values,
                    axis_pts_ref = axis_pts_ref,
                    curve_axis_ref = curve_axis_ref
                ))
            length = num_func_values * TYPE_SIZES[fnc_datatype]
            raw_values = self.image.read_ndarray(
                addr = chx.address + chx.record_layout_components.fncValues["offset"],
                length = length,
                dtype = get_section_reader(chx.record_layout_components.fncValues["datatype"], self.byte_order(chx)),
                shape = shape,
                #order = order,
                #bit_mask = chx.bitMask
            )
            if flipper:
                raw_values = np.flip(raw_values, axis = flipper)
            converted_values = fnc_cm.int_to_physical(raw_values)
            klass = cmod.get_calibration_class(category)
            self._parameters["{}".format(category)][chx.name] = klass(
                name = chx.name,
                comment = chx.longIdentifier,
                category = category,
                displayIdentifier = chx.displayIdentifier,
                raw_values = raw_values,
                converted_values = converted_values,
                fnc_unit = fnc_unit,
                axes = axes
            )

    def record_layout_correct_offsets(self, obj):
        """
        """
        no_axis_pts = {}
        no_rescale = {}
        axis_pts = {}
        axis_rescale = {}
        fnc_values = None
        for pos, component in obj.record_layout_components:
            component_type = component["type"]
            if component_type == "fncValues":
                fnc_values = component
            elif len(component_type) == 2:
                name, axis_name = component_type
                if name == "noAxisPts":
                    no_axis_pts[axis_name] = self.read_record_layout_value(obj, axis_name, name)
                elif name == "noRescale":
                    no_rescale[axis_name] = self.read_record_layout_value(obj, axis_name, name)
                elif name == "axisPts":
                    axis_pts[axis_name] = component
                elif name == "axisRescale":
                    axis_rescale[axis_name] = component
            else:
                pass
        biases = {}
        for key, value in no_axis_pts.items():
             axis_pt = axis_pts.get(key)
             if axis_pt:
                 max_axis_points = axis_pt["maxAxisPoints"]
                 bias = value - max_axis_points
                 biases[axis_pt["position"] + 1] = bias
        for key, value in no_rescale.items():
            axis_rescale = axis_rescale.get(key)
            if axis_rescale:
                max_number_of_rescale_pairs = axis_rescale["maxNumberOfRescalePairs"]
                bias = value - max_number_of_rescale_pairs
                biases[axis_rescale["position"] + 1] = bias
        total_bias = 0
        if biases:
            for pos, component in obj.record_layout_components:
                if pos in biases:
                    bias = biases.get(pos)
                    total_bias += bias
                component["offset"] += total_bias

    def read_record_layout_values(self, obj, axis_name):
        DATA_POINTS = (
            "distOp",
            "identification",
            "noAxisPts",
            "noRescale",
            "offset",
            "reserved",
            "ripAddr",
            "srcAddr",
            "shiftOp",
        )
        result = {}
        axis = obj.record_layout_components.axes(axis_name)
        for key in DATA_POINTS:
            if key in axis:
                result[key] = self.read_record_layout_value(obj, axis_name, key)
        return result

    def read_record_layout_value(self, obj, axis_name, component_name):
        """
        """
        axis = obj.record_layout_components.axes(axis_name)
        component_map = axis.get(component_name)
        if component_map is None:
            return None
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        reader = get_section_reader(datatype, self.byte_order(obj))
        value = self.image.read_numeric(obj.address + offset, reader)
        return value

    def read_nd_array(self, axis_pts, axis_name, component, no_elements, shape = None, order = None):
        """
        """
        axis = axis_pts.record_layout_components.axes(axis_name)
        component_map = axis[component]
        datatype = component_map["datatype"]
        offset = component_map["offset"]
        reader = get_section_reader(datatype, self.byte_order(axis_pts))

        length = no_elements * TYPE_SIZES[datatype]
        np_arr = self.image.read_ndarray(
            addr = axis_pts.address + offset,
            length = length,
            dtype = reader,
            shape = shape,
            order = order,
            #bit_mask = chx.bitMask
        )
        return np_arr

    def int_to_physical(self, characteristic, int_values):
        """
        """
        if characteristic._conversionRef != "NO_COMPU_METHOD":
            cm = CompuMethod(self.session, characteristic.compuMethod)
            converted_value = cm.int_to_physical(int_values)
        else:
            converted_value = int_values
        return converted_value

    @property
    def image(self):
        return self._image

    @property
    def parameters(self):
        return self._parameters

    def axis_points(self):
        """
        """
        axis_pts = self.query(model.AxisPts).order_by(model.AxisPts.address).all()
        for a in axis_pts:
            yield AxisPts.get(self.session, a.name)

    def characteristics(self, category):
        """
        """
        query = self.query(model.Characteristic.name).filter(model.Characteristic.type == category)
        for characteristic in query.all():
            yield Characteristic.get(self.session, characteristic.name)
