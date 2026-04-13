#!/usr/bin/env python

import binascii
import logging
from collections.abc import Callable
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from typing import Any

from asamint.calibration.msrsw_db import MSRSWDatabase, SwInstance, SwInstanceSpec
from asamint.msrsw import elements
from asamint.msrsw.elements import VG, VT
from asamint.utils import slicer

logger = logging.getLogger(__name__)


def array_values(values: list[Any], flatten: bool = False) -> list[Any]:
    result: list[Any] = []
    for v in values:
        if isinstance(v, VG):
            if flatten:
                result.extend(array_values(v.values, flatten))
            else:
                result.append(array_values(v.values, flatten))
        else:
            result.append(v.phys)
    return result


def scalar_value(values: list[Any]) -> Any:
    value = values[0].phys
    if isinstance(values[0], VT):
        value = f"'{value}'"
    return value


def axis_formatter(values: list[Any]) -> str:
    if all(isinstance(v, str) for v in values):
        return "   ".join([f"'{v}'" for v in values])
    else:
        return "   ".join([f"{v:8.3f}" for v in values])


def dump_array(values: list[Any], level: int = 1, brackets: bool = False) -> str:
    result = []
    for value in values:
        if isinstance(value, list):
            result.append("   " * level)
            if brackets:
                result.append("[")
            result.append(dump_array(value, level + 1))
            if brackets:
                result.append("]\n")
            else:
                result.append("\n")
        elif isinstance(value, (int, float, Decimal)):
            result.append(f"{value:8.3f}")
        else:
            result.append(f"{value!r:20}")
    return " ".join(result)


def reshape(arr: list[Any], dim: tuple[int, ...]) -> list[Any]:
    if not dim:
        return arr
    tmp = deepcopy(arr)
    for sl in dim:
        tmp = slicer(tmp, sl)
    tmp = tmp[0]
    return tmp


def convert_timestamp(ts: str, fmt: str = "%Y-%m-%dT%H:%M:%S") -> datetime:  # "%Y-%m-%d %H:%M:%S"
    return datetime.strptime(ts, fmt)


def get_content(
    attr: Any,
    default: Any | None = None,
    converter: Callable[..., Any] | None = None,
) -> Any:
    value = attr.content if attr else default
    if converter is not None:
        try:
            value = converter(value)
        except (ValueError, TypeError) as e:
            logger.warning("Converter failed for attr %r: %s", attr, e)
    return value


