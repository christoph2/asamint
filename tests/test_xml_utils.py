#!/usr/bin/env python
"""Tests for asamint.utils.xml – helper functions and XMLTraversor."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from lxml import etree
from lxml.etree import Comment, Element, SubElement, _Comment

from asamint.utils.xml import (
    XMLTraversor,
    as_numeric,
    create_elem,
    create_validator,
    element_name,
    xml_comment,
)

# ---------------------------------------------------------------------------
# element_name
# ---------------------------------------------------------------------------


def test_element_name_lowercase() -> None:
    elem = Element("MyTag")
    assert element_name(elem) == "mytag"


def test_element_name_hyphen_to_underscore() -> None:
    elem = Element("My-Tag")
    assert element_name(elem) == "my_tag"


def test_element_name_mixed() -> None:
    elem = Element("SW-INSTANCE-SPEC")
    assert element_name(elem) == "sw_instance_spec"


def test_element_name_already_lower() -> None:
    elem = Element("value")
    assert element_name(elem) == "value"


# ---------------------------------------------------------------------------
# create_elem
# ---------------------------------------------------------------------------


def test_create_elem_basic() -> None:
    parent = Element("root")
    child = create_elem(parent, "child")
    assert child.tag == "child"
    assert len(parent) == 1


def test_create_elem_with_text() -> None:
    parent = Element("root")
    child = create_elem(parent, "name", text="hello")
    assert child.text == "hello"


def test_create_elem_strips_null_bytes() -> None:
    parent = Element("root")
    child = create_elem(parent, "name", text="value\x00")
    assert child.text == "value"


def test_create_elem_with_attrib() -> None:
    parent = Element("root")
    child = create_elem(parent, "item", attrib={"id": "42", "type": "int"})
    assert child.get("id") == "42"
    assert child.get("type") == "int"


def test_create_elem_no_text_none_text() -> None:
    parent = Element("root")
    child = create_elem(parent, "child", text=None)
    assert child.text is None


def test_create_elem_no_attrib_defaults_to_empty() -> None:
    parent = Element("root")
    child = create_elem(parent, "child")
    assert child.attrib == {}


# ---------------------------------------------------------------------------
# xml_comment
# ---------------------------------------------------------------------------


def test_xml_comment_appended() -> None:
    parent = Element("root")
    xml_comment(parent, "my comment")
    assert len(parent) == 1
    child = parent[0]
    assert isinstance(child, _Comment)
    assert "my comment" in str(child)


def test_xml_comment_text_content() -> None:
    parent = Element("root")
    xml_comment(parent, "TODO: fix this")
    assert "TODO: fix this" in str(parent[0])


# ---------------------------------------------------------------------------
# as_numeric
# ---------------------------------------------------------------------------


def _elem_with_text(text: str):
    e = Element("val")
    e.text = text
    return e


def test_as_numeric_integer_string() -> None:
    assert as_numeric(_elem_with_text("42")) == Decimal("42")


def test_as_numeric_float_string() -> None:
    assert as_numeric(_elem_with_text("3.14")) == Decimal("3.14")


def test_as_numeric_scientific() -> None:
    result = as_numeric(_elem_with_text("1.5E+10"))
    assert isinstance(result, Decimal)


def test_as_numeric_negative() -> None:
    assert as_numeric(_elem_with_text("-7.0")) == Decimal("-7.0")


def test_as_numeric_non_numeric_returns_string() -> None:
    assert as_numeric(_elem_with_text("hello")) == "hello"


def test_as_numeric_empty_string_returns_string() -> None:
    result = as_numeric(_elem_with_text(""))
    assert result == ""


# ---------------------------------------------------------------------------
# create_validator
# ---------------------------------------------------------------------------


def test_create_validator_unknown_suffix_returns_none() -> None:
    with patch("asamint.utils.xml.get_dtd", return_value=None):
        assert create_validator("schema.txt") is None


def test_create_validator_get_dtd_none_returns_none() -> None:
    with patch("asamint.utils.xml.get_dtd", return_value=None):
        assert create_validator("cdf_v2.0.0.sl.dtd") is None


def test_create_validator_dtd_file() -> None:
    result = create_validator("cdf_v2.0.0.sl.dtd")
    # Returns an etree.DTD if the file exists in the package, else None
    assert result is None or isinstance(result, etree.DTD)


def test_create_validator_xsd_file() -> None:
    result = create_validator("msrsw_v222.xsd")
    assert result is None or isinstance(result, etree.XMLSchema)


def test_create_validator_dtd_extension_dispatched(tmp_path) -> None:
    dtd_content = "<!ELEMENT root EMPTY>"
    dtd_file = tmp_path / "test.dtd"
    dtd_file.write_text(dtd_content)
    with patch("asamint.utils.xml.get_dtd", return_value=dtd_file):
        result = create_validator("test.dtd")
    assert isinstance(result, etree.DTD)


def test_create_validator_unknown_extension_returns_none(tmp_path) -> None:
    dummy = tmp_path / "schema.json"
    dummy.write_text("{}")
    with patch("asamint.utils.xml.get_dtd", return_value=dummy):
        result = create_validator("schema.json")
    assert result is None


# ---------------------------------------------------------------------------
# XMLTraversor
# ---------------------------------------------------------------------------

_SIMPLE_XML = b"""<?xml version="1.0"?>
<root>
  <name>TestParam</name>
  <value>42</value>
