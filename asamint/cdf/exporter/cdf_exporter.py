import logging
from pathlib import Path

from lxml import etree
from sqlalchemy import inspect

from asamint.calibration.db import CalibrationDB
from asamint.calibration.msrsw_db import (
    ELEMENTS,
    Msrsw,
    MSRSWDatabase,
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
        self._apply_xml_attributes(elem, obj)
        self._apply_terminal_content(elem, obj)
        if not self._populate_value_container(elem, obj):
            return None
        self._append_children(elem, obj)
        return elem

    def _append_values(self, elem, data):
        category = data.attrs.get("category", "")
        if category in ("VALUE", "BOOLEAN", "ASCII", "TEXT"):
            self._append_scalar_value(
                elem, data.values, "VT" if category in ("ASCII", "TEXT") else "V"
            )
            return
        if category in (
            "VAL_BLK",
            "COM_AXIS",
            "CURVE",
            "MAP",
            "CUBOID",
            "CUBE4",
            "CUBE5",
        ):
            self._append_array_values(elem, data, category)
            return
        self._append_flat_values(elem, data.values.flatten(), "V")

    def _apply_xml_attributes(self, elem, obj) -> None:
        if not hasattr(obj, "ATTRIBUTES"):
            return
        for xml_attr, py_attr in obj.ATTRIBUTES.items():
            value = getattr(obj, py_attr, None)
            if value is not None:
                elem.set(xml_attr, str(value))

    @staticmethod
    def _apply_terminal_content(elem, obj) -> None:
        if (
            getattr(obj, "TERMINAL", False)
            and hasattr(obj, "content")
            and obj.content is not None
        ):
            elem.text = str(obj.content)

    def _populate_value_container(self, elem, obj) -> bool:
        if not isinstance(obj, SwValueCont) or not self.h5_db:
            return True
        param_name = self._value_container_name(obj)
        if not param_name:
            return True
        try:
            self._append_values(elem, self.h5_db.load(param_name))
            return True
        except Exception as e:
            self.logger.debug(f"Could not load values for {param_name} from H5: {e}")
            return False

    def _value_container_name(self, obj) -> str | None:
        session = inspect(obj).session
        if not session:
            return None
        instance = (
            session.query(SwInstance).filter(SwInstance.sw_value_cont == obj).first()
        )
        if instance and instance.short_name:
            return instance.short_name.content
        return None

    def _append_children(self, elem, obj) -> None:
        if not hasattr(obj, "ELEMENTS"):
            return
        for tag, child_value, elem_type in self._iter_child_mappings(obj):
            if child_value is None:
                continue
            self._append_child_value(elem, tag, child_value, elem_type)

    def _iter_child_mappings(self, obj):
        for tag, (py_attr, elem_type) in obj.ELEMENTS.items():
            if self._skip_child_tag(obj, tag):
                continue
            yield tag, self._resolve_child_value(obj, tag, py_attr), elem_type

    def _skip_child_tag(self, obj, tag: str) -> bool:
        if not isinstance(obj, SwInstance):
            return False
        if self.variant_coding:
            return tag in ("SwValueCont", "SwAxisConts")
        return tag == "SwInstancePropsVariants"

    def _resolve_child_value(self, obj, tag, py_attr):
        child_value = getattr(obj, py_attr, None)
        if child_value is not None or not isinstance(obj, Msrsw):
            return child_value
        session = inspect(obj).session
        if not session:
            return None
        target_cls = ELEMENTS.get(tag)
        if not target_cls:
            return None
        child_value = session.query(target_cls).first()
        if child_value:
            self.logger.debug(f"Found orphaned {tag} for MSRSW root")
        return child_value

    def _append_child_value(self, elem, tag: str, child_value, elem_type: str) -> None:
        child_tag = self._format_tag(tag)
        if elem_type == "A":
            for item in child_value:
                child_elem = self._to_xml(item, child_tag)
                if child_elem is not None:
                    elem.append(child_elem)
            return
        child_elem = self._to_xml(child_value, child_tag)
        if child_elem is not None:
            elem.append(child_elem)

    @staticmethod
    def _append_scalar_value(elem, value, tag: str) -> None:
        child = etree.SubElement(elem, tag)
        child.text = str(value)

    def _append_array_values(self, elem, data, category: str) -> None:
        if (
            category in ("CURVE", "MAP", "VAL_BLK", "CUBOID", "CUBE4", "CUBE5")
            and len(data.dims) > 0
        ):
            self._append_grouped_values(elem, data.values)
            return
        self._append_flat_values(
            elem, data.values.flatten(), "VT" if category == "ASCII" else "V"
        )

    def _append_grouped_values(self, elem, values) -> None:
        if len(values.shape) == 1:
            group = etree.SubElement(elem, "VG")
            self._append_flat_values(group, values, "V")
            return
        for sub_values in values:
            self._append_grouped_values(elem, sub_values)

    @staticmethod
    def _append_flat_values(elem, values, tag: str) -> None:
        for value in values:
            child = etree.SubElement(elem, tag)
            child.text = str(value)


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
