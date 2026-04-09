#!/usr/bin/env python
# -*- coding: utf-8 -*-

from collections import defaultdict
from dataclasses import dataclass, field
import functools
import json
import logging
from pathlib import Path
from pprint import pformat
import re
import typing

logger = logging.getLogger(__name__)

BASE = Path(r"C:\Users\Chris\PycharmProjects\asamint\asamint\data\dtds")

MSRSW = BASE / "msrsw.json"
CDF = BASE / "cdf.json"

data = open(CDF, encoding="utf-8-sig").read()

keywords = set()

@dataclass
class Reference:
    name: str
    description: str
    ref: str

@dataclass
class Integer:
    name: str
    description: str
    minimum: int
    maximum: int
    exclusive_minimum: int
    exclusive_maximum: int

@dataclass
class Number:
    name: str
    description: str
    minimum: float
    maximum: float
    exclusive_minimum: float
    exclusive_maximum: float

@dataclass
class String:
    name: str
    description: str
    min_length: int
    max_length: int
    pattern: str
    enum: str

@dataclass
class Array:
    name: str
    description: str
    items: typing.List[typing.Any]
    min_items: int
    max_items: int
    unique_items: bool

@dataclass
class Element:
    name: str
    description: str
    required: typing.List[str]
    attrs: typing.List[typing.Any]
    terminal: typing.Optional[bool] = None
    enums: typing.Dict[str, typing.List[str]] = field(default_factory=dict)
    attributes: typing.Dict[str, str] = field(default_factory=dict)
    elements: typing.Dict[str, str] = field(default_factory=dict)


cdf = json.loads(data)

SAMPLE = """
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.com/product.schema.json",
  "title": "Product",
  "description": "A product from Acme's catalog",
  "type": "object",
  "properties": {
    "productId": {
      "description": "The unique identifier for a product",
      "type": "integer"
    },
    "productName": {
      "description": "Name of the product",
      "type": "string"
    },
    "price": {
      "description": "The price of the product",
      "type": "number",
      "exclusiveMinimum": 0
    },
    "tags": {
      "description": "Tags for the product",
      "type": "array",
      "items": {
        "type": "string"
      },
      "minItems": 1,
      "uniqueItems": true
    },
    "dimensions": {
      "type": "object",
      "properties": {
        "length": {
          "type": "number"
        },
        "width": {
          "type": "number"
        },
        "height": {
          "type": "number"
        }
      },
      "required": [ "length", "width", "height" ]
    }
  },
  "required": [ "productId", "productName", "price" ]
}
"""

# Schema Keywords
SCHEMA = '$schema'
ID = "$id"

# Schema Annotations
TITLE = "title"
DESCRIPTION = "description"

# Validation
TYPE = 'type'       # object, array, string, number, boolean, null
ENUM = "enum"
CONST = "const"
EXCLUSIVE_MINIMUM = "exclusiveMinimum" # numeric
EXCLUSIVE_MAXIMUM = "exclusiveMaximum" # numeric
MINIMUM = "minimum"
MAXIMUM = "maximum"

MIN_LENGTH = "minLength"
MAX_LENGTH = "maxLength"
PATTERN = "pattern"

PROPERTIES = 'properties'
ADDITIONAL_PROPERTIES = 'additionalProperties'
REQUIRED = 'required'
DEFINITIONS = 'definitions'

REF = "$ref"
ALL_OF = "allOf"

ITEMS = "items"
MIN_ITEMS = "minItems"
MAX_ITEMS = "maxItems"
UNIQUE_ITEMS = "uniqueItems"    # boolean

DEF_PATH = "#/definitions/"

@functools.cache
def xml_name_converter(name: str) -> str:
    if not name:
        return
    res = "".join([x.title() for x in name.split("-")])
    return res

@functools.cache
def klass_name(name: str) -> str:
    return re.sub("[Tt]ype$", "", xml_name_converter(name))

@functools.cache
def real_name(name: str) -> str:
    return klass_name(re.sub(DEF_PATH, "", name))

@functools.cache
def table_name(name: str) -> str:
    return re.sub("[tT]ype$", "", name.replace('-', '_').lower())


@functools.cache
def map_internals(name: str) -> str:
    import builtins
    import keyword

    names = set([x for x in dir(builtins) if x[0].islower()] + keyword.kwlist + ["view", "desc", "row"])

    if name in names:
        return f"_{name}"
    else:
        return name

