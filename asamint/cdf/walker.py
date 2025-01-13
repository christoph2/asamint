#!/usr/bin/env python

import binascii
import typing
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from asamint.calibration.msrsw_db import MSRSWDatabase, SwInstance, SwInstanceSpec
from asamint.msrsw import elements
from asamint.msrsw.elements import VG, VT, Instance
from asamint.utils import slicer


def array_values(values, flatten: bool = False):
    result = []
    for v in values:
        if isinstance(v, VG):
            if flatten:
                result.extend(array_values(v.values, flatten))
            else:
                result.append(array_values(v.values, flatten))
        else:
            result.append(v.value)
    return result


def scalar_value(values):
    value = values[0].value
    if isinstance(values[0], VT):
        value = f"'{value}'"
    return value


def axis_formatter(values):
    if all(isinstance(v, str) for v in values):
        return "   ".join([f"'{v}'" for v in values])
    else:
        return "   ".join([f"{v:8.3f}" for v in values])


def dump_array(values, level: int = 1, brackets=False) -> str:
    result = []
    for value in values:
        if isinstance(value, list):
            result.extend(["   " * level, "[" if brackets else ""])
            result.extend(dump_array(value, level + 1))
            if brackets:
                result.append("]\n")
            else:
                result.append("\n")
        else:
            if isinstance(value, (int, float, Decimal)):
                result.append(f"{value:8.3f}")
            else:
                result.append(f"'{value:20s}'")
    return "".join(result)


def reshape(arr, dim: tuple[int]):
    if not dim:
        return arr
    tmp = deepcopy(arr)
    for sl in dim:
        tmp = slicer(tmp, sl)
    tmp = tmp[0]
    return tmp


def convert_timestamp(ts: str, fmt: str = "%Y-%m-%dT%H:%M:%S") -> datetime:  # "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(ts, fmt)


def get_content(attr: typing.Any, default: typing.Any | None = None, converter: typing.Callable | None = None):
    value = getattr(attr, "content") if attr else default
    if converter is not None:
        try:
            value = converter(value)
        except Exception as e:
            print(str(e))
    return value


@dataclass
class ValueContainer:
    unit_display_name: str
    array_size: tuple[int]
    values: list[typing.Any]


@dataclass
class AxisContainer:
    category: str
    unit_display_name: str
    array_size: tuple[int]
    instance_ref: str
    values: list[typing.Any]


@dataclass
class CalibrationParameter:
    short_name: str
    display_name: str
    category: str
    long_name: str
    feature_ref: str
    model_link: str
    axes: elements.AxisContainer
    values: ValueContainer


