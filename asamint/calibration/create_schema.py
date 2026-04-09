#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging

from asamint.utils.templates import do_template_from_text
from asamint.calibration.model_from_json import Schema, Number, Integer, String, Array, Reference, Element

import io
import json
from pathlib import Path
import re
import typing

logger = logging.getLogger(__name__)


BASE = Path(r"C:\Users\Chris\PycharmProjects\asamint\asamint\data\dtds")

MSRSW = BASE / "msrsw.json"
CDF = BASE / "cdf.json"

HEADER = '''
import binascii
from collections import defaultdict
import datetime
import mmap
from pathlib import Path
import re
import sqlite3
import typing
from dataclasses import dataclass, field
from decimal import Decimal

from lxml import etree  # nosec
import sqlalchemy as sqa
from sqlalchemy import Column, ForeignKey, create_engine, event, orm, types
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Mapped, as_declarative, relationship, backref, mapped_column
from sqlalchemy.ext.associationproxy import association_proxy

from asamint.utils.xml import create_validator

DB_EXTENSION    = ".msrswdb"

CURRENT_SCHEMA_VERSION = 10

CACHE_SIZE      = 4 # MB
PAGE_SIZE       = mmap.PAGESIZE


def calculateCacheSize(value):
    return -(value // PAGE_SIZE)


REGEXER_CACHE = {}


def regexer(value, expr):
    if not REGEXER_CACHE.get(expr):
        REGEXER_CACHE[expr] = re.compile(expr, re.UNICODE)
    re_expr = REGEXER_CACHE[expr]
    return re_expr.match(value) is not None


@event.listens_for(Engine, "connect")
def set_sqlite3_pragmas(dbapi_connection, connection_record):
    dbapi_connection.create_function("REGEXP", 2, regexer)
    cursor = dbapi_connection.cursor()
    #cursor.execute("PRAGMA jornal_mode=WAL")
    cursor.execute("PRAGMA FOREIGN_KEYS=ON")
    cursor.execute("PRAGMA PAGE_SIZE={}".format(PAGE_SIZE))
    cursor.execute(
        "PRAGMA CACHE_SIZE={}".format(calculateCacheSize(CACHE_SIZE * 1024 * 1024))
    )
    cursor.execute("PRAGMA SYNCHRONOUS=OFF") # FULL
    cursor.execute("PRAGMA LOCKING_MODE=EXCLUSIVE") # NORMAL
    cursor.execute("PRAGMA TEMP_STORE=MEMORY")  # FILE
    cursor.close()


@as_declarative()
class Base:

    rid = Column("rid", types.Integer, primary_key = True)
    content = Column("content", types.Text, nullable = True, unique = False)

    TERMINAL = False
    SELF_REF = False

    ## @declared_attr
    ## def __tablename__(cls):
    ##     return cls.__name__.lower()

    def __repr__(self):
        columns = [c.name for c in self.__class__.__table__.c]
        result = []
        for name, value in [
            (n, getattr(self, n)) for n in columns if not n.startswith("_")
        ]:
            if isinstance(value, str):
                result.append("{} = '{}'".format(name, value))
            else:
                result.append("{} = {}".format(name, value))
        return "{}({})".format(self.__class__.__name__, ", ".join(result))

class DatetimeType(types.TypeDecorator):

    FMT = '%Y-%m-%dT%H:%M:%S'
    impl = types.Float
    cache_ok = True

    def process_bind_param(self, value, dialect):   # IN
        return str(Decimal(datetime.datetime.strptime(value, DatetimeType.FMT).timestamp()))

    def process_result_value(self, value, dialect): # OUT
        return datetime.datetime.fromtimestamp(value).strftime(DatetimeType.FMT)

class DecimalType(types.TypeDecorator):

    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):   # IN
        return str(value)

    def process_result_value(self, value, dialect): # OUT
        return Decimal(value)

class BlobType(types.TypeDecorator):

    impl = types.BLOB
    cache_ok = True

    def process_bind_param(self, value, dialect):   # IN
        return binascii.a2b_hex(value)

    def process_result_value(self, value, dialect): # OUT
        return binascii.b2a_hex(value)

def StdFloat(default = 0.0):
    return Column(types.Float, default = default, nullable = True)

def StdDecimal(default = 0.0):
    return Column(DecimalType, default = default, nullable = True)

def StdDate(default=None):
    # if not default:
    #     default = datetime.datetime.now().strftime(DatetimeType.FMT)
    # return Column(DatetimeType, nullable=True, default=default)
    return Column(types.Text)

def StdBlob():
    return Column(BlobType,  nullable = True)

def StdShort(default = 0, primary_key = False, unique = False):
    return Column(
        types.Integer,
        default = default,
        nullable = True,
        primary_key = primary_key,
        unique = unique,
        #CheckClause('BETWEEN (-32768, 32767)')
    )

def StdUShort(default = 0, primary_key = False, unique = False):
    return Column(
        types.Integer,
        default = default,
        nullable = False,
        primary_key = primary_key,
        unique = unique,
        #CheckClause('BETWEEN (0, 65535)')
    )

def StdLong(default = 0, primary_key = False, unique = False):
    return Column(
        types.Integer,
        default = default,
        nullable = False,
        primary_key = primary_key,
        unique = unique,
        #CheckClause('BETWEEN (-2147483648, 2147483647)')
    )

def StdULong(default = 0, primary_key = False, unique = False):
    return Column(
        types.Integer,
        default = default,
        nullable = False,
        primary_key = primary_key,
        unique = unique,
        #CheckClause('BETWEEN (0, 4294967295)')
    )

def StdString(default = None, primary_key = False, unique = False, index = False):
    return Column(
        types.Text,
        default = default,
        nullable = True,
        primary_key = primary_key,
        unique = unique,
        index = index,
    )

class MetaData(Base):

    __tablename__ = "metadata"

    """
    """
    schema_version = StdShort()
    variant = StdString()
    xml_schema = StdString()
    created = StdDate()
'''