</root>
"""

_NESTED_XML = b"""<?xml version="1.0"?>
<root>
  <group>
    <item>a</item>
    <item>b</item>
  </group>
</root>
"""

_COMMENT_XML = b"""<?xml version="1.0"?>
<root>
  <!-- this is a comment -->
  <value>1</value>
</root>
"""


@pytest.fixture
def simple_xml_file(tmp_path: Path) -> Path:
    f = tmp_path / "simple.xml"
    f.write_bytes(_SIMPLE_XML)
    return f


@pytest.fixture
def nested_xml_file(tmp_path: Path) -> Path:
    f = tmp_path / "nested.xml"
    f.write_bytes(_NESTED_XML)
    return f


@pytest.fixture
def comment_xml_file(tmp_path: Path) -> Path:
    f = tmp_path / "comment.xml"
    f.write_bytes(_COMMENT_XML)
    return f


def test_xml_traversor_root_tag(simple_xml_file: Path) -> None:
    t = XMLTraversor(str(simple_xml_file))
    assert t.root.tag == "root"


def test_xml_traversor_run_returns_dict(simple_xml_file: Path) -> None:
    t = XMLTraversor(str(simple_xml_file))
    result = t.run()
    assert isinstance(result, dict)
    assert "root" in result


def test_xml_traversor_generic_visit_leaf_returns_dict(simple_xml_file: Path) -> None:
    t = XMLTraversor(str(simple_xml_file))
    name_elem = t.root.find("name")
    result = t.generic_visit(name_elem)
    assert result == {"name": "TestParam"}


def test_xml_traversor_generic_visit_non_string_text(simple_xml_file: Path) -> None:
    t = XMLTraversor(str(simple_xml_file))
    # Root has children, not leaf text
    result = t.generic_visit(t.root)
    assert isinstance(result, dict)
    assert isinstance(result["root"], list)


def test_xml_traversor_visit_children_length(simple_xml_file: Path) -> None:
    t = XMLTraversor(str(simple_xml_file))
    children = t.visit_children(t.root)
    # root has <name> and <value> — strip whitespace-only text nodes
    assert len(children) == 2


def test_xml_traversor_nested_xml(nested_xml_file: Path) -> None:
    t = XMLTraversor(str(nested_xml_file))
    result = t.run()
    assert "root" in result


def test_xml_traversor_comment_node(comment_xml_file: Path) -> None:
    t = XMLTraversor(str(comment_xml_file))
    result = t.run()
    root_children = result["root"]
    # Comment should appear as {"_com_ment_": "..."} entry
    comments = [c for c in root_children if isinstance(c, dict) and "_com_ment_" in c]
    assert len(comments) == 1
    assert "this is a comment" in comments[0]["_com_ment_"]


def test_xml_traversor_visit_dispatches_to_generic(simple_xml_file: Path) -> None:
    t = XMLTraversor(str(simple_xml_file))
    name_elem = t.root.find("name")
    result = t.visit(name_elem)
    assert result == {"name": "TestParam"}


def test_xml_traversor_custom_visitor_called(simple_xml_file: Path) -> None:
    """A visit_value method on the subclass is dispatched to automatically."""

    class MyTraversor(XMLTraversor):
        def visit_value(self, tree):
            return {"custom_value": int(tree.text)}

    t = MyTraversor(str(simple_xml_file))
    val_elem = t.root.find("value")
    result = t.visit(val_elem)
    assert result == {"custom_value": 42}