class CdfWalker:

    def __init__(self, db_name: str) -> None:
        self.db = MSRSWDatabase(db_name)
        self.session = self.db.session

    def on_instance(self, instance: elements.Instance) -> None:
        raise NotImplementedError("CdfWalker::on_instance() must be overriten")

    def on_header(self, shortname: str, a2l_file: str, hex_file: str, references: list, variants: bool):
        raise NotImplementedError("CdfWalker::on_header() must be overriten")

    def do_shortname(self, sn):
        content = get_content(sn, "")
        return elements.ShortName(content)

    def do_longname(self, ln):
        content = get_content(ln, "")
        return elements.LongName(content)

    def do_displayname(self, dn):
        content = get_content(dn, "")
        return elements.DisplayName(content)

    def do_category(self, cat):
        content = get_content(cat, "")
        return elements.Category(content)

    def do_feature_ref(self, ref):
        ref = get_content(ref)
        return elements.A2LFunction(ref)

    def do_instance_ref(self, ref):
        ref = get_content(ref)
        return elements.InstanceRef(ref)

    def do_sw_model_link(self, link):
        link = get_content(link)
        return elements.ModelLink(link)

    def do_unit_display_name(self, name):
        name = get_content(name, "")
        return elements.UnitDisplayName(name)

    def do_vs(self, vs):
        if vs:
            return [elements.V(v.content) for v in vs]
        else:
            return []

    def do_vfs(self, vfs):
        if vfs:
            return [elements.VF(v.content) for v in vfs]
        else:
            return []

    def do_vts(self, vts):
        if vts:
            return [elements.VT(v.content) for v in vts]
        else:
            return []

    def do_vhs(self, vhs):
        if vhs:
            result = []
            for v in vhs:
                content = v.content.strip()
                try:
                    content = binascii.unhexlify(content)
                except binascii.Error:
                    pass
                result.append(elements.VH(content))
            return result
        else:
            return []

    def do_array_size(self, arr):
        if arr:
            values = []
            values.extend(self.do_vfs(arr.vfs))
            values.extend(self.do_vs(arr.vs))
            return elements.ArraySize(tuple(int(v.value) for v in values))
        else:
            return elements.ArraySize(())

    def do_array_index(self, arr):
        return elements.ArrayIndex(get_content(arr))

    def do_sw_cs_flags(self, flags):
        if flags:
            category = self.do_category(flags.category)
            flag = get_content(flags.flag, None, bool)
            csus = get_content(flags.csus)
            date = get_content(flags.date, None, convert_timestamp)
            remark = self.do_remark(flags.remark)
            return elements.Flags(category, flag, csus, date, remark)
        else:
            return None

    def do_remark(self, remark):
        if remark.ps:
            result = []
            for p in remark.ps:
                result.append(elements.P(get_content(p)))
            return result
        else:
            return elements.Remark([])

    def do_vgs(self, vgs):
        result = []
        for item in vgs:
            vg = elements.VG()
            if item.label:
                vg.label = item.label.content
            if item.vs:
                vg.values.extend(self.do_vs(item.vs))
            elif item.vfs:
                vg.values.extend(self.do_vfs(item.vfs))
            elif item.vts:
                vg.values.extend(self.do_vts(item.vts))
            elif item.vhs:
                vg.values.extend(self.do_vhs(item.vhs))
            if item.children:
                vg.values.extend(self.do_vgs(item.children))
            result.append(vg)
        return result

    def do_values(self, values):
        if values is None:
            return []
        result = []
        if values.vs:
            result.extend(self.do_vs(values.vs))
        if values.vgs:
            result.extend(self.do_vgs(values.vgs))
        if values.vts:
            result.extend(self.do_vts(values.vts))
        if values.vfs:
            result.extend(self.do_vfs(values.vfs))
        if values.vhs:
            result.extend(self.do_vhs(values.vhs))
        return result

    def do_sw_values_coded(self, values):
        return self.do_values(values)

    def do_sw_values_phys(self, values):
        return self.do_values(values)

    def do_value_cont(self, cont):
        if cont is None:
            return elements.ValueContainer(None, None, [])
        display_name = self.do_unit_display_name(cont.unit_display_name)
        array_size = self.do_array_size(cont.sw_arraysize)
        values = []
        if cont.sw_values_phys:
            values = self.do_sw_values_phys(cont.sw_values_phys)
        if cont.sw_values_coded:
            values = self.do_sw_values_coded(cont.sw_values_coded)
        return elements.ValueContainer(display_name, array_size, values)

    def do_axis_conts(self, cont):
        result = []
        if cont:
            for item in cont.sw_axis_cont:
                category = self.do_category(item.category)
                unit_display_name = self.do_unit_display_name(item.unit_display_name)
                values = self.do_sw_values_phys(item.sw_values_phys)
                array_size = self.do_array_size(item.sw_arraysize)
                instance_ref = self.do_instance_ref(item.sw_instance_ref)
                # print("\tAX:", cont.category.value, cont.unit_display_name, cont.array_size.dimensions, cont.instance_ref.name, walker.axis_formatter(walker.array_values(cont.values))
                result.append(
                    AxisContainer(
                        category.value, unit_display_name.value, array_size, instance_ref, array_values(values, flatten=True)
                    )
                )
        return result

    def do_sw_cs_history(self, history):
        result = []
        if history is not None:
            for entry in history.cs_entry:
                state = get_content(entry.state)
                date = get_content(entry.date, None, convert_timestamp)
                csus = get_content(entry.csus)
                cspr = get_content(entry.cspr)
                cswp = get_content(entry.cswp)
                csto = get_content(entry.csto)
                cstv = get_content(entry.cstv)
                cspi = get_content(entry.cspi)
                csdi = get_content(entry.csdi)
                remark = self.do_remark(entry.remark)
                result.append(elements.HistoryEntry(state, date, csus, cspr, cswp, csto, cstv, cspi, csdi, remark))
        return result

    def do_sw_vcd_criterion_ref(self, ref):
        ref = get_content(ref)
        return elements.CriterionRef(ref)

    def do_sw_vcd_criterion_values(self, values):
        result = []
        if values is not None:
            for value in values.sw_vcd_criterion_value:
                ref = self.do_sw_vcd_criterion_ref(value.sw_vcd_criterion_ref)
                vt = self.do_vts(value.vts)
                result.append(elements.CriterionValue(ref, vt))
        return result

    def do_sw_cs_collection(self, collections):
        sw_collection = []
        if collections is not None and collections.sw_cs_collection:
            for coll in collections.sw_cs_collection:
                if coll.category.content == "FEATURE":
                    sw_collection.append(elements.A2LFunction(coll.sw_feature_ref.content))  # A2L FUNCTION
                elif coll.category.content == "COLLECTION":
                    sw_collection.append(elements.A2LGroup(coll.sw_collection_ref.content))  # A2L GROUP
        return sw_collection

    def do_sw_instance_props_variants(self, variants):
        result = []
        if variants is not None:
            for variant in variants.sw_instance_props_variant:
                value_container = self.do_value_cont(variant.sw_value_cont)
                axis_containers = self.do_axis_conts(variant.sw_axis_conts)
                history = self.do_sw_cs_history(variant.sw_cs_history)
                flags = self.do_sw_cs_flags(variant.sw_cs_flags)
                crit_values = self.do_sw_vcd_criterion_values(variant.sw_vcd_criterion_values)
                result.append(elements.InstancePropsVariant(crit_values, value_container, axis_containers, history, flags))
        return result

    def do_instance(self, inst):

        shortname = self.do_shortname(inst.short_name).value
        longname = self.do_longname(inst.short_name).value
        displayname = self.do_displayname(inst.display_name).value
        category = self.do_category(inst.category).value
        feature_ref = self.do_feature_ref(inst.sw_feature_ref).name
        model_link = self.do_sw_model_link(inst.sw_model_link).value

        value_container = self.do_value_cont(inst.sw_value_cont)
        axis_containers = self.do_axis_conts(inst.sw_axis_conts)

        # TODO: conversion routines, e.g. '', or "" around strings, FORMATs, and the like, if A2L is available.
        array_size = value_container.array_size.dimensions
        match category:
            case "VALUE" | "DEPENDENT_VALUE" | "BOOLEAN" | "ASCII":
                values = scalar_value(value_container.values)
            case "COM_AXIS" | "CURVE_AXIS" | "RES_AXIS" | "CURVE":
                values = array_values(value_container.values, flatten=True)
            case "VAL_BLK" | "MAP" | "CUBOID" | "CUBE_4" | "CUBE_5":
                if array_size:
                    values = array_values(value_container.values, flatten=True)
                    values = reshape(values, array_size)
                else:
                    values = array_values(value_container.values, flatten=False)
            case "BLOB":
                values = array_values(value_container.values, flatten=True)
            case _:
                raise ValueError(category)

        vc = ValueContainer(value_container.unit_display_name.value or "", array_size, values)

        cp = CalibrationParameter(shortname, displayname, category, longname, feature_ref, model_link, axis_containers, vc)
        # print("\tCP:", cp)

        history = self.do_sw_cs_history(inst.sw_cs_history)
        array_index = self.do_array_index(inst.sw_array_index)
        flags = self.do_sw_cs_flags(inst.sw_cs_flags)
        variants = self.do_sw_instance_props_variants(inst.sw_instance_props_variants)
        children = []
        for ch in inst.children:
            children.append(self.do_instance(ch))
        inst = elements.Instance(
            shortname,
            array_index,
            longname,
            displayname,
            category,
            feature_ref,
            vc,
            axis_containers,
            history,
            flags,
            model_link,
            variants,
            children,
        )
        return cp

    def run(self):
        spec = self.session.query(SwInstanceSpec).first()
        tree = spec.sw_instance_tree[0]
        collections = tree.sw_cs_collections
        shortname = self.do_shortname(tree.short_name)
        category = self.do_category(tree.category)
        orig = tree.sw_instance_tree_origin
        if orig:
            a2l_file = get_content(orig.symbolic_file)
            hex_file = get_content(orig.data_file)
        else:
            a2l_file = None
            hex_file = None

        sw_collection = self.do_sw_cs_collection(collections)

        self.on_header(shortname.value, a2l_file, hex_file, sw_collection, category.value == "VCD")
        for inst in self.session.query(SwInstance).all():
            self.on_instance(self.do_instance(inst))