FOOTER = '''
class MSRSWDatabase:

    def __init__(self, filename: Path | str, debug: bool = False, logLevel: str = "INFO") -> None:
        if filename == ":memory:":
            self.dbname = ""
        else:
            if isinstance(filename, str):
                filename = Path(filename)
            self.dbname = filename.with_suffix(DB_EXTENSION)
        self._engine = create_engine(
            f"sqlite:///{self.dbname}",
            echo=debug,
            connect_args={"detect_types": sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES},
            native_datetime=True,
        )

        self._session = orm.Session(self._engine, autoflush = False, autocommit = False)
        self._metadata = Base.metadata
        #loadInitialData(Node)
        Base.metadata.create_all(self.engine)
        meta = MetaData(schema_version = CURRENT_SCHEMA_VERSION)
        self.session.add(meta)
        self.session.flush()
        self.session.commit()
        self._closed = False

    def __del__(self):
        pass
        #if not self._closed:
        #    self.close()

    def close(self):
        """"""
        self.session.close()
        self.engine.dispose()
        self._closed = True

    def create_indices(self):
        index_name = sqa.Index("shortname_content_idx", ShortName.content)
        index_name.create(bind=self.engine)

    @property
    def engine(self):
        return self._engine

    @property
    def metadata(self):
        return self._metadata

    @property
    def session(self):
        return self._session

    def begin_transaction(self):
        self.session.begin()

    def commit_transaction(self):
        self.session.commit()

    def rollback_transaction(self):
        self.session.rollback()


class Parser:

    ATTR = re.compile(r'(\\\\{.*?\\\\})?(.*)', re.DOTALL)

    def __init__(self, file_name: str, db: MSRSWDatabase, root_elem: str = ROOT_ELEMENT):
        self.validator = create_validator("cdf_v2.0.0.sl.dtd")
        self.schema_version = 0
        self.variant = "MSRSW"
        self.file_name = file_name
        self.db = db
        self.msrsw = etree.parse(file_name)  # nosec

        validate_result = self.validator.validate(self.msrsw)
        if not validate_result:
            logger.warning("Validation failed: %s", validate_result)
            logger.warning("%s", self.validator.error_log)
        else:
            logger.info("Validation passed")

        self.root = self.msrsw.getroot()
        self.parse(self.root)
        self.db.commit_transaction()
        self.update_metadata()
        self.db.commit_transaction()
        self.db.close()

    def parse(self, tree):
        res = defaultdict(list)
        if issubclass(type(tree), etree._Comment):
            return tree
        element = ELEMENTS.get(tree.tag)
        if not element:
            logger.warning("invalid tag: %s", tree.tag)
            return []
        obj = element()
        for name, value in tree.attrib.items():
            name = self.get_attr(name)
            if name in obj.ATTRIBUTES:
                name = obj.ATTRIBUTES[name]
                setattr(obj, name, value)
        if element.TERMINAL:
            obj.content = tree.text
        self_ref = element.SELF_REF
        for child in tree.getchildren():
            parsed = self.parse(child)
            res[parsed.__class__.__name__].append(parsed)
        if res:
            for key, items in res.items():
                if key == "_Comment":
                    continue
                if key not in obj.ELEMENTS:
                    logger.warning("unknown key: %s", key)
                    continue
                attrib, elem_tp = obj.ELEMENTS[key]
                if self_ref and (attrib[:-1] ==  obj.__tablename__):
                        attrib = "children"
                if not hasattr(obj, attrib):
                    logger.warning("unknown attribute: %s", attrib)
                    continue
                try:
                    if elem_tp == "A":
                        setattr(obj, attrib, items)
                    else:
                        setattr(obj, attrib, items[0])
                except Exception as e:
                    logger.error("%s %s", e, obj)
                    logger.error("\tSELF-REF: %s", self_ref)
        self.db.session.add(obj)
        return obj

    def get_attr(self, name: str) -> str:
        match = self.ATTR.match(name)
        if match:
            return match.group(2)
        return ""

    def update_metadata(self):
        msrsw = self.db.session.query(Msrsw).first()
        meta = self.db.session.query(MetaData).first()
        if msrsw:
            category = msrsw.category.content if  msrsw.category else ""
            meta.variant = category
        for attr, value in self.root.attrib.items():
            attr = self.get_attr(attr)
            if attr == "noNamespaceSchemaLocation":
                meta.xml_schema = value
'''


