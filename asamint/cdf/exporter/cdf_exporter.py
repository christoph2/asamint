import logging
from pathlib import Path

from lxml import etree
import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy import inspect

from asamint.calibration.db import CalibrationDB
from asamint.calibration.msrsw_db import (
    ELEMENTS,
    MSRSWDatabase,
    Msrsw,
    SwInstance,
    SwValueCont,
)

class CDFExporter:
    def __init__(
        self,
        db: MSRSWDatabase,
        h5_db: CalibrationDB = None,
        variant_coding: bool = False,
        logger: logging.Logger = None,
    ):
        self.db = db
        self.h5_db = h5_db
        self.variant_coding = variant_coding
        self.logger = logger or logging.getLogger(__name__)
        self.reverse_elements = {v: k for k, v in ELEMENTS.items()}
        # Add special case for root if not in ELEMENTS
        if Msrsw not in self.reverse_elements:
            self.reverse_elements[Msrsw] = "MSRSW"

    def export(self, file_path: str | Path):
        self.logger.info(f"Exporting database to {file_path}")
        msrsw_obj = self.db.session.query(Msrsw).first()
        if not msrsw_obj:
            self.logger.error("No MSRSW object found in database.")
            return False

        root_tag = self.reverse_elements.get(type(msrsw_obj), "MSRSW")
        root_elem = self._to_xml(msrsw_obj, root_tag)

        tree = etree.ElementTree(root_elem)

        # Add DOCTYPE if possible, though it might depend on the specific version
        # For now, let's just write the XML.

        with open(file_path, "wb") as f:
            f.write(
                etree.tostring(
                    tree, encoding="UTF-8", xml_declaration=True, pretty_print=True
                )
            )

        self.logger.info("Export completed successfully.")
        return True

    def _format_tag(self, tag):
        # Specific overrides for tags that shouldn't be just upper-cased
        overrides = {
            "ShortName": "SHORT-NAME",
            "LongName": "LONG-NAME",
            "ProjectData": "PROJECT-DATA",
            "AdminData": "ADMIN-DATA",
            "GeneralRequirements": "GENERAL-REQUIREMENTS",
            "SwSystems": "SW-SYSTEMS",
            "SwSystem": "SW-SYSTEM",
            "SwMcCommunicationSpec": "SW-MC-COMMUNICATION-SPEC",
            "SwGlossary": "SW-GLOSSARY",
            "SpecialData": "SPECIAL-DATA",
            "MsrProcessingLog": "MSR-PROCESSING-LOG",
            "MatchingDcis": "MATCHING-DCIS",
            "SwInstanceSpec": "SW-INSTANCE-SPEC",
            "SwInstanceTree": "SW-INSTANCE-TREE",
            "SwInstance": "SW-INSTANCE",
            "SwInstanceTreeOrigin": "SW-INSTANCE-TREE-ORIGIN",
            "SymbolicFile": "SYMBOLIC-FILE",
            "DataFile": "DATA-FILE",
            "DisplayName": "DISPLAY-NAME",
            "SwValueCont": "SW-VALUE-CONT",
            "UnitDisplayName": "UNIT-DISPLAY-NAME",
            "SwCsCollections": "SW-CS-COLLECTIONS",
            "SwCsCollection": "SW-CS-COLLECTION",
            "SwInstancePropsVariants": "SW-INSTANCE-PROPS-VARIANTS",
            "SwInstancePropsVariant": "SW-INSTANCE-PROPS-VARIANT",
            "SwAxisConts": "SW-AXIS-CONTS",
            "SwAxisCont": "SW-AXIS-CONT",
        }
        if tag in overrides:
            return overrides[tag]

        # Fallback to a heuristic: add hyphens before capital letters and uppercase
        formatted = ""
        for i, char in enumerate(tag):
            if i > 0 and char.isupper():
                formatted += "-"
            formatted += char
        return formatted.upper()

    def _to_xml(self, obj, tag_name):
        elem = etree.Element(tag_name)
        valid_entry: bool = True
        # Handle attributes
        if hasattr(obj, "ATTRIBUTES"):
            for xml_attr, py_attr in obj.ATTRIBUTES.items():
                value = getattr(obj, py_attr, None)
                if value is not None:
                    elem.set(xml_attr, str(value))

        # Handle terminal content
        if getattr(obj, "TERMINAL", False) and hasattr(obj, "content"):
            if obj.content is not None:
                elem.text = str(obj.content)

        # Special handling for values from HDF5
        if isinstance(obj, SwValueCont) and self.h5_db:
            # Try to find the parameter name from the parent SwInstance
            # In our DB model, SwValueCont is linked from SwInstance
            instance = None

            # Check if this SwValueCont has a parent SwInstance
            # Usually SwInstance.sw_value_cont links to this

            session = inspect(obj).session
            if session:
                instance = (
                    session.query(SwInstance)
                    .filter(SwInstance.sw_value_cont == obj)
                    .first()
                )
            if instance and instance.short_name:
                param_name = instance.short_name.content
                try:
                    data = self.h5_db.load(param_name)
                    self._append_values(elem, data)

                except Exception as e:
                    self.logger.debug(
                        f"Could not load values for {param_name} from H5: {e}"
                    )
                    valid_entry = False

        # Handle child elements
        if hasattr(obj, "ELEMENTS") and valid_entry:
            for tag, (py_attr, elem_tp) in obj.ELEMENTS.items():
                # Filter based on variant_coding if object is SwInstance
                if isinstance(obj, SwInstance):
                    if self.variant_coding:
                        # VCD mode: data is in SwInstancePropsVariants
                        if tag in ("SwValueCont", "SwAxisConts"):
                            continue
                    else:
                        # NO_VCD mode: data is direct, skip variants
                        if tag == "SwInstancePropsVariants":
                            continue

                child_val = getattr(obj, py_attr, None)

                # Heuristic: if a top-level relationship is missing in Msrsw, try to find it in DB
                if child_val is None and isinstance(obj, Msrsw):
                    session = inspect(obj).session
                    if session:
                        # Find the class for this tag from ELEMENTS mapping
                        target_cls = ELEMENTS.get(tag)
                        if target_cls:
                            child_val = session.query(target_cls).first()
                            if child_val:
                                self.logger.debug(
                                    f"Found orphaned {tag} for MSRSW root"
                                )

                if child_val is None:
                    continue

                if elem_tp == "A":  # Association/List
                    for item in child_val:
                        child_tag = self._format_tag(tag)
                        child_elem = self._to_xml(item, child_tag)
                        if child_elem is not None:
                            elem.append(child_elem)
                else:  # Relationship/Single
                    child_tag = self._format_tag(tag)
                    child_elem = self._to_xml(child_val, child_tag)
                    if child_elem is not None:
                        elem.append(child_elem)

        if not valid_entry:
            return None

        return elem

    def _append_values(self, elem, data):

        category = data.attrs.get("category", "")

        # Flatten values if it's more than 1D and we just want a list of values
        # For maps and curves, CDF often uses <VG> with <V> for values.

        if category in ("VALUE", "BOOLEAN", "ASCII", "TEXT"):
            val = data.values
            tag = "VT" if category in ("ASCII", "TEXT") else "V"
            v_elem = etree.SubElement(elem, tag)
            v_elem.text = str(val)
        elif category in (
                "VAL_BLK",
                "COM_AXIS",
                "CURVE",
                "MAP",
                "CUBOID",
                "CUBE4",
                "CUBE5",
        ):
            # For multi-dimensional data, we should group by dimension with <VG> elements
            if (
                category in ("CURVE", "MAP", "VAL_BLK", "CUBOID", "CUBE4", "CUBE5")
                and len(data.dims) > 0
            ):
                if len(data.dims) == 1:
                    vg_elem = etree.SubElement(elem, "VG")
                    for v in data.values:
                        v_elem = etree.SubElement(vg_elem, "V")
                        v_elem.text = str(v)
                else:
                    # Recursive grouping for N-dimensional data
                    def _append_recursive(parent_elem, sub_data):
                        if len(sub_data.shape) == 1:
                            vg_elem = etree.SubElement(parent_elem, "VG")
                            for v in sub_data:
                                v_elem = etree.SubElement(vg_elem, "V")
                                v_elem.text = str(v)
                        else:
                            for sub_part in sub_data:
                                _append_recursive(parent_elem, sub_part)

                    _append_recursive(elem, data.values)
            else:
                vals = data.values.flatten()
                tag = "VT" if category == "ASCII" else "V"  # simplified
                for v in vals:
                    v_elem = etree.SubElement(elem, tag)
                    v_elem.text = str(v)
        else:
            # Fallback for other types
            vals = data.values.flatten()
            for v in vals:
                v_elem = etree.SubElement(elem, "V")
                v_elem.text = str(v)


def export_to_cdf(
    db_path: str | Path,
    output_xml_path: str | Path,
    h5_path: str | Path = None,
    variant_coding: bool = False,
):
    db = MSRSWDatabase(db_path)

    h5_db = None
    if h5_path:
        h5_db = CalibrationDB(h5_path, mode="r")
    else:
        # Try to find corresponding .h5 file
        potential_h5 = Path(db_path).with_suffix(".h5")
        if potential_h5.exists():
            h5_db = CalibrationDB(potential_h5, mode="r")

    exporter = CDFExporter(db, h5_db=h5_db, variant_coding=variant_coding)
    success = exporter.export(output_xml_path)

    if h5_db:
        h5_db.close()
    db.close()
    return success