class Schema:

    def __init__(self, data):
        self.data = data
        self.definitions = {}
        self.properties = {}
        self.references = defaultdict(set)
        self.current_obj = None

        references = defaultdict(set)

        for k, v in data["definitions"].items():
            k = re.sub("Type$", "", k)
            if "properties" in v:
                for n, t in v["properties"].items():
                    if "type" in t and t["type"] == "array":
                        references[n].add(k)
        self.simple_assocs = {}
        self.complex_assocs = {}
        self.klass_assocs = defaultdict(list)
        self.children = defaultdict(list)
        self.parent = {}
        self.self_ref = set()
        for key, values in references.items():
            # pth = f"#/definitions/{key}Type"
            if len(values) > 1:
                self.complex_assocs[klass_name(key)] = [klass_name(v) for v in values]
            else:
                tn = map_internals(table_name(tuple(values)[0]))
                self.simple_assocs[klass_name(key)] = klass_name(tuple(values)[0])
                self.children[klass_name(tuple(values)[0])].append(klass_name(key))
                self.parent[klass_name(key)] = klass_name(tuple(values)[0]), tn,
        logger.debug("%s", pformat(self.complex_assocs))
        logger.debug(" " * 80)
        logger.debug("%s", pformat(self.simple_assocs))
        for k, values in self.complex_assocs.items():
            for v in values:
                if v == k:
                    self.self_ref.add(k)
                    logger.debug("Self-referential: %s", k)
                self.klass_assocs[v].append(k)

    @functools.cache  # noqa: B019
    def get_klasses(self, name: str) -> typing.List[str]:
        values = self.klass_assocs.get(name, [])
        has = [f"Has{v}s" for v in values if v != name]
        return has

    @functools.cache
    @staticmethod
    def fullname(name: str) -> str:
        return f"#/definitions/{name}Type"

    def run(self):
        #print(self.data.keys())
        schema = self.data.get(SCHEMA)
        if not schema:
            raise TypeError("Not a JSON schema")
        self.toplevel(data)

    def toplevel(self, data):
        props = self.data.get(PROPERTIES)
        title = self.data.get(TITLE)
        description = self.data.get(DESCRIPTION)
        logger.debug("%s %s", title, description)
        definitions = self.data.get(DEFINITIONS)
        #self.current_obj = name
        if definitions:
            logger.debug("DEFINITIONS")
            logger.debug("==============")
            self.do_properties(definitions, self.definitions, DEF_PATH)
        if props:
            logger.debug("PROPERTIES")
            logger.debug("==============")
            self.do_properties(props, self.properties)
        self.obj_dict = {}
        for k, v in self.definitions.items():
            self.obj_dict[real_name(k)] = v

    def do_properties(self, data, destination, prefix = ""):
        result = []
        for name, v in data.items():
            #print(name)
            tp = v.get(TYPE)
            description = v.get(DESCRIPTION)
            enum = v.get(ENUM)
            ref = v.get(REF)
            if enum and tp != "string":
                logger.debug("\t\tenum %s %s", name, enum)
            if tp == "object": # or tp is None:
                self.current_obj = name
                required = v.get(REQUIRED)
                props = v.get(PROPERTIES)
                if props:
                    ppp = self.do_properties(props, destination)
                element = Element(name, description, required, [])
                if props:
                    element.attrs = ppp
                result.append(element)
                destination[f"{prefix}{name}"] = element
            elif tp == "array":
                items = v.get(ITEMS)
                min_items = v.get(MIN_ITEMS)
                max_items = v.get(MAX_ITEMS)
                unique_items = v.get(UNIQUE_ITEMS)
                arr = Array(name, description, items, min_items, max_items, unique_items)
                result.append(arr)
            elif tp == "string":
                min_length = v.get(MIN_LENGTH)
                max_length = v.get(MAX_LENGTH)
                pattern = v.get(PATTERN)
                string = String(name, description, min_length, max_length, pattern, enum)
                result.append(string)
            elif tp in ("integer", "number"):
                minimum = v.get(MINIMUM)
                maximum = v.get(MAXIMUM)
                exclusive_minimum = v.get(EXCLUSIVE_MINIMUM)
                exclusive_maximum = v.get(EXCLUSIVE_MAXIMUM)
                if tp == "integer":
                    num = Integer(name, description, minimum, maximum, exclusive_minimum, exclusive_maximum)
                else:
                    num = Number(name, description, minimum, maximum, exclusive_minimum, exclusive_maximum)
                result.append(num)
            elif tp == "boolean":
                pass
            elif tp == "null":
                pass
            if tp is None and ref:
                required = v.get(REQUIRED)
                element = Element(name, description, required, [])
                self.current_obj = name
            if ref:
                #print("\tREF:", ref)
                xyz = Reference(name, description, ref)
                self.references[ref].add(self.current_obj)
                result.append(xyz)
                if (tp == "object" or tp is None) and element:
                    element.attrs.append(xyz)
        return result