DEFI = """
#
#   Definitions
#
%for name, item in schema.definitions.items():
<% klasses = schema.get_klasses(klass_name(item.name)) %>
<% assocs = schema.klass_assocs.get(klass_name(item.name), []) %>
<% simple = schema.simple_assocs.get(klass_name(item.name), []) %>
<% parent = schema.parent.get(klass_name(item.name), []) %>
<% children= schema.children.get(klass_name(item.name), []) %>
%if not klass_name(item.name) in schema.complex_assocs:
## class ${klass_name(item.name)}(Base):   # ${klass_name(item.name)}
%if klasses:
class ${klass_name(item.name)}(Base, ${', '.join(klasses)}):
%else:
class ${klass_name(item.name)}(Base):
%endif
    # SIMPLE: ${simple} == SR: ${name in schema.self_ref}
    # P: ${parent}  --  C: ${children}
    __tablename__ = "${map_name(item.name)}"

    ATTRIBUTES = {
%for key, value in item.attributes.items():
        "${key}": "${value}",
%endfor
    }
    ELEMENTS = {
%for key, (el, tp) in item.elements.items():
        "${key}": ("${el}", "${tp}"),
%endfor
    }
%if item.enums:
    ENUMS = {
%for key, value in item.enums.items():
        "${key}": ${value},
%endfor
    }
%endif
%if item.terminal:
    TERMINAL = True
%endif
%if name in schema.self_ref:
    SELF_REF = True
%endif
%if klass_name(item.name) in TYPE_MAP:
    content = ${TYPE_MAP[klass_name(item.name)]}
%endif
%for attr in item.attrs:
%if isinstance(attr, String):
    ${map_name(attr.name)} = StdString()
%elif isinstance(attr, Integer):
    ${map_name(attr.name)} = StdLong()
%elif isinstance(attr, Number):
    ${map_name(attr.name)} = StdFloat()
%elif isinstance(attr, Reference):
    # REF
    ${map_name(attr.name, "id")}: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${map_name(attr.name)}.rid"))
    ${map_name(attr.name)}: Mapped["${rel_name(attr.name)}"] = relationship(single_parent=True)
%elif isinstance(attr, Array):
    # ARR
    %if rel_name(attr.name) in children:
        # PARENT-OBJ
    ${map_name(attr.name)}: Mapped[typing.List["${rel_name(attr.name)}"]] = relationship(back_populates="${map_name(item.name)}")
    %else:
        # NO_PA         ${map_name(attr.name)}
    ## ${map_name(attr.name, "id")}: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${map_name(attr.name)}.rid"))
    ## ${map_name(attr.name)}: Mapped[typing.List["${rel_name(attr.name)}"]] = relationship(backref="${map_name(item.name)}")
    %endif
    %if rel_name(attr.name) not in assocs and rel_name(attr.name) not in children:
    ${map_name(attr.name, "id")}: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${map_name(attr.name)}.rid"))
    ${map_name(attr.name)}: Mapped[typing.List["${rel_name(attr.name)}"]] = relationship()
    %endif
%else:
            # ${attr}   ${type(attr)}
%endif
%endfor
%if parent:
    # PARENT
    ${parent[1]}_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${parent[1]}.rid"))
    ${parent[1]}: Mapped["${parent[0]}"] = relationship(back_populates="${map_name(item.name)}")
%endif
%else:
    # N-I: ${klass_name(item.name)}
%endif
%endfor
"""