class CdfWalker:
    def __init__(self, db_name: str) -> None:
        self.db = MSRSWDatabase(db_name)
        self.session = self.db.session

    def on_instance(self, instance: elements.Instance) -> None:
        raise NotImplementedError("CdfWalker::on_instance() must be overriten")

    def on_header(
        self,
        shortname: str,
        a2l_file: str,
        hex_file: str,
        references: list[Any],
        variants: bool,
    ) -> None:
        raise NotImplementedError("CdfWalker::on_header() must be overriten")

    def do_shortname(self, sn: Any) -> elements.ShortName:
        content = get_content(sn, "")
        return elements.ShortName(content)

    def do_longname(self, ln: Any) -> elements.LongName:
        content = get_content(ln, "")
        return elements.LongName(content)

    def do_displayname(self, dn: Any) -> elements.DisplayName:
        content = get_content(dn, "")
        return elements.DisplayName(content)

    def do_category(self, cat: Any) -> elements.Category:
        content = get_content(cat, "")
        return elements.Category(content)

    def do_feature_ref(self, ref: Any) -> elements.A2LFunction:
        ref = get_content(ref)
        return elements.A2LFunction(ref)

    def do_instance_ref(self, ref: Any) -> elements.InstanceRef:
        ref = get_content(ref)
        return elements.InstanceRef(ref)

    def do_sw_model_link(self, link: Any) -> elements.ModelLink:
        link = get_content(link)
        return elements.ModelLink(link)

    def do_unit_display_name(self, name: Any) -> elements.UnitDisplayName:
        name = get_content(name, "")
        return elements.UnitDisplayName(name)

    def do_vs(self, vs: Any) -> list[elements.V]:
        if vs:
            return [elements.V(phys=v.content) for v in vs]
        else:
            return []

    def do_vfs(self, vfs: Any) -> list[elements.VF]:
        if vfs:
            return [elements.VF(phys=v.content) for v in vfs]
        else:
            return []

    def do_vts(self, vts: Any) -> list[elements.VT]:
        if vts:
            return [elements.VT(phys=v.content) for v in vts]
        else:
            return []

    def do_vhs(self, vhs: Any) -> list[elements.VH]:
        if vhs:
            result = []
            for v in vhs:
                content = v.content.strip()
                try:
                    content = binascii.unhexlify(content)
                except binascii.Error:
                    pass
                result.append(elements.VH(phys=content))
            return result
        else:
            return []

    def do_array_size(self, arr: Any) -> elements.ArraySize:
        if arr:
            values = []
            values.extend(self.do_vfs(arr.vfs))
            values.extend(self.do_vs(arr.vs))
            return elements.ArraySize(tuple(int(v.phys) for v in values))
        else:
            return elements.ArraySize(())

    def do_array_index(self, arr: Any) -> elements.ArrayIndex:
        return elements.ArrayIndex(get_content(arr))

    def do_sw_cs_flags(self, flags: Any) -> elements.Flags | None:
        if flags:
            category = self.do_category(flags.category)
            flag = get_content(flags.flag, None, bool)
            csus = get_content(flags.csus)
            date = get_content(flags.date, None, convert_timestamp)
            remark = self.do_remark(flags.remark)
            return elements.Flags(category, flag, csus, date, remark)
        else:
            return None

    def do_remark(self, remark: Any) -> list[elements.P] | elements.Remark:
        if remark.ps:
            result = []
            for p in remark.ps:
                result.append(elements.P(get_content(p)))
            return result
        else:
            return elements.Remark([])

    def do_vgs(self, vgs: Any) -> list[elements.VG]:
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

    def do_values(self, values: Any) -> list[Any]:
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

    def do_sw_values_coded(self, values: Any) -> list[Any]:
        return self.do_values(values)

    def do_sw_values_phys(self, values: Any) -> list[Any]:
        return self.do_values(values)

    def do_value_cont(self, cont: Any) -> elements.ValueContainer:
        if cont is None:
            return elements.ValueContainer(unit_display_name=None, array_size=(), values_phys=[], values_int=[])
        display_name = self.do_unit_display_name(cont.unit_display_name)
        array_size = self.do_array_size(cont.sw_arraysize)
        if cont.sw_values_phys:
            values_phys = self.do_sw_values_phys(cont.sw_values_phys)
        if cont.sw_values_coded:
            values_int = self.do_sw_values_coded(cont.sw_values_coded)
        else:
            values_int = []
        return elements.ValueContainer(
            unit_display_name=display_name,
            array_size=array_size,
            values_phys=values_phys,
            values_int=values_int,
        )

    def do_axis_conts(self, cont: Any) -> list[elements.AxisContainer]:
        result = []
        if cont:
            for item in cont.sw_axis_cont:
                category = self.do_category(item.category)
                unit_display_name = self.do_unit_display_name(item.unit_display_name)
                if item.sw_values_phys:
                    values_phys = self.do_sw_values_phys(item.sw_values_phys)
                else:
                    values_phys = []
                if item.sw_values_coded:
                    values_int = self.do_sw_values_coded(item.sw_values_coded)
                else:
                    values_int = []
                array_size = self.do_array_size(item.sw_arraysize)
                instance_ref = self.do_instance_ref(item.sw_instance_ref)
                result.append(
                    elements.AxisContainer(
                        category=category.value,
                        unit_display_name=unit_display_name.value,
                        array_size=array_size,
                        values_phys=values_phys,
                        values_int=values_int,
                        instance_ref=instance_ref,
                    )
                )
        return result

    def do_sw_cs_history(self, history: Any) -> list[elements.HistoryEntry]:
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

    def do_sw_vcd_criterion_ref(self, ref: Any) -> elements.CriterionRef:
        ref = get_content(ref)
        return elements.CriterionRef(ref)

    def do_sw_vcd_criterion_values(self, values: Any) -> list[elements.CriterionValue]:
        result = []
        if values is not None:
            for value in values.sw_vcd_criterion_value:
                ref = self.do_sw_vcd_criterion_ref(value.sw_vcd_criterion_ref)
                vt = self.do_vts(value.vts)
                result.append(elements.CriterionValue(ref, vt))
        return result

    def do_sw_cs_collection(self, collections: Any) -> list[elements.A2LFunction | elements.A2LGroup]:
        sw_collection = []
        if collections is not None and collections.sw_cs_collection:
            for coll in collections.sw_cs_collection:
                if coll.category.content == "FEATURE":
                    sw_collection.append(elements.A2LFunction(coll.sw_feature_ref.content))  # A2L FUNCTION
                elif coll.category.content == "COLLECTION":
                    sw_collection.append(elements.A2LGroup(coll.sw_collection_ref.content))  # A2L GROUP
        return sw_collection

    def do_sw_instance_props_variants(self, variants: Any) -> list[elements.InstancePropsVariant]:
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

    def do_instance(self, inst: Any) -> elements.CalibrationParameter:

        shortname = self.do_shortname(inst.short_name).value
        longname = self.do_longname(inst.short_name).value
        displayname = self.do_displayname(inst.display_name).value
        category = self.do_category(inst.category).value
        feature_ref = self.do_feature_ref(inst.sw_feature_ref).name
        model_link = self.do_sw_model_link(inst.sw_model_link).value

        value_container = self.do_value_cont(inst.sw_value_cont)
        axis_containers = self.do_axis_conts(inst.sw_axis_conts)
        cp = elements.CalibrationParameter(
            shortname,
            displayname,
            category,
            longname,
            feature_ref,
            model_link,
            axis_containers,
            value_container,
        )

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
            value_container,
            axis_containers,
            history,
            flags,
            model_link,
            variants,
            children,
        )
        return cp

    def run(self) -> None:
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