ASSOCS = """
#
# Assocs.
#
%for name, item in schema.complex_assocs.items():
<% obj = schema.obj_dict[name] %>
<% klasses = schema.get_klasses(name) %>
<% assocs = schema.klass_assocs.get(name, []) %>
<% parent = schema.parent.get(name, []) %>
<% children = schema.children.get(name, []) %>
<% simple = schema.simple_assocs.get(klass_name(name), []) %>
class ${name}Association(Base):

    __tablename__ = "${map_name(obj.name)}_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    ${map_name(obj.name)}s: Mapped[typing.List["${name}"]] = relationship(back_populates="association")

class Has${name}s:

    @declared_attr
    def ${table_name(obj.name)}_association_id(self):
        return Column(types.Integer, ForeignKey("${map_name(obj.name)}_association.rid"))

    @declared_attr
    def ${map_name(obj.name)}_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%s${name}Association" % name,
            (${name}Association, ),
            dict(
                __tablename__ = None,
                __mapper_args__ = {"polymorphic_identity": discriminator},
            ),
        )

        cls.${map_name(obj.name)}s = association_proxy(
            "${map_name(obj.name)}_association",
            "${map_name(obj.name)}s",
            creator = lambda ${map_name(obj.name)}s: assoc_cls(${map_name(obj.name)}s=${map_name(obj.name)}s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))

%if klasses:
class ${name}(Base, ${', '.join(klasses)}):
%else:
class ${name}(Base):
%endif
    # SIMPLE: ${simple} -- SR: ${name in schema.self_ref}
    # P: ${parent}  --  C: ${children}
    __tablename__ = "${map_name(obj.name)}" # ${obj.name}   --  ${map_name(obj.name)}

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${map_name(obj.name)}_association.rid"))
    association = relationship("${name}Association", back_populates="${map_name(obj.name)}s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("${map_name(obj.name)}.rid"))
    children = relationship("${name}")

    ATTRIBUTES = {
%for key, value in obj.attributes.items():
        "${key}": "${value}",
%endfor
    }
    ELEMENTS = {
%for key, (el, tp) in obj.elements.items():
        "${key}": ("${el}", "${tp}"),
%endfor
    }
%if obj.enums:
    ENUMS = {
%for key, value in obj.enums.items():
        "${key}": ${value},
%endfor
    }
%endif
%if obj.terminal:
    TERMINAL = True
%endif
%if name in schema.self_ref:
    SELF_REF = True
%endif

%if klass_name(obj.name) in TYPE_MAP:
    content = ${TYPE_MAP[klass_name(obj.name)]}
%endif
%for attr in obj.attrs:
%if isinstance(attr, String):
    ${map_name(attr.name)} = StdString()
%elif isinstance(attr, Integer):
    ${map_name(attr.name)} = StdLong()
%elif isinstance(attr, Number):
    ${map_name(attr.name)} = StdFloat()
%elif isinstance(attr, Reference):
    # SHIT-R
    ${map_name(attr.name, "id")}: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${map_name(attr.name)}.rid"))
    ${map_name(attr.name)}: Mapped["${rel_name(attr.name)}"] = relationship(single_parent=True)
%elif isinstance(attr, Array):
    # SHIT-A
    %if rel_name(attr.name) in children:
        # PARENT-OBJ
    ${map_name(attr.name)}: Mapped[typing.List["${rel_name(attr.name)}"]] = relationship(back_populates="${map_name(obj.name)}")
    %else:
        # NO_PA         ${map_name(attr.name)}
    %endif
    %if rel_name(attr.name) not in assocs and rel_name(attr.name) not in children:
    ${map_name(attr.name, "id")}: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${map_name(attr.name)}.rid"))
    ${map_name(attr.name)}: Mapped[typing.List["${rel_name(attr.name)}"]] = relationship()
    %endif
%else:
            # ${attr}   ${type(attr)}
%endif
%endfor
%if parent:
    # PARENT-ASSO
    ${parent[1]}_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("${parent[1]}.rid"))
    ${parent[1]}: Mapped["${parent[0]}"] = relationship(back_populates="${map_name(obj.name)}")
%endif
%endfor
"""

PROPS = """
#
# Properties
#
%for name, item in schema.properties.items():
class ${xml_name_converter(item.name)}(Base):

    __tablename__ = "${map_name(item.name)}"

%for attr in item.attrs:
%if isinstance(attr, String):
    ${map_name(attr.name)} = StdString()
%elif isinstance(attr, Integer):
    ${map_name(attr.name)} = StdLong()
%elif isinstance(attr, Number):
    ${map_name(attr.name)} = StdFloat()
%elif isinstance(attr, Reference):
        # ${map_name(attr.name)} = ${attr.ref}
%else:
            # ${attr}   ${type(attr)}
%endif
%endfor

%endfor
"""

POST_HEADER = """
#
#   Post-Header
#
@dataclass
class ElementMap:
    klass: Base
    attributes: typing.Dict[str, str] = field(default_factory=dict)
    enums: typing.Dict[str, typing.List[str]] = field(default_factory=dict)
    elements: typing.Dict[str, str] = field(default_factory=dict)
    terminal: bool = False

ELEMENTS = {
%for k, v in names.items():
    "${v}": ${k},
%endfor
}

ROOT_ELEMENT = "MSRSW"
"""

def xml_name_converter(name: str) -> str:
    if not name:
        return
    res = "".join([x.title() for x in name.split("-")])
    return res

def map_name(name: str, suffix: str = None) -> str:
    import builtins
    import keyword

    name = re.sub("[tT]ype$", "", name)
    names = set([x for x in dir(builtins) if x[0].islower()] + keyword.kwlist + ["view", "desc", "row"])
    if suffix:
        name = f"{name}_{suffix}"
    name = name.replace('-', '_').lower()
    if name in names:
        return f"_{name}"
    else:
        return name

def table_name(name: str) -> str:
    return re.sub("[tT]ype$", "", name.replace('-', '_').lower())

def klass_name(name: str) -> str:
    return re.sub("[Tt]ype$", "", xml_name_converter(name))

def strip_type(name: str) -> str:
    return re.sub("[Tt]ype$", "", name)

def attr_name(name: str) -> str:
    return map_name(name)

def rel_name(name: str) -> str:
    xname = xml_name_converter(name)
    #flz, _ = re.subn("[Tt]ype$", "", xname, 1)
    return xname

data = open(MSRSW, encoding="utf-8-sig").read()
#data = open(CDF, encoding="utf-8-sig").read()
msrsw = json.loads(data)

schema = Schema(msrsw)
schema.run()

kkk = schema.get_klasses("Requirement")

def sorter1(schema):
    positions = {}
    items = []
    for idx, (name, item) in enumerate(schema.definitions.items()):
        positions[name] = (idx, item)
        items.append((name, item))

    while True:
        swap_counter = 0
        for (name, item) in items:
            for attr in item.attrs:
                if isinstance(attr, Reference):
                    pos, elem = positions[attr.ref]
                    pos2, _ = positions[name]
                    if pos > pos2:
                        lhs = items[pos2]
                        rhs = items[pos]
                        items[pos2] = rhs
                        items[pos] = lhs
                        positions[attr.ref] = (pos2, rhs)
                        positions[name] = (pos, lhs)
                        swap_counter += 1
        if swap_counter == 0:
            break
    schema.definitions = dict(items)


def sorter2(schema):
    positions = {}
    result = []
    for idx, (name, items) in enumerate(schema.complex_assocs.items()):
        positions[name] = (idx, items)
        result.append((name, items))
    # pprint(positions)
    iterations = 0
    while True:
        swap_counter = 0
        for _idx, (name, items) in enumerate(result):
            for attr in items:
                pos = positions.get(attr)
                if pos:
                    pos, elem = pos
                    pos2, elem2 = positions[name]
                    if pos > pos2:
                        lhs = result[pos2]
                        rhs = result[pos]
                        # print(pos, pos2, lhs, rhs)
                        result[pos2] = rhs
                        result[pos] = lhs
                        positions[attr] = (pos2, rhs[1])
                        positions[name] = (pos, lhs[1])
                        swap_counter += 1
        iterations += 1
        if swap_counter == 0 and iterations > 10:
            break
    ttt = sorted(positions.items(), key=lambda x: x[1][0])
    xyz = []
    for k, (_, v) in ttt:
        xyz.append((k, v,))
    schema.complex_assocs = dict(xyz)

TERMINAL_EXTRA = {"LONG-NAMEType", "PType", "NMLISTType", "LABELType", "VFType"}

def traverser(schema):
    short_names = []
    names = {}
    for _idx, (_name, item) in enumerate(schema.definitions.items()):
        item.terminal = True
        names[klass_name(item.name)] = strip_type(item.name)
        for attr in item.attrs:
            if attr.name == 'SHORT-NAME':
                short_names.append(klass_name(item.name))
            cpis = schema.klass_assocs.get(klass_name(item.name), [])
            cmplx = rel_name(attr.name) in cpis
            if isinstance(attr, (Reference, Array)):
                nmm = map_name(attr.name)
                if cmplx:
                    nmm += "s"
                item.elements[rel_name(attr.name)] = (nmm, "A" if isinstance(attr, Array) else "R")
            else:
                item.attributes[attr.name] = map_name(attr.name)
            if isinstance(attr, (Reference, Array)):
                item.terminal = False
            elif isinstance(attr, String):
                if attr.enum:
                    item.enums[map_name(attr.name)] = attr.enum
        if item.name in TERMINAL_EXTRA:
            item.terminal = True
    return names, sorted(short_names)

def swappy(schema, items_to_swap=()):

    def swap(array, pos1, pos2):
        lhs = array[pos1]
        rhs = array[pos2]
        array[pos1] = rhs
        array[pos2] = lhs

    positions = {}
    result = []
    for idx, (name, items) in enumerate(schema.complex_assocs.items()):
        positions[name] = (idx, items)
        result.append((name, items))
    for left, right in items_to_swap:
        swap(result, left, right)

    schema.complex_assocs = dict(result)

sorter1(schema)
swappy(schema, [(25, 32 ), (24, 33), (19, 31), (9,  31), (9, 12), (6, 31), (9, 11),
    (15, 31), (11, 15), (12, 15), (20, 31), (22, 31), (42, 43), (46, 47)]
)

names, shortnames = traverser(schema)

TYPE_MAP = {
    "Date": "StdDate()",
    "V": "StdDecimal()",
    "VH": "StdBlob()",
}

with io.open("msrsw_db.py", "w") as fout:
    fout.write(do_template_from_text(HEADER))
    fout.write("\n")

    fout.write(do_template_from_text(ASSOCS, namespace={
        "schema": schema, "xml_name_converter": xml_name_converter, "map_name": map_name,
        "Number": Number, "Integer": Integer, "String": String, "Array": Array, "Reference": Reference,
        "Element": Element, "re": re, "table_name": table_name, "klass_name": klass_name,
        "attr_name": attr_name, "rel_name": rel_name, "TYPE_MAP": TYPE_MAP,
    }, formatExceptions=False))
    fout.write("\n")

    fout.write(do_template_from_text(DEFI, namespace={
        "schema": schema, "xml_name_converter": xml_name_converter, "map_name": map_name,
        "Number": Number, "Integer": Integer, "String": String, "Array": Array, "Reference": Reference,
        "Element": Element, "re": re, "table_name": table_name, "klass_name": klass_name,
        "attr_name": attr_name, "rel_name": rel_name, "TYPE_MAP": TYPE_MAP,
    }, formatExceptions=False))
    fout.write("\n")

    fout.write(do_template_from_text(PROPS, namespace={
        "schema": schema, "xml_name_converter": xml_name_converter, "map_name": map_name,
        "Number": Number, "Integer": Integer, "String": String, "Array": Array, "Reference": Reference,
        "Element": Element, "re": re, "table_name": table_name, "klass_name": klass_name,
        "attr_name": attr_name, "rel_name": rel_name, "TYPE_MAP": TYPE_MAP,
    }, formatExceptions=False))
    fout.write("\n")
    fout.write(do_template_from_text(POST_HEADER, namespace={"names": names}))
    fout.write("\n")
    fout.write(do_template_from_text(FOOTER, namespace={"shortnames": shortnames}))   #
    fout.write("\n")
