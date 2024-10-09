import binascii
import datetime
import itertools
import mmap
import re
import sqlite3
import typing
from dataclasses import dataclass, field
from decimal import Decimal

from lxml import etree  # nosec
from sqlalchemy import Column, ForeignKey, create_engine, event, orm, types
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import as_declarative, relationship
from sqlalchemy.orm.collections import InstrumentedList

DB_EXTENSION    = "msrswdb"

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
    cursor.execute(f"PRAGMA PAGE_SIZE={PAGE_SIZE}")
    cursor.execute(
        f"PRAGMA CACHE_SIZE={calculateCacheSize(CACHE_SIZE * 1024 * 1024)}"
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

    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    def __repr__(self):
        columns = [c.name for c in self.__class__.__table__.c]
        result = []
        for name, value in [
            (n, getattr(self, n)) for n in columns if not n.startswith("_")
        ]:
            if isinstance(value, str):
                result.append(f"{name} = '{value}'")
            else:
                result.append(f"{name} = {value}")
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

def StdDate():
    return Column(DatetimeType,  nullable = True)

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
    """
    """
    schema_version = StdShort()
    variant = StdString()
    xml_schema = StdString()
    created = Column(types.DateTime, default = datetime.datetime.now)

#
#   Definitions
#
class ShortName(Base):

    __tablename__ = "short_name"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Category(Base):

    __tablename__ = "category"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Label(Base):

    __tablename__ = "label"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "E": "e",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")

class Language(Base):

    __tablename__ = "language"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Desc(Base):

    __tablename__ = "desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "MsrQueryText": "msr_query_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class OverallProject(Base):

    __tablename__ = "overall_project"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "Desc": "_desc",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")

class Tt(Base):

    __tablename__ = "tt"
    ATTRIBUTES = {
        "TYPE": "_type",
        "USER-DEFINED-TYPE": "user_defined_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "_type": ['SGMLTAG', 'SGML-ATTRIBUTE', 'TOOL', 'PRODUCT', 'VARIABLE', 'STATE', 'PRM', 'MATERIAL', 'CONTROL-ELEMENT', 'CODE', 'ORGANISATION', 'OTHER'],
    }
    TERMINAL = True
    _type = StdString()
    user_defined_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class E(Base):

    __tablename__ = "e"
    ATTRIBUTES = {
        "TYPE": "_type",
        "COLOR": "color",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "_type": ['BOLD', 'ITALIC', 'BOLDITALIC', 'PLAIN'],
    }
    TERMINAL = True
    _type = StdString()
    color = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Sup(Base):

    __tablename__ = "sup"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Sub(Base):

    __tablename__ = "sub"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Ie(Base):

    __tablename__ = "ie"
    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Companies(Base):

    __tablename__ = "companies"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Company": "company",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    company_id = Column(types.Integer, ForeignKey('company.rid', use_alter=True))
    company = relationship('Company', foreign_keys=[company_id], uselist=True, cascade="all")

class Xref(Base):

    __tablename__ = "xref"
    ATTRIBUTES = {
        "ID-CLASS": "id_class",
        "EXT-ID-CLASS": "ext_id_class",
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "SHOW-SEE": "show_see",
        "SHOW-CONTENT": "show_content",
        "SHOW-RESOURCE-TYPE": "show_resource_type",
        "SHOW-RESOURCE-NUMBER": "show_resource_number",
        "SHOW-RESOURCE-LONG-NAME": "show_resource_long_name",
        "SHOW-RESOURCE-SHORT-NAME": "show_resource_short_name",
        "SHOW-RESOURCE-PAGE": "show_resource_page",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "id_class": ['CHAPTER', 'COMPANY', 'DEF-ITEM', 'EXTERNAL', 'FIGURE', 'FORMULA', 'PRM', 'REQUIREMENT', 'SAMPLE', 'SDG', 'STD', 'SW-ADDR-METHOD', 'SW-AXIS-TYPE', 'SW-BASE-TYPE', 'SW-CALPRM', 'SW-CALPRM-PROTOTYPE', 'SW-CLASS-PROTOTYPE', 'SW-CLASS-ATTR-IMPL', 'SW-CLASS-INSTANCE', 'SW-CLASS', 'SW-CODE-SYNTAX', 'SW-COLLECTION', 'SW-COMPU-METHOD', 'SW-CPU-MEM-SEG', 'SW-DATA-CONSTR', 'SW-FEATURE', 'SW-GENERIC-AXIS-PARAM-TYPE', 'SW-INSTANCE-TREE', 'SW-INSTANCE', 'SW-MC-BASE-TYPE', 'SW-MC-INTERFACE-SOURCE', 'SW-MC-INTERFACE', 'SW-RECORD-LAYOUT', 'SW-SYSTEMCONST', 'SW-SYSTEM', 'SW-TASK', 'SW-TEMPLATE', 'SW-UNIT', 'SW-USER-ACCESS-CASE', 'SW-USER-GROUP', 'SW-VARIABLE-PROTOTYPE', 'SW-VARIABLE', 'SW-VCD-CRITERION', 'TABLE', 'TEAM-MEMBER', 'TOPIC', 'VARIANT-DEF', 'VARIANT-CHAR', 'XDOC', 'XFILE', 'XREF-TARGET'],
        "show_see": ['SHOW-SEE', 'NO-SHOW-SEE'],
        "show_content": ['SHOW-CONTENT', 'NO-SHOW-CONTENT'],
        "show_resource_type": ['SHOW-TYPE', 'NO-SHOW-TYPE'],
        "show_resource_number": ['SHOW-NUMBER', 'NO-SHOW-NUMBER'],
        "show_resource_long_name": ['SHOW-LONG-NAME', 'NO-SHOW-LONG-NAME'],
        "show_resource_short_name": ['SHOW-SHORT-NAME', 'NO-SHOW-SHORT-NAME'],
        "show_resource_page": ['SHOW-PAGE', 'NO-SHOW-PAGE'],
    }
    TERMINAL = True
    id_class = StdString()
    ext_id_class = StdString()
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    show_see = StdString()
    show_content = StdString()
    show_resource_type = StdString()
    show_resource_number = StdString()
    show_resource_long_name = StdString()
    show_resource_short_name = StdString()
    show_resource_page = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class LongName1(Base):

    __tablename__ = "long_name_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "E": "e",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")

class XrefTarget(Base):

    __tablename__ = "xref_target"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": "long_name_1",
        "ShortName": "short_name",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_1_id = Column(types.Integer, ForeignKey('long_name_1.rid', use_alter=True))
    long_name_1 = relationship('LongName1', foreign_keys=[long_name_1_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")

class Ft(Base):

    __tablename__ = "ft"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class MsrQueryName(Base):

    __tablename__ = "msr_query_name"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class MsrQueryResultText(Base):

    __tablename__ = "msr_query_result_text"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "MsrQueryText": "msr_query_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class Comment(Base):

    __tablename__ = "comment"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class MsrQueryArg(Base):

    __tablename__ = "msr_query_arg"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Xref": "xref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")

class MsrQueryProps(Base):

    __tablename__ = "msr_query_props"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryName": "msr_query_name",
        "MsrQueryArg": "msr_query_arg",
        "Comment": "comment",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_name_id = Column(types.Integer, ForeignKey('msr_query_name.rid', use_alter=True))
    msr_query_name = relationship('MsrQueryName', foreign_keys=[msr_query_name_id], uselist=False, cascade="all")
    msr_query_arg_id = Column(types.Integer, ForeignKey('msr_query_arg.rid', use_alter=True))
    msr_query_arg = relationship('MsrQueryArg', foreign_keys=[msr_query_arg_id], uselist=True, cascade="all")
    comment_id = Column(types.Integer, ForeignKey('comment.rid', use_alter=True))
    comment = relationship('Comment', foreign_keys=[comment_id], uselist=False, cascade="all")

class MsrQueryText(Base):

    __tablename__ = "msr_query_text"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": "msr_query_props",
        "MsrQueryResultText": "msr_query_result_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_props_id = Column(types.Integer, ForeignKey('msr_query_props.rid', use_alter=True))
    msr_query_props = relationship('MsrQueryProps', foreign_keys=[msr_query_props_id], uselist=False, cascade="all")
    msr_query_result_text_id = Column(types.Integer, ForeignKey('msr_query_result_text.rid', use_alter=True))
    msr_query_result_text = relationship('MsrQueryResultText', foreign_keys=[msr_query_result_text_id], uselist=False, cascade="all")

class Na(Base):

    __tablename__ = "na"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class TeamMemberRefs(Base):

    __tablename__ = "team_member_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TeamMemberRef": "team_member_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    team_member_ref_id = Column(types.Integer, ForeignKey('team_member_ref.rid', use_alter=True))
    team_member_ref = relationship('TeamMemberRef', foreign_keys=[team_member_ref_id], uselist=True, cascade="all")

class LongName(Base):

    __tablename__ = "long_name"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "E": "e",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")

class Roles(Base):

    __tablename__ = "roles"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
        "F-CHILD-TYPE": "f_child_type",
    }
    ELEMENTS = {
        "Role": "role",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    f_child_type = StdString()
    role_id = Column(types.Integer, ForeignKey('role.rid', use_alter=True))
    role = relationship('Role', foreign_keys=[role_id], uselist=True, cascade="all")

class TeamMembers(Base):

    __tablename__ = "team_members"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TeamMember": "team_member",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    team_member_id = Column(types.Integer, ForeignKey('team_member.rid', use_alter=True))
    team_member = relationship('TeamMember', foreign_keys=[team_member_id], uselist=True, cascade="all")

class Role(Base):

    __tablename__ = "role"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Company(Base):

    __tablename__ = "company"
    ATTRIBUTES = {
        "ROLE": "role",
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "F-CHILD-TYPE": "f_child_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Roles": "roles",
        "TeamMembers": "team_members",
    }
    ENUMS = {
        "role": ['MANUFACTURER', 'SUPPLIER'],
    }
    role = StdString()
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    f_child_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    roles_id = Column(types.Integer, ForeignKey('roles.rid', use_alter=True))
    roles = relationship('Roles', foreign_keys=[roles_id], uselist=False, cascade="all")
    team_members_id = Column(types.Integer, ForeignKey('team_members.rid', use_alter=True))
    team_members = relationship('TeamMembers', foreign_keys=[team_members_id], uselist=False, cascade="all")

class Department(Base):

    __tablename__ = "department"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Address(Base):

    __tablename__ = "address"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Zip(Base):

    __tablename__ = "zip"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class City(Base):

    __tablename__ = "city"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Phone(Base):

    __tablename__ = "phone"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Fax(Base):

    __tablename__ = "fax"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Email(Base):

    __tablename__ = "email"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Homepage(Base):

    __tablename__ = "homepage"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class TeamMember(Base):

    __tablename__ = "team_member"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Roles": "roles",
        "Department": "department",
        "Address": "address",
        "Zip": "_zip",
        "City": "city",
        "Phone": "phone",
        "Fax": "fax",
        "Email": "email",
        "Homepage": "homepage",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    roles_id = Column(types.Integer, ForeignKey('roles.rid', use_alter=True))
    roles = relationship('Roles', foreign_keys=[roles_id], uselist=False, cascade="all")
    department_id = Column(types.Integer, ForeignKey('department.rid', use_alter=True))
    department = relationship('Department', foreign_keys=[department_id], uselist=False, cascade="all")
    address_id = Column(types.Integer, ForeignKey('address.rid', use_alter=True))
    address = relationship('Address', foreign_keys=[address_id], uselist=False, cascade="all")
    zip_id = Column(types.Integer, ForeignKey('zip.rid', use_alter=True))
    _zip = relationship('Zip', foreign_keys=[zip_id], uselist=False, cascade="all")
    city_id = Column(types.Integer, ForeignKey('city.rid', use_alter=True))
    city = relationship('City', foreign_keys=[city_id], uselist=False, cascade="all")
    phone_id = Column(types.Integer, ForeignKey('phone.rid', use_alter=True))
    phone = relationship('Phone', foreign_keys=[phone_id], uselist=False, cascade="all")
    fax_id = Column(types.Integer, ForeignKey('fax.rid', use_alter=True))
    fax = relationship('Fax', foreign_keys=[fax_id], uselist=False, cascade="all")
    email_id = Column(types.Integer, ForeignKey('email.rid', use_alter=True))
    email = relationship('Email', foreign_keys=[email_id], uselist=False, cascade="all")
    homepage_id = Column(types.Integer, ForeignKey('homepage.rid', use_alter=True))
    homepage = relationship('Homepage', foreign_keys=[homepage_id], uselist=False, cascade="all")

class SampleRef(Base):

    __tablename__ = "sample_ref"
    ATTRIBUTES = {
        "F-ID-CLASS": "f_id_class",
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    f_id_class = StdString()
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Date(Base):

    __tablename__ = "date"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    content = StdDate()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Tbr(Base):

    __tablename__ = "tbr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "Std": "std",
        "Xdoc": "xdoc",
        "Xfile": "xfile",
        "MsrQueryText": "msr_query_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    std_id = Column(types.Integer, ForeignKey('std.rid', use_alter=True))
    std = relationship('Std', foreign_keys=[std_id], uselist=True, cascade="all")
    xdoc_id = Column(types.Integer, ForeignKey('xdoc.rid', use_alter=True))
    xdoc = relationship('Xdoc', foreign_keys=[xdoc_id], uselist=True, cascade="all")
    xfile_id = Column(types.Integer, ForeignKey('xfile.rid', use_alter=True))
    xfile = relationship('Xfile', foreign_keys=[xfile_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class Schedule(Base):

    __tablename__ = "schedule"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SampleRef": "sample_ref",
        "Date": "date",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sample_ref_id = Column(types.Integer, ForeignKey('sample_ref.rid', use_alter=True))
    sample_ref = relationship('SampleRef', foreign_keys=[sample_ref_id], uselist=False, cascade="all")
    date_id = Column(types.Integer, ForeignKey('date.rid', use_alter=True))
    date = relationship('Date', foreign_keys=[date_id], uselist=False, cascade="all")

class TeamMemberRef(Base):

    __tablename__ = "team_member_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Tbd(Base):

    __tablename__ = "tbd"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TeamMemberRefs": "team_member_refs",
        "Schedule": "schedule",
        "Desc": "_desc",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    team_member_refs_id = Column(types.Integer, ForeignKey('team_member_refs.rid', use_alter=True))
    team_member_refs = relationship('TeamMemberRefs', foreign_keys=[team_member_refs_id], uselist=False, cascade="all")
    schedule_id = Column(types.Integer, ForeignKey('schedule.rid', use_alter=True))
    schedule = relationship('Schedule', foreign_keys=[schedule_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")

class UsedLanguages(Base):

    __tablename__ = "used_languages"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class CompanyDocInfos(Base):

    __tablename__ = "company_doc_infos"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyDocInfo": "company_doc_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    company_doc_info_id = Column(types.Integer, ForeignKey('company_doc_info.rid', use_alter=True))
    company_doc_info = relationship('CompanyDocInfo', foreign_keys=[company_doc_info_id], uselist=True, cascade="all")

class FormatterCtrls(Base):

    __tablename__ = "formatter_ctrls"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FormatterCtrl": "formatter_ctrl",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    formatter_ctrl_id = Column(types.Integer, ForeignKey('formatter_ctrl.rid', use_alter=True))
    formatter_ctrl = relationship('FormatterCtrl', foreign_keys=[formatter_ctrl_id], uselist=True, cascade="all")

class Subtitle(Base):

    __tablename__ = "subtitle"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class State1(Base):

    __tablename__ = "state_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Date1(Base):

    __tablename__ = "date_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Url(Base):

    __tablename__ = "url"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Position(Base):

    __tablename__ = "position"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Std(Base):

    __tablename__ = "std"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": "long_name_1",
        "ShortName": "short_name",
        "Subtitle": "subtitle",
        "State1": "state_1",
        "Date1": "date_1",
        "Url": "url",
        "Position": "position",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_1_id = Column(types.Integer, ForeignKey('long_name_1.rid', use_alter=True))
    long_name_1 = relationship('LongName1', foreign_keys=[long_name_1_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    subtitle_id = Column(types.Integer, ForeignKey('subtitle.rid', use_alter=True))
    subtitle = relationship('Subtitle', foreign_keys=[subtitle_id], uselist=False, cascade="all")
    state_1_id = Column(types.Integer, ForeignKey('state_1.rid', use_alter=True))
    state_1 = relationship('State1', foreign_keys=[state_1_id], uselist=False, cascade="all")
    date_1_id = Column(types.Integer, ForeignKey('date_1.rid', use_alter=True))
    date_1 = relationship('Date1', foreign_keys=[date_1_id], uselist=False, cascade="all")
    url_id = Column(types.Integer, ForeignKey('url.rid', use_alter=True))
    url = relationship('Url', foreign_keys=[url_id], uselist=False, cascade="all")
    position_id = Column(types.Integer, ForeignKey('position.rid', use_alter=True))
    position = relationship('Position', foreign_keys=[position_id], uselist=False, cascade="all")

class Number(Base):

    __tablename__ = "number"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Publisher(Base):

    __tablename__ = "publisher"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Xdoc(Base):

    __tablename__ = "xdoc"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": "long_name_1",
        "ShortName": "short_name",
        "Number": "number",
        "State1": "state_1",
        "Date1": "date_1",
        "Publisher": "publisher",
        "Url": "url",
        "Position": "position",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_1_id = Column(types.Integer, ForeignKey('long_name_1.rid', use_alter=True))
    long_name_1 = relationship('LongName1', foreign_keys=[long_name_1_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    number_id = Column(types.Integer, ForeignKey('number.rid', use_alter=True))
    number = relationship('Number', foreign_keys=[number_id], uselist=False, cascade="all")
    state_1_id = Column(types.Integer, ForeignKey('state_1.rid', use_alter=True))
    state_1 = relationship('State1', foreign_keys=[state_1_id], uselist=False, cascade="all")
    date_1_id = Column(types.Integer, ForeignKey('date_1.rid', use_alter=True))
    date_1 = relationship('Date1', foreign_keys=[date_1_id], uselist=False, cascade="all")
    publisher_id = Column(types.Integer, ForeignKey('publisher.rid', use_alter=True))
    publisher = relationship('Publisher', foreign_keys=[publisher_id], uselist=False, cascade="all")
    url_id = Column(types.Integer, ForeignKey('url.rid', use_alter=True))
    url = relationship('Url', foreign_keys=[url_id], uselist=False, cascade="all")
    position_id = Column(types.Integer, ForeignKey('position.rid', use_alter=True))
    position = relationship('Position', foreign_keys=[position_id], uselist=False, cascade="all")

class Notation(Base):

    __tablename__ = "notation"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Tool(Base):

    __tablename__ = "tool"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class ToolVersion(Base):

    __tablename__ = "tool_version"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Xfile(Base):

    __tablename__ = "xfile"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": "long_name_1",
        "ShortName": "short_name",
        "Url": "url",
        "Notation": "notation",
        "Tool": "tool",
        "ToolVersion": "tool_version",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_1_id = Column(types.Integer, ForeignKey('long_name_1.rid', use_alter=True))
    long_name_1 = relationship('LongName1', foreign_keys=[long_name_1_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    url_id = Column(types.Integer, ForeignKey('url.rid', use_alter=True))
    url = relationship('Url', foreign_keys=[url_id], uselist=False, cascade="all")
    notation_id = Column(types.Integer, ForeignKey('notation.rid', use_alter=True))
    notation = relationship('Notation', foreign_keys=[notation_id], uselist=False, cascade="all")
    tool_id = Column(types.Integer, ForeignKey('tool.rid', use_alter=True))
    tool = relationship('Tool', foreign_keys=[tool_id], uselist=False, cascade="all")
    tool_version_id = Column(types.Integer, ForeignKey('tool_version.rid', use_alter=True))
    tool_version = relationship('ToolVersion', foreign_keys=[tool_version_id], uselist=False, cascade="all")

class Introduction(Base):

    __tablename__ = "introduction"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "MsrQueryP2": "msr_query_p_2",
        "Topic2": "topic_2",
        "MsrQueryTopic2": "msr_query_topic_2",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    msr_query_p_2_id = Column(types.Integer, ForeignKey('msr_query_p_2.rid', use_alter=True))
    msr_query_p_2 = relationship('MsrQueryP2', foreign_keys=[msr_query_p_2_id], uselist=True, cascade="all")
    topic_2_id = Column(types.Integer, ForeignKey('topic_2.rid', use_alter=True))
    topic_2 = relationship('Topic2', foreign_keys=[topic_2_id], uselist=True, cascade="all")
    msr_query_topic_2_id = Column(types.Integer, ForeignKey('msr_query_topic_2.rid', use_alter=True))
    msr_query_topic_2 = relationship('MsrQueryTopic2', foreign_keys=[msr_query_topic_2_id], uselist=True, cascade="all")

class DocRevisions(Base):

    __tablename__ = "doc_revisions"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "DocRevision": "doc_revision",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    doc_revision_id = Column(types.Integer, ForeignKey('doc_revision.rid', use_alter=True))
    doc_revision = relationship('DocRevision', foreign_keys=[doc_revision_id], uselist=True, cascade="all")

class AdminData(Base):

    __tablename__ = "admin_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Language": "language",
        "UsedLanguages": "used_languages",
        "CompanyDocInfos": "company_doc_infos",
        "FormatterCtrls": "formatter_ctrls",
        "DocRevisions": "doc_revisions",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    language_id = Column(types.Integer, ForeignKey('language.rid', use_alter=True))
    language = relationship('Language', foreign_keys=[language_id], uselist=False, cascade="all")
    used_languages_id = Column(types.Integer, ForeignKey('used_languages.rid', use_alter=True))
    used_languages = relationship('UsedLanguages', foreign_keys=[used_languages_id], uselist=False, cascade="all")
    company_doc_infos_id = Column(types.Integer, ForeignKey('company_doc_infos.rid', use_alter=True))
    company_doc_infos = relationship('CompanyDocInfos', foreign_keys=[company_doc_infos_id], uselist=False, cascade="all")
    formatter_ctrls_id = Column(types.Integer, ForeignKey('formatter_ctrls.rid', use_alter=True))
    formatter_ctrls = relationship('FormatterCtrls', foreign_keys=[formatter_ctrls_id], uselist=False, cascade="all")
    doc_revisions_id = Column(types.Integer, ForeignKey('doc_revisions.rid', use_alter=True))
    doc_revisions = relationship('DocRevisions', foreign_keys=[doc_revisions_id], uselist=False, cascade="all")

class Ncoi1(Base):

    __tablename__ = "ncoi_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class CompanyRef(Base):

    __tablename__ = "company_ref"
    ATTRIBUTES = {
        "F-ID-CLASS": "f_id_class",
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    f_id_class = StdString()
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class DocLabel(Base):

    __tablename__ = "doc_label"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class PrivateCodes(Base):

    __tablename__ = "private_codes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "PrivateCode": "private_code",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    private_code_id = Column(types.Integer, ForeignKey('private_code.rid', use_alter=True))
    private_code = relationship('PrivateCode', foreign_keys=[private_code_id], uselist=True, cascade="all")

class EntityName(Base):

    __tablename__ = "entity_name"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class PrivateCode(Base):

    __tablename__ = "private_code"
    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class CompanyDocInfo(Base):

    __tablename__ = "company_doc_info"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRef": "company_ref",
        "DocLabel": "doc_label",
        "TeamMemberRef": "team_member_ref",
        "PrivateCodes": "private_codes",
        "EntityName": "entity_name",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    company_ref_id = Column(types.Integer, ForeignKey('company_ref.rid', use_alter=True))
    company_ref = relationship('CompanyRef', foreign_keys=[company_ref_id], uselist=False, cascade="all")
    doc_label_id = Column(types.Integer, ForeignKey('doc_label.rid', use_alter=True))
    doc_label = relationship('DocLabel', foreign_keys=[doc_label_id], uselist=False, cascade="all")
    team_member_ref_id = Column(types.Integer, ForeignKey('team_member_ref.rid', use_alter=True))
    team_member_ref = relationship('TeamMemberRef', foreign_keys=[team_member_ref_id], uselist=False, cascade="all")
    private_codes_id = Column(types.Integer, ForeignKey('private_codes.rid', use_alter=True))
    private_codes = relationship('PrivateCodes', foreign_keys=[private_codes_id], uselist=False, cascade="all")
    entity_name_id = Column(types.Integer, ForeignKey('entity_name.rid', use_alter=True))
    entity_name = relationship('EntityName', foreign_keys=[entity_name_id], uselist=False, cascade="all")

class SystemOverview(Base):

    __tablename__ = "system_overview"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FormatterCtrl(Base):

    __tablename__ = "formatter_ctrl"
    ATTRIBUTES = {
        "TARGET-SYSTEM": "target_system",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    target_system = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class ReasonOrder(Base):

    __tablename__ = "reason_order"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class CompanyRevisionInfos(Base):

    __tablename__ = "company_revision_infos"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRevisionInfo": "company_revision_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    company_revision_info_id = Column(types.Integer, ForeignKey('company_revision_info.rid', use_alter=True))
    company_revision_info = relationship('CompanyRevisionInfo', foreign_keys=[company_revision_info_id], uselist=True, cascade="all")

class RevisionLabel(Base):

    __tablename__ = "revision_label"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class State(Base):

    __tablename__ = "state"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Remark(Base):

    __tablename__ = "remark"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")

class IssuedBy(Base):

    __tablename__ = "issued_by"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class CompanyRevisionInfo(Base):

    __tablename__ = "company_revision_info"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRef": "company_ref",
        "RevisionLabel": "revision_label",
        "State": "state",
        "Remark": "remark",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    company_ref_id = Column(types.Integer, ForeignKey('company_ref.rid', use_alter=True))
    company_ref = relationship('CompanyRef', foreign_keys=[company_ref_id], uselist=False, cascade="all")
    revision_label_id = Column(types.Integer, ForeignKey('revision_label.rid', use_alter=True))
    revision_label = relationship('RevisionLabel', foreign_keys=[revision_label_id], uselist=False, cascade="all")
    state_id = Column(types.Integer, ForeignKey('state.rid', use_alter=True))
    state = relationship('State', foreign_keys=[state_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")

class P(Base):

    __tablename__ = "p"
    ATTRIBUTES = {
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "Std": "std",
        "Xdoc": "xdoc",
        "Xfile": "xfile",
        "MsrQueryText": "msr_query_text",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    TERMINAL = True
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    std_id = Column(types.Integer, ForeignKey('std.rid', use_alter=True))
    std = relationship('Std', foreign_keys=[std_id], uselist=True, cascade="all")
    xdoc_id = Column(types.Integer, ForeignKey('xdoc.rid', use_alter=True))
    xdoc = relationship('Xdoc', foreign_keys=[xdoc_id], uselist=True, cascade="all")
    xfile_id = Column(types.Integer, ForeignKey('xfile.rid', use_alter=True))
    xfile = relationship('Xfile', foreign_keys=[xfile_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class Verbatim(Base):

    __tablename__ = "verbatim"
    ATTRIBUTES = {
        "ALLOW-BREAK": "allow_break",
        "HELP-ENTRY": "help_entry",
        "FLOAT": "_float",
        "PGWIDE": "pgwide",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "E": "e",
    }
    ENUMS = {
        "_float": ['FLOAT', 'NO-FLOAT'],
        "pgwide": ['PGWIDE', 'NO-PGWIDE'],
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    allow_break = StdString()
    help_entry = StdString()
    _float = StdString()
    pgwide = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")

class FigureCaption(Base):

    __tablename__ = "figure_caption"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")

class Graphic(Base):

    __tablename__ = "graphic"
    ATTRIBUTES = {
        "FILENAME": "filename",
        "NOTATION": "notation",
        "WIDTH": "width",
        "HEIGHT": "height",
        "SCALE": "scale",
        "FIT": "fit",
        "EDIT-WIDTH": "edit_width",
        "EDIT-HEIGHT": "edit_height",
        "HTML-WIDTH": "html_width",
        "HTML-HEIGHT": "html_height",
        "HTML-FIT": "html_fit",
        "CATEGORY": "category",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "category": ['BARCODE', 'CONCEPTUAL', 'ENGINEERING', 'FLOWCHART', 'GRAPH', 'LOGO', 'SCHEMATIC', 'WAVEFORM'],
    }
    TERMINAL = True
    filename = StdString()
    notation = StdString()
    width = StdString()
    height = StdString()
    scale = StdString()
    fit = StdString()
    edit_width = StdString()
    edit_height = StdString()
    html_width = StdString()
    html_height = StdString()
    html_fit = StdString()
    category = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Map(Base):

    __tablename__ = "map"
    ATTRIBUTES = {
        "ID": "_id",
        "CLASS": "_class",
        "STYLE": "style",
        "TITLE": "title",
        "ONCLICK": "onclick",
        "ONDBLCLICK": "ondblclick",
        "ONMOUSEDOWN": "onmousedown",
        "ONMOUSEUP": "onmouseup",
        "ONMOUSEOVER": "onmouseover",
        "ONMOUSEMOVE": "onmousemove",
        "ONMOUSEOUT": "onmouseout",
        "ONKEYPRESS": "onkeypress",
        "ONKEYDOWN": "onkeydown",
        "ONKEYUP": "onkeyup",
        "NAME": "name",
    }
    ELEMENTS = {
        "Area": "area",
    }
    _id = StdString()
    _class = StdString()
    style = StdString()
    title = StdString()
    onclick = StdString()
    ondblclick = StdString()
    onmousedown = StdString()
    onmouseup = StdString()
    onmouseover = StdString()
    onmousemove = StdString()
    onmouseout = StdString()
    onkeypress = StdString()
    onkeydown = StdString()
    onkeyup = StdString()
    name = StdString()
    area_id = Column(types.Integer, ForeignKey('area.rid', use_alter=True))
    area = relationship('Area', foreign_keys=[area_id], uselist=True, cascade="all")

class Figure(Base):

    __tablename__ = "figure"
    ATTRIBUTES = {
        "FLOAT": "_float",
        "HELP-ENTRY": "help_entry",
        "PGWIDE": "pgwide",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FigureCaption": "figure_caption",
        "Graphic": "graphic",
        "Map": "_map",
        "Verbatim": "verbatim",
        "Desc": "_desc",
    }
    ENUMS = {
        "_float": ['FLOAT', 'NO-FLOAT'],
        "pgwide": ['PGWIDE', 'NO-PGWIDE'],
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    _float = StdString()
    help_entry = StdString()
    pgwide = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    figure_caption_id = Column(types.Integer, ForeignKey('figure_caption.rid', use_alter=True))
    figure_caption = relationship('FigureCaption', foreign_keys=[figure_caption_id], uselist=False, cascade="all")
    graphic_id = Column(types.Integer, ForeignKey('graphic.rid', use_alter=True))
    graphic = relationship('Graphic', foreign_keys=[graphic_id], uselist=False, cascade="all")
    map_id = Column(types.Integer, ForeignKey('map.rid', use_alter=True))
    _map = relationship('Map', foreign_keys=[map_id], uselist=False, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")

class Area(Base):

    __tablename__ = "area"
    ATTRIBUTES = {
    }
    ELEMENTS = {
    }
    TERMINAL = True

class FormulaCaption(Base):

    __tablename__ = "formula_caption"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")

class TexMath(Base):

    __tablename__ = "tex_math"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class CCode(Base):

    __tablename__ = "c_code"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class GenericMath(Base):

    __tablename__ = "generic_math"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Formula(Base):

    __tablename__ = "formula"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FormulaCaption": "formula_caption",
        "Graphic": "graphic",
        "Map": "_map",
        "Verbatim": "verbatim",
        "TexMath": "tex_math",
        "CCode": "c_code",
        "GenericMath": "generic_math",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    formula_caption_id = Column(types.Integer, ForeignKey('formula_caption.rid', use_alter=True))
    formula_caption = relationship('FormulaCaption', foreign_keys=[formula_caption_id], uselist=False, cascade="all")
    graphic_id = Column(types.Integer, ForeignKey('graphic.rid', use_alter=True))
    graphic = relationship('Graphic', foreign_keys=[graphic_id], uselist=False, cascade="all")
    map_id = Column(types.Integer, ForeignKey('map.rid', use_alter=True))
    _map = relationship('Map', foreign_keys=[map_id], uselist=False, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=False, cascade="all")
    tex_math_id = Column(types.Integer, ForeignKey('tex_math.rid', use_alter=True))
    tex_math = relationship('TexMath', foreign_keys=[tex_math_id], uselist=False, cascade="all")
    c_code_id = Column(types.Integer, ForeignKey('c_code.rid', use_alter=True))
    c_code = relationship('CCode', foreign_keys=[c_code_id], uselist=False, cascade="all")
    generic_math_id = Column(types.Integer, ForeignKey('generic_math.rid', use_alter=True))
    generic_math = relationship('GenericMath', foreign_keys=[generic_math_id], uselist=False, cascade="all")

class List(Base):

    __tablename__ = "list"
    ATTRIBUTES = {
        "TYPE": "_type",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Item": "item",
    }
    ENUMS = {
        "_type": ['UNNUMBER', 'NUMBER'],
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    _type = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    item_id = Column(types.Integer, ForeignKey('item.rid', use_alter=True))
    item = relationship('Item', foreign_keys=[item_id], uselist=True, cascade="all")

class Item(Base):

    __tablename__ = "item"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")

class DefList(Base):

    __tablename__ = "def_list"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "DefItem": "def_item",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    def_item_id = Column(types.Integer, ForeignKey('def_item.rid', use_alter=True))
    def_item = relationship('DefItem', foreign_keys=[def_item_id], uselist=True, cascade="all")

class Def(Base):

    __tablename__ = "def"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")

class DefItem(Base):

    __tablename__ = "def_item"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Def": "_def",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    def_id = Column(types.Integer, ForeignKey('def.rid', use_alter=True))
    _def = relationship('Def', foreign_keys=[def_id], uselist=False, cascade="all")

class IndentSample(Base):

    __tablename__ = "indent_sample"
    ATTRIBUTES = {
        "ITEM-LABEL-POS": "item_label_pos",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "MsrQueryText": "msr_query_text",
    }
    ENUMS = {
        "item_label_pos": ['NO-NEWLINE', 'NEWLINE', 'NEWLINE-IF-NECESSARY'],
    }
    item_label_pos = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class LabeledList(Base):

    __tablename__ = "labeled_list"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "IndentSample": "indent_sample",
        "LabeledItem": "labeled_item",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    indent_sample_id = Column(types.Integer, ForeignKey('indent_sample.rid', use_alter=True))
    indent_sample = relationship('IndentSample', foreign_keys=[indent_sample_id], uselist=False, cascade="all")
    labeled_item_id = Column(types.Integer, ForeignKey('labeled_item.rid', use_alter=True))
    labeled_item = relationship('LabeledItem', foreign_keys=[labeled_item_id], uselist=True, cascade="all")

class ItemLabel(Base):

    __tablename__ = "item_label"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "MsrQueryText": "msr_query_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class LabeledItem(Base):

    __tablename__ = "labeled_item"
    ATTRIBUTES = {
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "ItemLabel": "item_label",
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    item_label_id = Column(types.Integer, ForeignKey('item_label.rid', use_alter=True))
    item_label = relationship('ItemLabel', foreign_keys=[item_label_id], uselist=False, cascade="all")
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")

class Note(Base):

    __tablename__ = "note"
    ATTRIBUTES = {
        "NOTE-TYPE": "note_type",
        "USER-DEFINED-TYPE": "user_defined_type",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "P": "p",
    }
    ENUMS = {
        "note_type": ['CAUTION', 'HINT', 'TIP', 'INSTRUCTION', 'EXERCISE', 'OTHER'],
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    note_type = StdString()
    user_defined_type = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")

class Modifications(Base):

    __tablename__ = "modifications"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Modification": "modification",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    modification_id = Column(types.Integer, ForeignKey('modification.rid', use_alter=True))
    modification = relationship('Modification', foreign_keys=[modification_id], uselist=True, cascade="all")

class DocRevision(Base):

    __tablename__ = "doc_revision"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRevisionInfos": "company_revision_infos",
        "RevisionLabel": "revision_label",
        "State": "state",
        "IssuedBy": "issued_by",
        "TeamMemberRef": "team_member_ref",
        "Date": "date",
        "Modifications": "modifications",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    company_revision_infos_id = Column(types.Integer, ForeignKey('company_revision_infos.rid', use_alter=True))
    company_revision_infos = relationship('CompanyRevisionInfos', foreign_keys=[company_revision_infos_id], uselist=False, cascade="all")
    revision_label_id = Column(types.Integer, ForeignKey('revision_label.rid', use_alter=True))
    revision_label = relationship('RevisionLabel', foreign_keys=[revision_label_id], uselist=False, cascade="all")
    state_id = Column(types.Integer, ForeignKey('state.rid', use_alter=True))
    state = relationship('State', foreign_keys=[state_id], uselist=False, cascade="all")
    issued_by_id = Column(types.Integer, ForeignKey('issued_by.rid', use_alter=True))
    issued_by = relationship('IssuedBy', foreign_keys=[issued_by_id], uselist=False, cascade="all")
    team_member_ref_id = Column(types.Integer, ForeignKey('team_member_ref.rid', use_alter=True))
    team_member_ref = relationship('TeamMemberRef', foreign_keys=[team_member_ref_id], uselist=False, cascade="all")
    date_id = Column(types.Integer, ForeignKey('date.rid', use_alter=True))
    date = relationship('Date', foreign_keys=[date_id], uselist=False, cascade="all")
    modifications_id = Column(types.Integer, ForeignKey('modifications.rid', use_alter=True))
    modifications = relationship('Modifications', foreign_keys=[modifications_id], uselist=False, cascade="all")

class Change(Base):

    __tablename__ = "change"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "MsrQueryText": "msr_query_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class Reason(Base):

    __tablename__ = "reason"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": "tt",
        "Xref": "xref",
        "XrefTarget": "xref_target",
        "E": "e",
        "Ft": "ft",
        "Sup": "sup",
        "Sub": "sub",
        "Ie": "ie",
        "MsrQueryText": "msr_query_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    tt_id = Column(types.Integer, ForeignKey('tt.rid', use_alter=True))
    tt = relationship('Tt', foreign_keys=[tt_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")
    xref_target_id = Column(types.Integer, ForeignKey('xref_target.rid', use_alter=True))
    xref_target = relationship('XrefTarget', foreign_keys=[xref_target_id], uselist=True, cascade="all")
    e_id = Column(types.Integer, ForeignKey('e.rid', use_alter=True))
    e = relationship('E', foreign_keys=[e_id], uselist=True, cascade="all")
    ft_id = Column(types.Integer, ForeignKey('ft.rid', use_alter=True))
    ft = relationship('Ft', foreign_keys=[ft_id], uselist=True, cascade="all")
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")
    ie_id = Column(types.Integer, ForeignKey('ie.rid', use_alter=True))
    ie = relationship('Ie', foreign_keys=[ie_id], uselist=True, cascade="all")
    msr_query_text_id = Column(types.Integer, ForeignKey('msr_query_text.rid', use_alter=True))
    msr_query_text = relationship('MsrQueryText', foreign_keys=[msr_query_text_id], uselist=True, cascade="all")

class Modification(Base):

    __tablename__ = "modification"
    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Change": "change",
        "Reason": "reason",
    }
    ENUMS = {
        "_type": ['CONTENT-RELATED', 'DOC-RELATED'],
    }
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    change_id = Column(types.Integer, ForeignKey('change.rid', use_alter=True))
    change = relationship('Change', foreign_keys=[change_id], uselist=False, cascade="all")
    reason_id = Column(types.Integer, ForeignKey('reason.rid', use_alter=True))
    reason = relationship('Reason', foreign_keys=[reason_id], uselist=False, cascade="all")

class ProductDesc(Base):

    __tablename__ = "product_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class TableCaption(Base):

    __tablename__ = "table_caption"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")

class Table(Base):

    __tablename__ = "table"
    ATTRIBUTES = {
        "TABSTYLE": "tabstyle",
        "TOCENTRY": "tocentry",
        "SHORTENTRY": "shortentry",
        "FRAME": "frame",
        "COLSEP": "colsep",
        "ROWSEP": "rowsep",
        "ORIENT": "orient",
        "PGWIDE": "pgwide",
        "HELP-ENTRY": "help_entry",
        "FLOAT": "_float",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TableCaption": "table_caption",
        "Tgroup": "tgroup",
    }
    ENUMS = {
        "frame": ['TOP', 'BOTTOM', 'TOPBOT', 'ALL', 'SIDES', 'NONE'],
        "orient": ['PORT', 'LAND'],
        "_float": ['FLOAT', 'NO-FLOAT'],
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    tabstyle = StdString()
    tocentry = StdString()
    shortentry = StdString()
    frame = StdString()
    colsep = StdString()
    rowsep = StdString()
    orient = StdString()
    pgwide = StdString()
    help_entry = StdString()
    _float = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    table_caption_id = Column(types.Integer, ForeignKey('table_caption.rid', use_alter=True))
    table_caption = relationship('TableCaption', foreign_keys=[table_caption_id], uselist=False, cascade="all")
    tgroup_id = Column(types.Integer, ForeignKey('tgroup.rid', use_alter=True))
    tgroup = relationship('Tgroup', foreign_keys=[tgroup_id], uselist=True, cascade="all")

class Thead(Base):

    __tablename__ = "thead"
    ATTRIBUTES = {
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Colspec": "colspec",
        "Row": "_row",
    }
    ENUMS = {
        "valign": ['TOP', 'MIDDLE', 'BOTTOM'],
    }
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    colspec_id = Column(types.Integer, ForeignKey('colspec.rid', use_alter=True))
    colspec = relationship('Colspec', foreign_keys=[colspec_id], uselist=True, cascade="all")
    row_id = Column(types.Integer, ForeignKey('row.rid', use_alter=True))
    _row = relationship('Row', foreign_keys=[row_id], uselist=True, cascade="all")

class Colspec(Base):

    __tablename__ = "colspec"
    ATTRIBUTES = {
    }
    ELEMENTS = {
    }
    TERMINAL = True

class Spanspec(Base):

    __tablename__ = "spanspec"
    ATTRIBUTES = {
    }
    ELEMENTS = {
    }
    TERMINAL = True

class Tfoot(Base):

    __tablename__ = "tfoot"
    ATTRIBUTES = {
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Colspec": "colspec",
        "Row": "_row",
    }
    ENUMS = {
        "valign": ['TOP', 'MIDDLE', 'BOTTOM'],
    }
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    colspec_id = Column(types.Integer, ForeignKey('colspec.rid', use_alter=True))
    colspec = relationship('Colspec', foreign_keys=[colspec_id], uselist=True, cascade="all")
    row_id = Column(types.Integer, ForeignKey('row.rid', use_alter=True))
    _row = relationship('Row', foreign_keys=[row_id], uselist=True, cascade="all")

class Row(Base):

    __tablename__ = "row"
    ATTRIBUTES = {
        "ROWSEP": "rowsep",
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Entry": "entry",
    }
    ENUMS = {
        "valign": ['TOP', 'BOTTOM', 'MIDDLE'],
    }
    rowsep = StdString()
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    entry_id = Column(types.Integer, ForeignKey('entry.rid', use_alter=True))
    entry = relationship('Entry', foreign_keys=[entry_id], uselist=True, cascade="all")

class Entry(Base):

    __tablename__ = "entry"
    ATTRIBUTES = {
        "COLNAME": "colname",
        "NAMEST": "namest",
        "NAMEEND": "nameend",
        "SPANNAME": "spanname",
        "MOREROWS": "morerows",
        "COLSEP": "colsep",
        "ROWSEP": "rowsep",
        "ROTATE": "rotate",
        "VALIGN": "valign",
        "ALIGN": "align",
        "CHAROFF": "charoff",
        "CHAR": "char",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
    }
    ENUMS = {
        "valign": ['TOP', 'BOTTOM', 'MIDDLE'],
        "align": ['LEFT', 'RIGHT', 'CENTER', 'JUSTIFY', 'CHAR'],
    }
    colname = StdString()
    namest = StdString()
    nameend = StdString()
    spanname = StdString()
    morerows = StdString()
    colsep = StdString()
    rowsep = StdString()
    rotate = StdString()
    valign = StdString()
    align = StdString()
    charoff = StdString()
    char = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")

class Tbody(Base):

    __tablename__ = "tbody"
    ATTRIBUTES = {
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Row": "_row",
    }
    ENUMS = {
        "valign": ['TOP', 'MIDDLE', 'BOTTOM'],
    }
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    row_id = Column(types.Integer, ForeignKey('row.rid', use_alter=True))
    _row = relationship('Row', foreign_keys=[row_id], uselist=True, cascade="all")

class Tgroup(Base):

    __tablename__ = "tgroup"
    ATTRIBUTES = {
        "COLS": "cols",
        "TGROUPSTYLE": "tgroupstyle",
        "COLSEP": "colsep",
        "ROWSEP": "rowsep",
        "ALIGN": "align",
        "CHAROFF": "charoff",
        "CHAR": "char",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Colspec": "colspec",
        "Spanspec": "spanspec",
        "Thead": "thead",
        "Tfoot": "tfoot",
        "Tbody": "tbody",
    }
    ENUMS = {
        "align": ['LEFT', 'RIGHT', 'CENTER', 'JUSTIFY', 'CHAR'],
    }
    cols = StdString()
    tgroupstyle = StdString()
    colsep = StdString()
    rowsep = StdString()
    align = StdString()
    charoff = StdString()
    char = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    colspec_id = Column(types.Integer, ForeignKey('colspec.rid', use_alter=True))
    colspec = relationship('Colspec', foreign_keys=[colspec_id], uselist=True, cascade="all")
    spanspec_id = Column(types.Integer, ForeignKey('spanspec.rid', use_alter=True))
    spanspec = relationship('Spanspec', foreign_keys=[spanspec_id], uselist=True, cascade="all")
    thead_id = Column(types.Integer, ForeignKey('thead.rid', use_alter=True))
    thead = relationship('Thead', foreign_keys=[thead_id], uselist=False, cascade="all")
    tfoot_id = Column(types.Integer, ForeignKey('tfoot.rid', use_alter=True))
    tfoot = relationship('Tfoot', foreign_keys=[tfoot_id], uselist=False, cascade="all")
    tbody_id = Column(types.Integer, ForeignKey('tbody.rid', use_alter=True))
    tbody = relationship('Tbody', foreign_keys=[tbody_id], uselist=False, cascade="all")

class MsrQueryResultP2(Base):

    __tablename__ = "msr_query_result_p_2"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")

class MsrQueryP2(Base):

    __tablename__ = "msr_query_p_2"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": "msr_query_props",
        "MsrQueryResultP2": "msr_query_result_p_2",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_props_id = Column(types.Integer, ForeignKey('msr_query_props.rid', use_alter=True))
    msr_query_props = relationship('MsrQueryProps', foreign_keys=[msr_query_props_id], uselist=False, cascade="all")
    msr_query_result_p_2_id = Column(types.Integer, ForeignKey('msr_query_result_p_2.rid', use_alter=True))
    msr_query_result_p_2 = relationship('MsrQueryResultP2', foreign_keys=[msr_query_result_p_2_id], uselist=False, cascade="all")

class Topic2(Base):

    __tablename__ = "topic_2"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "MsrQueryP2": "msr_query_p_2",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    msr_query_p_2_id = Column(types.Integer, ForeignKey('msr_query_p_2.rid', use_alter=True))
    msr_query_p_2 = relationship('MsrQueryP2', foreign_keys=[msr_query_p_2_id], uselist=True, cascade="all")

class MsrQueryResultTopic2(Base):

    __tablename__ = "msr_query_result_topic_2"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Topic2": "topic_2",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    topic_2_id = Column(types.Integer, ForeignKey('topic_2.rid', use_alter=True))
    topic_2 = relationship('Topic2', foreign_keys=[topic_2_id], uselist=True, cascade="all")

class MsrQueryTopic2(Base):

    __tablename__ = "msr_query_topic_2"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": "msr_query_props",
        "MsrQueryResultTopic2": "msr_query_result_topic_2",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_props_id = Column(types.Integer, ForeignKey('msr_query_props.rid', use_alter=True))
    msr_query_props = relationship('MsrQueryProps', foreign_keys=[msr_query_props_id], uselist=False, cascade="all")
    msr_query_result_topic_2_id = Column(types.Integer, ForeignKey('msr_query_result_topic_2.rid', use_alter=True))
    msr_query_result_topic_2 = relationship('MsrQueryResultTopic2', foreign_keys=[msr_query_result_topic_2_id], uselist=False, cascade="all")

class Objectives(Base):

    __tablename__ = "objectives"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Rights(Base):

    __tablename__ = "rights"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Prms(Base):

    __tablename__ = "prms"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "Prm": "prm",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    prm_id = Column(types.Integer, ForeignKey('prm.rid', use_alter=True))
    prm = relationship('Prm', foreign_keys=[prm_id], uselist=True, cascade="all")

class Prm(Base):

    __tablename__ = "prm"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "PrmChar": "prm_char",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    prm_char_id = Column(types.Integer, ForeignKey('prm_char.rid', use_alter=True))
    prm_char = relationship('PrmChar', foreign_keys=[prm_char_id], uselist=True, cascade="all")

class Cond(Base):

    __tablename__ = "cond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")

class Abs(Base):

    __tablename__ = "abs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Tol(Base):

    __tablename__ = "tol"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Min(Base):

    __tablename__ = "min"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Typ(Base):

    __tablename__ = "typ"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Max(Base):

    __tablename__ = "max"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Unit(Base):

    __tablename__ = "unit"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class Text(Base):

    __tablename__ = "text"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class PrmChar(Base):

    __tablename__ = "prm_char"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Cond": "cond",
        "Abs": "_abs",
        "Tol": "tol",
        "Min": "_min",
        "Typ": "typ",
        "Max": "_max",
        "Unit": "unit",
        "Text": "text",
        "Remark": "remark",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    cond_id = Column(types.Integer, ForeignKey('cond.rid', use_alter=True))
    cond = relationship('Cond', foreign_keys=[cond_id], uselist=False, cascade="all")
    abs_id = Column(types.Integer, ForeignKey('abs.rid', use_alter=True))
    _abs = relationship('Abs', foreign_keys=[abs_id], uselist=False, cascade="all")
    tol_id = Column(types.Integer, ForeignKey('tol.rid', use_alter=True))
    tol = relationship('Tol', foreign_keys=[tol_id], uselist=False, cascade="all")
    min_id = Column(types.Integer, ForeignKey('min.rid', use_alter=True))
    _min = relationship('Min', foreign_keys=[min_id], uselist=False, cascade="all")
    typ_id = Column(types.Integer, ForeignKey('typ.rid', use_alter=True))
    typ = relationship('Typ', foreign_keys=[typ_id], uselist=False, cascade="all")
    max_id = Column(types.Integer, ForeignKey('max.rid', use_alter=True))
    _max = relationship('Max', foreign_keys=[max_id], uselist=False, cascade="all")
    unit_id = Column(types.Integer, ForeignKey('unit.rid', use_alter=True))
    unit = relationship('Unit', foreign_keys=[unit_id], uselist=False, cascade="all")
    text_id = Column(types.Integer, ForeignKey('text.rid', use_alter=True))
    text = relationship('Text', foreign_keys=[text_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")

class MsrQueryResultP1(Base):

    __tablename__ = "msr_query_result_p_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")

class MsrQueryP1(Base):

    __tablename__ = "msr_query_p_1"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": "msr_query_props",
        "MsrQueryResultP1": "msr_query_result_p_1",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_props_id = Column(types.Integer, ForeignKey('msr_query_props.rid', use_alter=True))
    msr_query_props = relationship('MsrQueryProps', foreign_keys=[msr_query_props_id], uselist=False, cascade="all")
    msr_query_result_p_1_id = Column(types.Integer, ForeignKey('msr_query_result_p_1.rid', use_alter=True))
    msr_query_result_p_1 = relationship('MsrQueryResultP1', foreign_keys=[msr_query_result_p_1_id], uselist=False, cascade="all")

class Topic1(Base):

    __tablename__ = "topic_1"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")

class MsrQueryResultTopic1(Base):

    __tablename__ = "msr_query_result_topic_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Topic1": "topic_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")

class MsrQueryTopic1(Base):

    __tablename__ = "msr_query_topic_1"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": "msr_query_props",
        "MsrQueryResultTopic1": "msr_query_result_topic_1",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_props_id = Column(types.Integer, ForeignKey('msr_query_props.rid', use_alter=True))
    msr_query_props = relationship('MsrQueryProps', foreign_keys=[msr_query_props_id], uselist=False, cascade="all")
    msr_query_result_topic_1_id = Column(types.Integer, ForeignKey('msr_query_result_topic_1.rid', use_alter=True))
    msr_query_result_topic_1 = relationship('MsrQueryResultTopic1', foreign_keys=[msr_query_result_topic_1_id], uselist=False, cascade="all")

class Chapter(Base):

    __tablename__ = "chapter"
    ATTRIBUTES = {
        "BREAK": "_break",
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    ENUMS = {
        "_break": ['BREAK', 'NO-BREAK'],
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    _break = StdString()
    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class MsrQueryResultChapter(Base):

    __tablename__ = "msr_query_result_chapter"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Chapter": "chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")

class MsrQueryChapter(Base):

    __tablename__ = "msr_query_chapter"
    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": "msr_query_props",
        "MsrQueryResultChapter": "msr_query_result_chapter",
    }
    ENUMS = {
        "keep_with_previous": ['KEEP', 'NO-KEEP'],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    msr_query_props_id = Column(types.Integer, ForeignKey('msr_query_props.rid', use_alter=True))
    msr_query_props = relationship('MsrQueryProps', foreign_keys=[msr_query_props_id], uselist=False, cascade="all")
    msr_query_result_chapter_id = Column(types.Integer, ForeignKey('msr_query_result_chapter.rid', use_alter=True))
    msr_query_result_chapter = relationship('MsrQueryResultChapter', foreign_keys=[msr_query_result_chapter_id], uselist=False, cascade="all")

class Guarantee(Base):

    __tablename__ = "guarantee"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Maintenance(Base):

    __tablename__ = "maintenance"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Samples(Base):

    __tablename__ = "samples"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sample": "sample",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sample_id = Column(types.Integer, ForeignKey('sample.rid', use_alter=True))
    sample = relationship('Sample', foreign_keys=[sample_id], uselist=True, cascade="all")

class AddSpec(Base):

    __tablename__ = "add_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class ContractAspects(Base):

    __tablename__ = "contract_aspects"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Rights": "rights",
        "Guarantee": "guarantee",
        "Maintenance": "maintenance",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    rights_id = Column(types.Integer, ForeignKey('rights.rid', use_alter=True))
    rights = relationship('Rights', foreign_keys=[rights_id], uselist=False, cascade="all")
    guarantee_id = Column(types.Integer, ForeignKey('guarantee.rid', use_alter=True))
    guarantee = relationship('Guarantee', foreign_keys=[guarantee_id], uselist=False, cascade="all")
    maintenance_id = Column(types.Integer, ForeignKey('maintenance.rid', use_alter=True))
    maintenance = relationship('Maintenance', foreign_keys=[maintenance_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class SampleSpec(Base):

    __tablename__ = "sample_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Samples": "samples",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    samples_id = Column(types.Integer, ForeignKey('samples.rid', use_alter=True))
    samples = relationship('Samples', foreign_keys=[samples_id], uselist=False, cascade="all")

class VariantChars(Base):

    __tablename__ = "variant_chars"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantChar": "variant_char",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    variant_char_id = Column(types.Integer, ForeignKey('variant_char.rid', use_alter=True))
    variant_char = relationship('VariantChar', foreign_keys=[variant_char_id], uselist=True, cascade="all")

class VariantDefs(Base):

    __tablename__ = "variant_defs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantDef": "variant_def",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    variant_def_id = Column(types.Integer, ForeignKey('variant_def.rid', use_alter=True))
    variant_def = relationship('VariantDef', foreign_keys=[variant_def_id], uselist=True, cascade="all")

class VariantSpec(Base):

    __tablename__ = "variant_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "VariantChars": "variant_chars",
        "VariantDefs": "variant_defs",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    variant_chars_id = Column(types.Integer, ForeignKey('variant_chars.rid', use_alter=True))
    variant_chars = relationship('VariantChars', foreign_keys=[variant_chars_id], uselist=False, cascade="all")
    variant_defs_id = Column(types.Integer, ForeignKey('variant_defs.rid', use_alter=True))
    variant_defs = relationship('VariantDefs', foreign_keys=[variant_defs_id], uselist=False, cascade="all")

class Sample(Base):

    __tablename__ = "sample"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-CHILD-TYPE": "f_child_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Ncoi1": "ncoi_1",
    }
    _id = StdString()
    f_id_class = StdString()
    f_child_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class DemarcationOtherProjects(Base):

    __tablename__ = "demarcation_other_projects"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class ParallelDesigns(Base):

    __tablename__ = "parallel_designs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Code(Base):

    __tablename__ = "code"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class VariantChar(Base):

    __tablename__ = "variant_char"
    ATTRIBUTES = {
        "TYPE": "_type",
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Code": "code",
    }
    ENUMS = {
        "_type": ['NEW-PART-NUMBER', 'NO-NEW-PART-NUMBER'],
    }
    _type = StdString()
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    code_id = Column(types.Integer, ForeignKey('code.rid', use_alter=True))
    code = relationship('Code', foreign_keys=[code_id], uselist=False, cascade="all")

class IntegrationCapability(Base):

    __tablename__ = "integration_capability"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class VariantCharAssigns(Base):

    __tablename__ = "variant_char_assigns"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantCharAssign": "variant_char_assign",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    variant_char_assign_id = Column(types.Integer, ForeignKey('variant_char_assign.rid', use_alter=True))
    variant_char_assign = relationship('VariantCharAssign', foreign_keys=[variant_char_assign_id], uselist=True, cascade="all")

class VariantDef(Base):

    __tablename__ = "variant_def"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Code": "code",
        "VariantCharAssigns": "variant_char_assigns",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    code_id = Column(types.Integer, ForeignKey('code.rid', use_alter=True))
    code = relationship('Code', foreign_keys=[code_id], uselist=False, cascade="all")
    variant_char_assigns_id = Column(types.Integer, ForeignKey('variant_char_assigns.rid', use_alter=True))
    variant_char_assigns = relationship('VariantCharAssigns', foreign_keys=[variant_char_assigns_id], uselist=False, cascade="all")

class VariantCharRef(Base):

    __tablename__ = "variant_char_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Value(Base):

    __tablename__ = "value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class VariantCharValue(Base):

    __tablename__ = "variant_char_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Value": "value",
        "Code": "code",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    value_id = Column(types.Integer, ForeignKey('value.rid', use_alter=True))
    value = relationship('Value', foreign_keys=[value_id], uselist=False, cascade="all")
    code_id = Column(types.Integer, ForeignKey('code.rid', use_alter=True))
    code = relationship('Code', foreign_keys=[code_id], uselist=False, cascade="all")

class VariantCharAssign(Base):

    __tablename__ = "variant_char_assign"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantCharRef": "variant_char_ref",
        "VariantCharValue": "variant_char_value",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    variant_char_ref_id = Column(types.Integer, ForeignKey('variant_char_ref.rid', use_alter=True))
    variant_char_ref = relationship('VariantCharRef', foreign_keys=[variant_char_ref_id], uselist=False, cascade="all")
    variant_char_value_id = Column(types.Integer, ForeignKey('variant_char_value.rid', use_alter=True))
    variant_char_value = relationship('VariantCharValue', foreign_keys=[variant_char_value_id], uselist=False, cascade="all")

class AcceptanceCond(Base):

    __tablename__ = "acceptance_cond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class ProjectSchedule(Base):

    __tablename__ = "project_schedule"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class PurchasingCond(Base):

    __tablename__ = "purchasing_cond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Protocols(Base):

    __tablename__ = "protocols"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class DirHandOverDocData(Base):

    __tablename__ = "dir_hand_over_doc_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class GeneralProjectData(Base):

    __tablename__ = "general_project_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SystemOverview": "system_overview",
        "ReasonOrder": "reason_order",
        "Objectives": "objectives",
        "ContractAspects": "contract_aspects",
        "SampleSpec": "sample_spec",
        "VariantSpec": "variant_spec",
        "DemarcationOtherProjects": "demarcation_other_projects",
        "ParallelDesigns": "parallel_designs",
        "IntegrationCapability": "integration_capability",
        "AcceptanceCond": "acceptance_cond",
        "ProjectSchedule": "project_schedule",
        "PurchasingCond": "purchasing_cond",
        "Protocols": "protocols",
        "DirHandOverDocData": "dir_hand_over_doc_data",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    system_overview_id = Column(types.Integer, ForeignKey('system_overview.rid', use_alter=True))
    system_overview = relationship('SystemOverview', foreign_keys=[system_overview_id], uselist=False, cascade="all")
    reason_order_id = Column(types.Integer, ForeignKey('reason_order.rid', use_alter=True))
    reason_order = relationship('ReasonOrder', foreign_keys=[reason_order_id], uselist=False, cascade="all")
    objectives_id = Column(types.Integer, ForeignKey('objectives.rid', use_alter=True))
    objectives = relationship('Objectives', foreign_keys=[objectives_id], uselist=False, cascade="all")
    contract_aspects_id = Column(types.Integer, ForeignKey('contract_aspects.rid', use_alter=True))
    contract_aspects = relationship('ContractAspects', foreign_keys=[contract_aspects_id], uselist=False, cascade="all")
    sample_spec_id = Column(types.Integer, ForeignKey('sample_spec.rid', use_alter=True))
    sample_spec = relationship('SampleSpec', foreign_keys=[sample_spec_id], uselist=False, cascade="all")
    variant_spec_id = Column(types.Integer, ForeignKey('variant_spec.rid', use_alter=True))
    variant_spec = relationship('VariantSpec', foreign_keys=[variant_spec_id], uselist=False, cascade="all")
    demarcation_other_projects_id = Column(types.Integer, ForeignKey('demarcation_other_projects.rid', use_alter=True))
    demarcation_other_projects = relationship('DemarcationOtherProjects', foreign_keys=[demarcation_other_projects_id], uselist=False, cascade="all")
    parallel_designs_id = Column(types.Integer, ForeignKey('parallel_designs.rid', use_alter=True))
    parallel_designs = relationship('ParallelDesigns', foreign_keys=[parallel_designs_id], uselist=False, cascade="all")
    integration_capability_id = Column(types.Integer, ForeignKey('integration_capability.rid', use_alter=True))
    integration_capability = relationship('IntegrationCapability', foreign_keys=[integration_capability_id], uselist=False, cascade="all")
    acceptance_cond_id = Column(types.Integer, ForeignKey('acceptance_cond.rid', use_alter=True))
    acceptance_cond = relationship('AcceptanceCond', foreign_keys=[acceptance_cond_id], uselist=False, cascade="all")
    project_schedule_id = Column(types.Integer, ForeignKey('project_schedule.rid', use_alter=True))
    project_schedule = relationship('ProjectSchedule', foreign_keys=[project_schedule_id], uselist=False, cascade="all")
    purchasing_cond_id = Column(types.Integer, ForeignKey('purchasing_cond.rid', use_alter=True))
    purchasing_cond = relationship('PurchasingCond', foreign_keys=[purchasing_cond_id], uselist=False, cascade="all")
    protocols_id = Column(types.Integer, ForeignKey('protocols.rid', use_alter=True))
    protocols = relationship('Protocols', foreign_keys=[protocols_id], uselist=False, cascade="all")
    dir_hand_over_doc_data_id = Column(types.Integer, ForeignKey('dir_hand_over_doc_data.rid', use_alter=True))
    dir_hand_over_doc_data = relationship('DirHandOverDocData', foreign_keys=[dir_hand_over_doc_data_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class Project(Base):

    __tablename__ = "project"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "Desc": "_desc",
        "Companies": "companies",
        "GeneralProjectData": "general_project_data",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    companies_id = Column(types.Integer, ForeignKey('companies.rid', use_alter=True))
    companies = relationship('Companies', foreign_keys=[companies_id], uselist=False, cascade="all")
    general_project_data_id = Column(types.Integer, ForeignKey('general_project_data.rid', use_alter=True))
    general_project_data = relationship('GeneralProjectData', foreign_keys=[general_project_data_id], uselist=False, cascade="all")

class ProjectData(Base):

    __tablename__ = "project_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "OverallProject": "overall_project",
        "Project": "project",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    overall_project_id = Column(types.Integer, ForeignKey('overall_project.rid', use_alter=True))
    overall_project = relationship('OverallProject', foreign_keys=[overall_project_id], uselist=False, cascade="all")
    project_id = Column(types.Integer, ForeignKey('project.rid', use_alter=True))
    project = relationship('Project', foreign_keys=[project_id], uselist=False, cascade="all")

class SwSystems(Base):

    __tablename__ = "sw_systems"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystem": "sw_system",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_system_id = Column(types.Integer, ForeignKey('sw_system.rid', use_alter=True))
    sw_system = relationship('SwSystem', foreign_keys=[sw_system_id], uselist=True, cascade="all")

class Requirements(Base):

    __tablename__ = "requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Requirement": "requirement",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    requirement_id = Column(types.Integer, ForeignKey('requirement.rid', use_alter=True))
    requirement = relationship('Requirement', foreign_keys=[requirement_id], uselist=True, cascade="all")

class FunctionOverview(Base):

    __tablename__ = "function_overview"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FreeInfo(Base):

    __tablename__ = "free_info"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class PrmRefs(Base):

    __tablename__ = "prm_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "PrmRef": "prm_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    prm_ref_id = Column(types.Integer, ForeignKey('prm_ref.rid', use_alter=True))
    prm_ref = relationship('PrmRef', foreign_keys=[prm_ref_id], uselist=True, cascade="all")

class KeyData(Base):

    __tablename__ = "key_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "FreeInfo": "free_info",
        "PrmRefs": "prm_refs",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    free_info_id = Column(types.Integer, ForeignKey('free_info.rid', use_alter=True))
    free_info = relationship('FreeInfo', foreign_keys=[free_info_id], uselist=False, cascade="all")
    prm_refs_id = Column(types.Integer, ForeignKey('prm_refs.rid', use_alter=True))
    prm_refs = relationship('PrmRefs', foreign_keys=[prm_refs_id], uselist=False, cascade="all")

class ProductDemarcation(Base):

    __tablename__ = "product_demarcation"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class PrmRef(Base):

    __tablename__ = "prm_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SimilarProducts(Base):

    __tablename__ = "similar_products"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class OperatingEnv(Base):

    __tablename__ = "operating_env"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class UsefulLifePrms(Base):

    __tablename__ = "useful_life_prms"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Availability": "availability",
        "LifeTime": "life_time",
        "OperatingTime": "operating_time",
        "Prm": "prm",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    availability_id = Column(types.Integer, ForeignKey('availability.rid', use_alter=True))
    availability = relationship('Availability', foreign_keys=[availability_id], uselist=True, cascade="all")
    life_time_id = Column(types.Integer, ForeignKey('life_time.rid', use_alter=True))
    life_time = relationship('LifeTime', foreign_keys=[life_time_id], uselist=True, cascade="all")
    operating_time_id = Column(types.Integer, ForeignKey('operating_time.rid', use_alter=True))
    operating_time = relationship('OperatingTime', foreign_keys=[operating_time_id], uselist=True, cascade="all")
    prm_id = Column(types.Integer, ForeignKey('prm.rid', use_alter=True))
    prm = relationship('Prm', foreign_keys=[prm_id], uselist=True, cascade="all")

class Ncoi3(Base):

    __tablename__ = "ncoi_3"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "MsrQueryP2": "msr_query_p_2",
        "Topic2": "topic_2",
        "MsrQueryTopic2": "msr_query_topic_2",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    msr_query_p_2_id = Column(types.Integer, ForeignKey('msr_query_p_2.rid', use_alter=True))
    msr_query_p_2 = relationship('MsrQueryP2', foreign_keys=[msr_query_p_2_id], uselist=True, cascade="all")
    topic_2_id = Column(types.Integer, ForeignKey('topic_2.rid', use_alter=True))
    topic_2 = relationship('Topic2', foreign_keys=[topic_2_id], uselist=True, cascade="all")
    msr_query_topic_2_id = Column(types.Integer, ForeignKey('msr_query_topic_2.rid', use_alter=True))
    msr_query_topic_2 = relationship('MsrQueryTopic2', foreign_keys=[msr_query_topic_2_id], uselist=True, cascade="all")

class ReliabilityPrms(Base):

    __tablename__ = "reliability_prms"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Mtbf": "mtbf",
        "Ppm": "ppm",
        "Prm": "prm",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    mtbf_id = Column(types.Integer, ForeignKey('mtbf.rid', use_alter=True))
    mtbf = relationship('Mtbf', foreign_keys=[mtbf_id], uselist=True, cascade="all")
    ppm_id = Column(types.Integer, ForeignKey('ppm.rid', use_alter=True))
    ppm = relationship('Ppm', foreign_keys=[ppm_id], uselist=True, cascade="all")
    prm_id = Column(types.Integer, ForeignKey('prm.rid', use_alter=True))
    prm = relationship('Prm', foreign_keys=[prm_id], uselist=True, cascade="all")

class UsefulLife(Base):

    __tablename__ = "useful_life"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "UsefulLifePrms": "useful_life_prms",
        "Ncoi3": "ncoi_3",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    useful_life_prms_id = Column(types.Integer, ForeignKey('useful_life_prms.rid', use_alter=True))
    useful_life_prms = relationship('UsefulLifePrms', foreign_keys=[useful_life_prms_id], uselist=False, cascade="all")
    ncoi_3_id = Column(types.Integer, ForeignKey('ncoi_3.rid', use_alter=True))
    ncoi_3 = relationship('Ncoi3', foreign_keys=[ncoi_3_id], uselist=False, cascade="all")

class Availability(Base):

    __tablename__ = "availability"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "PrmChar": "prm_char",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    prm_char_id = Column(types.Integer, ForeignKey('prm_char.rid', use_alter=True))
    prm_char = relationship('PrmChar', foreign_keys=[prm_char_id], uselist=True, cascade="all")

class LifeTime(Base):

    __tablename__ = "life_time"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "PrmChar": "prm_char",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    prm_char_id = Column(types.Integer, ForeignKey('prm_char.rid', use_alter=True))
    prm_char = relationship('PrmChar', foreign_keys=[prm_char_id], uselist=True, cascade="all")

class OperatingTime(Base):

    __tablename__ = "operating_time"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "PrmChar": "prm_char",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    prm_char_id = Column(types.Integer, ForeignKey('prm_char.rid', use_alter=True))
    prm_char = relationship('PrmChar', foreign_keys=[prm_char_id], uselist=True, cascade="all")

class Reliability(Base):

    __tablename__ = "reliability"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "ReliabilityPrms": "reliability_prms",
        "Ncoi3": "ncoi_3",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    reliability_prms_id = Column(types.Integer, ForeignKey('reliability_prms.rid', use_alter=True))
    reliability_prms = relationship('ReliabilityPrms', foreign_keys=[reliability_prms_id], uselist=False, cascade="all")
    ncoi_3_id = Column(types.Integer, ForeignKey('ncoi_3.rid', use_alter=True))
    ncoi_3 = relationship('Ncoi3', foreign_keys=[ncoi_3_id], uselist=False, cascade="all")

class GeneralHardware(Base):

    __tablename__ = "general_hardware"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "OperatingEnv": "operating_env",
        "UsefulLife": "useful_life",
        "Reliability": "reliability",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    operating_env_id = Column(types.Integer, ForeignKey('operating_env.rid', use_alter=True))
    operating_env = relationship('OperatingEnv', foreign_keys=[operating_env_id], uselist=False, cascade="all")
    useful_life_id = Column(types.Integer, ForeignKey('useful_life.rid', use_alter=True))
    useful_life = relationship('UsefulLife', foreign_keys=[useful_life_id], uselist=False, cascade="all")
    reliability_id = Column(types.Integer, ForeignKey('reliability.rid', use_alter=True))
    reliability = relationship('Reliability', foreign_keys=[reliability_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class NormativeReference(Base):

    __tablename__ = "normative_reference"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Mtbf(Base):

    __tablename__ = "mtbf"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "PrmChar": "prm_char",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    prm_char_id = Column(types.Integer, ForeignKey('prm_char.rid', use_alter=True))
    prm_char = relationship('PrmChar', foreign_keys=[prm_char_id], uselist=True, cascade="all")

class Ppm(Base):

    __tablename__ = "ppm"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "PrmChar": "prm_char",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    prm_char_id = Column(types.Integer, ForeignKey('prm_char.rid', use_alter=True))
    prm_char = relationship('PrmChar', foreign_keys=[prm_char_id], uselist=True, cascade="all")

class DataStructures(Base):

    __tablename__ = "data_structures"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class DataDesc(Base):

    __tablename__ = "data_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class RestrictionsByHardware(Base):

    __tablename__ = "restrictions_by_hardware"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class StandardSwModules(Base):

    __tablename__ = "standard_sw_modules"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class DesignRequirements(Base):

    __tablename__ = "design_requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "NormativeReference": "normative_reference",
        "RestrictionsByHardware": "restrictions_by_hardware",
        "StandardSwModules": "standard_sw_modules",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    normative_reference_id = Column(types.Integer, ForeignKey('normative_reference.rid', use_alter=True))
    normative_reference = relationship('NormativeReference', foreign_keys=[normative_reference_id], uselist=False, cascade="all")
    restrictions_by_hardware_id = Column(types.Integer, ForeignKey('restrictions_by_hardware.rid', use_alter=True))
    restrictions_by_hardware = relationship('RestrictionsByHardware', foreign_keys=[restrictions_by_hardware_id], uselist=False, cascade="all")
    standard_sw_modules_id = Column(types.Integer, ForeignKey('standard_sw_modules.rid', use_alter=True))
    standard_sw_modules = relationship('StandardSwModules', foreign_keys=[standard_sw_modules_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class BinaryCompatibility(Base):

    __tablename__ = "binary_compatibility"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class DataRequirements(Base):

    __tablename__ = "data_requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "DataStructures": "data_structures",
        "DataDesc": "data_desc",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    data_structures_id = Column(types.Integer, ForeignKey('data_structures.rid', use_alter=True))
    data_structures = relationship('DataStructures', foreign_keys=[data_structures_id], uselist=False, cascade="all")
    data_desc_id = Column(types.Integer, ForeignKey('data_desc.rid', use_alter=True))
    data_desc = relationship('DataDesc', foreign_keys=[data_desc_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class Extensibility(Base):

    __tablename__ = "extensibility"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Compatibility(Base):

    __tablename__ = "compatibility"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class GeneralSoftware(Base):

    __tablename__ = "general_software"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "DesignRequirements": "design_requirements",
        "DataRequirements": "data_requirements",
        "BinaryCompatibility": "binary_compatibility",
        "Extensibility": "extensibility",
        "Compatibility": "compatibility",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    design_requirements_id = Column(types.Integer, ForeignKey('design_requirements.rid', use_alter=True))
    design_requirements = relationship('DesignRequirements', foreign_keys=[design_requirements_id], uselist=False, cascade="all")
    data_requirements_id = Column(types.Integer, ForeignKey('data_requirements.rid', use_alter=True))
    data_requirements = relationship('DataRequirements', foreign_keys=[data_requirements_id], uselist=False, cascade="all")
    binary_compatibility_id = Column(types.Integer, ForeignKey('binary_compatibility.rid', use_alter=True))
    binary_compatibility = relationship('BinaryCompatibility', foreign_keys=[binary_compatibility_id], uselist=False, cascade="all")
    extensibility_id = Column(types.Integer, ForeignKey('extensibility.rid', use_alter=True))
    extensibility = relationship('Extensibility', foreign_keys=[extensibility_id], uselist=False, cascade="all")
    compatibility_id = Column(types.Integer, ForeignKey('compatibility.rid', use_alter=True))
    compatibility = relationship('Compatibility', foreign_keys=[compatibility_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class UserInterface(Base):

    __tablename__ = "user_interface"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class HardwareInterface(Base):

    __tablename__ = "hardware_interface"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class InternalInterfaces(Base):

    __tablename__ = "internal_interfaces"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class CommunicationInterface(Base):

    __tablename__ = "communication_interface"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FlashProgramming(Base):

    __tablename__ = "flash_programming"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class GeneralInterfaces(Base):

    __tablename__ = "general_interfaces"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "UserInterface": "user_interface",
        "HardwareInterface": "hardware_interface",
        "InternalInterfaces": "internal_interfaces",
        "CommunicationInterface": "communication_interface",
        "FlashProgramming": "flash_programming",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    user_interface_id = Column(types.Integer, ForeignKey('user_interface.rid', use_alter=True))
    user_interface = relationship('UserInterface', foreign_keys=[user_interface_id], uselist=False, cascade="all")
    hardware_interface_id = Column(types.Integer, ForeignKey('hardware_interface.rid', use_alter=True))
    hardware_interface = relationship('HardwareInterface', foreign_keys=[hardware_interface_id], uselist=False, cascade="all")
    internal_interfaces_id = Column(types.Integer, ForeignKey('internal_interfaces.rid', use_alter=True))
    internal_interfaces = relationship('InternalInterfaces', foreign_keys=[internal_interfaces_id], uselist=False, cascade="all")
    communication_interface_id = Column(types.Integer, ForeignKey('communication_interface.rid', use_alter=True))
    communication_interface = relationship('CommunicationInterface', foreign_keys=[communication_interface_id], uselist=False, cascade="all")
    flash_programming_id = Column(types.Integer, ForeignKey('flash_programming.rid', use_alter=True))
    flash_programming = relationship('FlashProgramming', foreign_keys=[flash_programming_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class Fmea(Base):

    __tablename__ = "fmea"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FailSaveConcept(Base):

    __tablename__ = "fail_save_concept"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class ReplacementValues(Base):

    __tablename__ = "replacement_values"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FailureMem(Base):

    __tablename__ = "failure_mem"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class SelfDiagnosis(Base):

    __tablename__ = "self_diagnosis"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FailureManagement(Base):

    __tablename__ = "failure_management"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Fmea": "fmea",
        "FailSaveConcept": "fail_save_concept",
        "ReplacementValues": "replacement_values",
        "FailureMem": "failure_mem",
        "SelfDiagnosis": "self_diagnosis",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    fmea_id = Column(types.Integer, ForeignKey('fmea.rid', use_alter=True))
    fmea = relationship('Fmea', foreign_keys=[fmea_id], uselist=False, cascade="all")
    fail_save_concept_id = Column(types.Integer, ForeignKey('fail_save_concept.rid', use_alter=True))
    fail_save_concept = relationship('FailSaveConcept', foreign_keys=[fail_save_concept_id], uselist=False, cascade="all")
    replacement_values_id = Column(types.Integer, ForeignKey('replacement_values.rid', use_alter=True))
    replacement_values = relationship('ReplacementValues', foreign_keys=[replacement_values_id], uselist=False, cascade="all")
    failure_mem_id = Column(types.Integer, ForeignKey('failure_mem.rid', use_alter=True))
    failure_mem = relationship('FailureMem', foreign_keys=[failure_mem_id], uselist=False, cascade="all")
    self_diagnosis_id = Column(types.Integer, ForeignKey('self_diagnosis.rid', use_alter=True))
    self_diagnosis = relationship('SelfDiagnosis', foreign_keys=[self_diagnosis_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class ResourceAllocation(Base):

    __tablename__ = "resource_allocation"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Calibration(Base):

    __tablename__ = "calibration"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Safety(Base):

    __tablename__ = "safety"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Quality(Base):

    __tablename__ = "quality"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class GeneralCond(Base):

    __tablename__ = "general_cond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class AddDesignDoc(Base):

    __tablename__ = "add_design_doc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class DevelopmentProcessSpec(Base):

    __tablename__ = "development_process_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class GeneralProductData1(Base):

    __tablename__ = "general_product_data_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "ProductDesc": "product_desc",
        "FunctionOverview": "function_overview",
        "KeyData": "key_data",
        "ProductDemarcation": "product_demarcation",
        "SimilarProducts": "similar_products",
        "GeneralHardware": "general_hardware",
        "GeneralSoftware": "general_software",
        "GeneralInterfaces": "general_interfaces",
        "FailureManagement": "failure_management",
        "ResourceAllocation": "resource_allocation",
        "Calibration": "calibration",
        "Safety": "safety",
        "Quality": "quality",
        "Maintenance": "maintenance",
        "GeneralCond": "general_cond",
        "AddDesignDoc": "add_design_doc",
        "DevelopmentProcessSpec": "development_process_spec",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    product_desc_id = Column(types.Integer, ForeignKey('product_desc.rid', use_alter=True))
    product_desc = relationship('ProductDesc', foreign_keys=[product_desc_id], uselist=False, cascade="all")
    function_overview_id = Column(types.Integer, ForeignKey('function_overview.rid', use_alter=True))
    function_overview = relationship('FunctionOverview', foreign_keys=[function_overview_id], uselist=False, cascade="all")
    key_data_id = Column(types.Integer, ForeignKey('key_data.rid', use_alter=True))
    key_data = relationship('KeyData', foreign_keys=[key_data_id], uselist=False, cascade="all")
    product_demarcation_id = Column(types.Integer, ForeignKey('product_demarcation.rid', use_alter=True))
    product_demarcation = relationship('ProductDemarcation', foreign_keys=[product_demarcation_id], uselist=False, cascade="all")
    similar_products_id = Column(types.Integer, ForeignKey('similar_products.rid', use_alter=True))
    similar_products = relationship('SimilarProducts', foreign_keys=[similar_products_id], uselist=False, cascade="all")
    general_hardware_id = Column(types.Integer, ForeignKey('general_hardware.rid', use_alter=True))
    general_hardware = relationship('GeneralHardware', foreign_keys=[general_hardware_id], uselist=False, cascade="all")
    general_software_id = Column(types.Integer, ForeignKey('general_software.rid', use_alter=True))
    general_software = relationship('GeneralSoftware', foreign_keys=[general_software_id], uselist=False, cascade="all")
    general_interfaces_id = Column(types.Integer, ForeignKey('general_interfaces.rid', use_alter=True))
    general_interfaces = relationship('GeneralInterfaces', foreign_keys=[general_interfaces_id], uselist=False, cascade="all")
    failure_management_id = Column(types.Integer, ForeignKey('failure_management.rid', use_alter=True))
    failure_management = relationship('FailureManagement', foreign_keys=[failure_management_id], uselist=False, cascade="all")
    resource_allocation_id = Column(types.Integer, ForeignKey('resource_allocation.rid', use_alter=True))
    resource_allocation = relationship('ResourceAllocation', foreign_keys=[resource_allocation_id], uselist=False, cascade="all")
    calibration_id = Column(types.Integer, ForeignKey('calibration.rid', use_alter=True))
    calibration = relationship('Calibration', foreign_keys=[calibration_id], uselist=False, cascade="all")
    safety_id = Column(types.Integer, ForeignKey('safety.rid', use_alter=True))
    safety = relationship('Safety', foreign_keys=[safety_id], uselist=False, cascade="all")
    quality_id = Column(types.Integer, ForeignKey('quality.rid', use_alter=True))
    quality = relationship('Quality', foreign_keys=[quality_id], uselist=False, cascade="all")
    maintenance_id = Column(types.Integer, ForeignKey('maintenance.rid', use_alter=True))
    maintenance = relationship('Maintenance', foreign_keys=[maintenance_id], uselist=False, cascade="all")
    general_cond_id = Column(types.Integer, ForeignKey('general_cond.rid', use_alter=True))
    general_cond = relationship('GeneralCond', foreign_keys=[general_cond_id], uselist=False, cascade="all")
    add_design_doc_id = Column(types.Integer, ForeignKey('add_design_doc.rid', use_alter=True))
    add_design_doc = relationship('AddDesignDoc', foreign_keys=[add_design_doc_id], uselist=False, cascade="all")
    development_process_spec_id = Column(types.Integer, ForeignKey('development_process_spec.rid', use_alter=True))
    development_process_spec = relationship('DevelopmentProcessSpec', foreign_keys=[development_process_spec_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class RequirementSpec(Base):

    __tablename__ = "requirement_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "Requirements": "requirements",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    requirements_id = Column(types.Integer, ForeignKey('requirements.rid', use_alter=True))
    requirements = relationship('Requirements', foreign_keys=[requirements_id], uselist=False, cascade="all")

class Monitoring(Base):

    __tablename__ = "monitoring"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class Diagnosis(Base):

    __tablename__ = "diagnosis"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class RequirementBody(Base):

    __tablename__ = "requirement_body"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class CriticalAspects(Base):

    __tablename__ = "critical_aspects"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class TechnicalAspects(Base):

    __tablename__ = "technical_aspects"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class RealtimeRequirements(Base):

    __tablename__ = "realtime_requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class Risks(Base):

    __tablename__ = "risks"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class RequirementsDependency(Base):

    __tablename__ = "requirements_dependency"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class AddInfo(Base):

    __tablename__ = "add_info"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class Requirement(Base):

    __tablename__ = "requirement"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "RequirementBody": "requirement_body",
        "CriticalAspects": "critical_aspects",
        "TechnicalAspects": "technical_aspects",
        "RealtimeRequirements": "realtime_requirements",
        "Risks": "risks",
        "RequirementsDependency": "requirements_dependency",
        "AddInfo": "add_info",
        "Requirement": "requirement",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    requirement_body_id = Column(types.Integer, ForeignKey('requirement_body.rid', use_alter=True))
    requirement_body = relationship('RequirementBody', foreign_keys=[requirement_body_id], uselist=False, cascade="all")
    critical_aspects_id = Column(types.Integer, ForeignKey('critical_aspects.rid', use_alter=True))
    critical_aspects = relationship('CriticalAspects', foreign_keys=[critical_aspects_id], uselist=False, cascade="all")
    technical_aspects_id = Column(types.Integer, ForeignKey('technical_aspects.rid', use_alter=True))
    technical_aspects = relationship('TechnicalAspects', foreign_keys=[technical_aspects_id], uselist=False, cascade="all")
    realtime_requirements_id = Column(types.Integer, ForeignKey('realtime_requirements.rid', use_alter=True))
    realtime_requirements = relationship('RealtimeRequirements', foreign_keys=[realtime_requirements_id], uselist=False, cascade="all")
    risks_id = Column(types.Integer, ForeignKey('risks.rid', use_alter=True))
    risks = relationship('Risks', foreign_keys=[risks_id], uselist=False, cascade="all")
    requirements_dependency_id = Column(types.Integer, ForeignKey('requirements_dependency.rid', use_alter=True))
    requirements_dependency = relationship('RequirementsDependency', foreign_keys=[requirements_dependency_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")
    requirement_id = Column(types.Integer, ForeignKey('requirement.rid', use_alter=True))
    requirement = relationship('Requirement', foreign_keys=[requirement_id], uselist=True, cascade="all")

class Communication(Base):

    __tablename__ = "communication"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class OperationalRequirements(Base):

    __tablename__ = "operational_requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class FunctionalRequirements(Base):

    __tablename__ = "functional_requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "RequirementSpec": "requirement_spec",
        "Monitoring": "monitoring",
        "Diagnosis": "diagnosis",
        "Communication": "communication",
        "OperationalRequirements": "operational_requirements",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    requirement_spec_id = Column(types.Integer, ForeignKey('requirement_spec.rid', use_alter=True))
    requirement_spec = relationship('RequirementSpec', foreign_keys=[requirement_spec_id], uselist=False, cascade="all")
    monitoring_id = Column(types.Integer, ForeignKey('monitoring.rid', use_alter=True))
    monitoring = relationship('Monitoring', foreign_keys=[monitoring_id], uselist=False, cascade="all")
    diagnosis_id = Column(types.Integer, ForeignKey('diagnosis.rid', use_alter=True))
    diagnosis = relationship('Diagnosis', foreign_keys=[diagnosis_id], uselist=False, cascade="all")
    communication_id = Column(types.Integer, ForeignKey('communication.rid', use_alter=True))
    communication = relationship('Communication', foreign_keys=[communication_id], uselist=False, cascade="all")
    operational_requirements_id = Column(types.Integer, ForeignKey('operational_requirements.rid', use_alter=True))
    operational_requirements = relationship('OperationalRequirements', foreign_keys=[operational_requirements_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class GeneralRequirements(Base):

    __tablename__ = "general_requirements"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "GeneralProductData1": "general_product_data_1",
        "FunctionalRequirements": "functional_requirements",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    general_product_data_1_id = Column(types.Integer, ForeignKey('general_product_data_1.rid', use_alter=True))
    general_product_data_1 = relationship('GeneralProductData1', foreign_keys=[general_product_data_1_id], uselist=False, cascade="all")
    functional_requirements_id = Column(types.Integer, ForeignKey('functional_requirements.rid', use_alter=True))
    functional_requirements = relationship('FunctionalRequirements', foreign_keys=[functional_requirements_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class SwMcInterfaceSpec(Base):

    __tablename__ = "sw_mc_interface_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwMcInterface": "sw_mc_interface",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_mc_interface_id = Column(types.Integer, ForeignKey('sw_mc_interface.rid', use_alter=True))
    sw_mc_interface = relationship('SwMcInterface', foreign_keys=[sw_mc_interface_id], uselist=True, cascade="all")

class Overview(Base):

    __tablename__ = "overview"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class SwTestSpec(Base):

    __tablename__ = "sw_test_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class SwTasks(Base):

    __tablename__ = "sw_tasks"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwTask": "sw_task",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_task_id = Column(types.Integer, ForeignKey('sw_task.rid', use_alter=True))
    sw_task = relationship('SwTask', foreign_keys=[sw_task_id], uselist=True, cascade="all")

class SwTaskSpec(Base):

    __tablename__ = "sw_task_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwTasks": "sw_tasks",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_tasks_id = Column(types.Integer, ForeignKey('sw_tasks.rid', use_alter=True))
    sw_tasks = relationship('SwTasks', foreign_keys=[sw_tasks_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class InterruptSpec(Base):

    __tablename__ = "interrupt_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class SwCseCode(Base):

    __tablename__ = "sw_cse_code"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCseCodeFactor(Base):

    __tablename__ = "sw_cse_code_factor"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRefreshTiming(Base):

    __tablename__ = "sw_refresh_timing"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCseCode": "sw_cse_code",
        "SwCseCodeFactor": "sw_cse_code_factor",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_cse_code_id = Column(types.Integer, ForeignKey('sw_cse_code.rid', use_alter=True))
    sw_cse_code = relationship('SwCseCode', foreign_keys=[sw_cse_code_id], uselist=False, cascade="all")
    sw_cse_code_factor_id = Column(types.Integer, ForeignKey('sw_cse_code_factor.rid', use_alter=True))
    sw_cse_code_factor = relationship('SwCseCodeFactor', foreign_keys=[sw_cse_code_factor_id], uselist=False, cascade="all")

class SwTask(Base):

    __tablename__ = "sw_task"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwRefreshTiming": "sw_refresh_timing",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_refresh_timing_id = Column(types.Integer, ForeignKey('sw_refresh_timing.rid', use_alter=True))
    sw_refresh_timing = relationship('SwRefreshTiming', foreign_keys=[sw_refresh_timing_id], uselist=False, cascade="all")

class TimeDependency(Base):

    __tablename__ = "time_dependency"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class SwArchitecture(Base):

    __tablename__ = "sw_architecture"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "Overview": "overview",
        "SwTaskSpec": "sw_task_spec",
        "InterruptSpec": "interrupt_spec",
        "TimeDependency": "time_dependency",
        "AddSpec": "add_spec",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    overview_id = Column(types.Integer, ForeignKey('overview.rid', use_alter=True))
    overview = relationship('Overview', foreign_keys=[overview_id], uselist=False, cascade="all")
    sw_task_spec_id = Column(types.Integer, ForeignKey('sw_task_spec.rid', use_alter=True))
    sw_task_spec = relationship('SwTaskSpec', foreign_keys=[sw_task_spec_id], uselist=False, cascade="all")
    interrupt_spec_id = Column(types.Integer, ForeignKey('interrupt_spec.rid', use_alter=True))
    interrupt_spec = relationship('InterruptSpec', foreign_keys=[interrupt_spec_id], uselist=False, cascade="all")
    time_dependency_id = Column(types.Integer, ForeignKey('time_dependency.rid', use_alter=True))
    time_dependency = relationship('TimeDependency', foreign_keys=[time_dependency_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class SwUnits(Base):

    __tablename__ = "sw_units"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwUnit": "sw_unit",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_unit_id = Column(types.Integer, ForeignKey('sw_unit.rid', use_alter=True))
    sw_unit = relationship('SwUnit', foreign_keys=[sw_unit_id], uselist=True, cascade="all")

class SwComponents(Base):

    __tablename__ = "sw_components"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Chapter": "chapter",
        "SwClass": "sw_class",
        "SwFeature": "sw_feature",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    sw_class_id = Column(types.Integer, ForeignKey('sw_class.rid', use_alter=True))
    sw_class = relationship('SwClass', foreign_keys=[sw_class_id], uselist=True, cascade="all")
    sw_feature_id = Column(types.Integer, ForeignKey('sw_feature.rid', use_alter=True))
    sw_feature = relationship('SwFeature', foreign_keys=[sw_feature_id], uselist=True, cascade="all")

class SwTemplates(Base):

    __tablename__ = "sw_templates"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwTemplate": "sw_template",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_template_id = Column(types.Integer, ForeignKey('sw_template.rid', use_alter=True))
    sw_template = relationship('SwTemplate', foreign_keys=[sw_template_id], uselist=True, cascade="all")

class SwUnitDisplay(Base):

    __tablename__ = "sw_unit_display"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": "sup",
        "Sub": "sub",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sup_id = Column(types.Integer, ForeignKey('sup.rid', use_alter=True))
    sup = relationship('Sup', foreign_keys=[sup_id], uselist=True, cascade="all")
    sub_id = Column(types.Integer, ForeignKey('sub.rid', use_alter=True))
    sub = relationship('Sub', foreign_keys=[sub_id], uselist=True, cascade="all")

class SwUnitGradient(Base):

    __tablename__ = "sw_unit_gradient"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SiUnit(Base):

    __tablename__ = "si_unit"
    ATTRIBUTES = {
        "LENGTH-EXPO": "length_expo",
        "TIME-EXPO": "time_expo",
        "MASS-EXPO": "mass_expo",
        "ELECTRIC-CURRENT-EXPO": "electric_current_expo",
        "THERMODYNAMIC-TEMPERATURE-EXPO": "thermodynamic_temperature_expo",
        "LUMINOUS-INTENSITY-EXPO": "luminous_intensity_expo",
        "AMOUNT-OF-SUBSTANCE-EXPO": "amount_of_substance_expo",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    length_expo = StdString()
    time_expo = StdString()
    mass_expo = StdString()
    electric_current_expo = StdString()
    thermodynamic_temperature_expo = StdString()
    luminous_intensity_expo = StdString()
    amount_of_substance_expo = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwUnitOffset(Base):

    __tablename__ = "sw_unit_offset"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwUnitConversionMethod(Base):

    __tablename__ = "sw_unit_conversion_method"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUnitGradient": "sw_unit_gradient",
        "SwUnitOffset": "sw_unit_offset",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_unit_gradient_id = Column(types.Integer, ForeignKey('sw_unit_gradient.rid', use_alter=True))
    sw_unit_gradient = relationship('SwUnitGradient', foreign_keys=[sw_unit_gradient_id], uselist=False, cascade="all")
    sw_unit_offset_id = Column(types.Integer, ForeignKey('sw_unit_offset.rid', use_alter=True))
    sw_unit_offset = relationship('SwUnitOffset', foreign_keys=[sw_unit_offset_id], uselist=False, cascade="all")

class SwUnitRef(Base):

    __tablename__ = "sw_unit_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwUnit(Base):

    __tablename__ = "sw_unit"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwUnitDisplay": "sw_unit_display",
        "SwUnitConversionMethod": "sw_unit_conversion_method",
        "SiUnit": "si_unit",
        "SwUnitRef": "sw_unit_ref",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_unit_display_id = Column(types.Integer, ForeignKey('sw_unit_display.rid', use_alter=True))
    sw_unit_display = relationship('SwUnitDisplay', foreign_keys=[sw_unit_display_id], uselist=False, cascade="all")
    sw_unit_conversion_method_id = Column(types.Integer, ForeignKey('sw_unit_conversion_method.rid', use_alter=True))
    sw_unit_conversion_method = relationship('SwUnitConversionMethod', foreign_keys=[sw_unit_conversion_method_id], uselist=False, cascade="all")
    si_unit_id = Column(types.Integer, ForeignKey('si_unit.rid', use_alter=True))
    si_unit = relationship('SiUnit', foreign_keys=[si_unit_id], uselist=False, cascade="all")
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwVariables(Base):

    __tablename__ = "sw_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwVariable": "sw_variable",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_variable_id = Column(types.Integer, ForeignKey('sw_variable.rid', use_alter=True))
    sw_variable = relationship('SwVariable', foreign_keys=[sw_variable_id], uselist=True, cascade="all")

class Annotations(Base):

    __tablename__ = "annotations"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Annotation": "annotation",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    annotation_id = Column(types.Integer, ForeignKey('annotation.rid', use_alter=True))
    annotation = relationship('Annotation', foreign_keys=[annotation_id], uselist=True, cascade="all")

class SwAddrMethodRef(Base):

    __tablename__ = "sw_addr_method_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAliasName(Base):

    __tablename__ = "sw_alias_name"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class AnnotationOrigin(Base):

    __tablename__ = "annotation_origin"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class AnnotationText(Base):

    __tablename__ = "annotation_text"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")

class Annotation(Base):

    __tablename__ = "annotation"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "AnnotationOrigin": "annotation_origin",
        "AnnotationText": "annotation_text",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    annotation_origin_id = Column(types.Integer, ForeignKey('annotation_origin.rid', use_alter=True))
    annotation_origin = relationship('AnnotationOrigin', foreign_keys=[annotation_origin_id], uselist=False, cascade="all")
    annotation_text_id = Column(types.Integer, ForeignKey('annotation_text.rid', use_alter=True))
    annotation_text = relationship('AnnotationText', foreign_keys=[annotation_text_id], uselist=False, cascade="all")

class SwBaseTypeRef(Base):

    __tablename__ = "sw_base_type_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class BitPosition(Base):

    __tablename__ = "bit_position"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class NumberOfBits(Base):

    __tablename__ = "number_of_bits"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwBitRepresentation(Base):

    __tablename__ = "sw_bit_representation"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "BitPosition": "bit_position",
        "NumberOfBits": "number_of_bits",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    bit_position_id = Column(types.Integer, ForeignKey('bit_position.rid', use_alter=True))
    bit_position = relationship('BitPosition', foreign_keys=[bit_position_id], uselist=False, cascade="all")
    number_of_bits_id = Column(types.Integer, ForeignKey('number_of_bits.rid', use_alter=True))
    number_of_bits = relationship('NumberOfBits', foreign_keys=[number_of_bits_id], uselist=False, cascade="all")

class SwCalibrationAccess(Base):

    __tablename__ = "sw_calibration_access"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCalprmAxisSet(Base):

    __tablename__ = "sw_calprm_axis_set"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmAxis": "sw_calprm_axis",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_axis_id = Column(types.Integer, ForeignKey('sw_calprm_axis.rid', use_alter=True))
    sw_calprm_axis = relationship('SwCalprmAxis', foreign_keys=[sw_calprm_axis_id], uselist=True, cascade="all")

class SwCalprmNoEffectValue(Base):

    __tablename__ = "sw_calprm_no_effect_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwTemplateRef(Base):

    __tablename__ = "sw_template_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAxisIndex(Base):

    __tablename__ = "sw_axis_index"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVariableRefs(Base):

    __tablename__ = "sw_variable_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")

class SwCalprmRef(Base):

    __tablename__ = "sw_calprm_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCompuMethodRef(Base):

    __tablename__ = "sw_compu_method_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVariableRef(Base):

    __tablename__ = "sw_variable_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMaxAxisPoints(Base):

    __tablename__ = "sw_max_axis_points"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwSystemconstPhysRef": "sw_systemconst_phys_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_systemconst_phys_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_phys_ref.rid', use_alter=True))
    sw_systemconst_phys_ref = relationship('SwSystemconstPhysRef', foreign_keys=[sw_systemconst_phys_ref_id], uselist=True, cascade="all")

class SwMinAxisPoints(Base):

    __tablename__ = "sw_min_axis_points"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwSystemconstPhysRef": "sw_systemconst_phys_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_systemconst_phys_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_phys_ref.rid', use_alter=True))
    sw_systemconst_phys_ref = relationship('SwSystemconstPhysRef', foreign_keys=[sw_systemconst_phys_ref_id], uselist=True, cascade="all")

class SwSystemconstCodedRef(Base):

    __tablename__ = "sw_systemconst_coded_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwSystemconstPhysRef(Base):

    __tablename__ = "sw_systemconst_phys_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwDataConstrRef(Base):

    __tablename__ = "sw_data_constr_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAxisTypeRef(Base):

    __tablename__ = "sw_axis_type_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwNumberOfAxisPoints(Base):

    __tablename__ = "sw_number_of_axis_points"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwSystemconstPhysRef": "sw_systemconst_phys_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_systemconst_phys_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_phys_ref.rid', use_alter=True))
    sw_systemconst_phys_ref = relationship('SwSystemconstPhysRef', foreign_keys=[sw_systemconst_phys_ref_id], uselist=True, cascade="all")

class SwGenericAxisParams(Base):

    __tablename__ = "sw_generic_axis_params"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwGenericAxisParam": "sw_generic_axis_param",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_generic_axis_param_id = Column(types.Integer, ForeignKey('sw_generic_axis_param.rid', use_alter=True))
    sw_generic_axis_param = relationship('SwGenericAxisParam', foreign_keys=[sw_generic_axis_param_id], uselist=True, cascade="all")

class SwValuesPhys(Base):

    __tablename__ = "sw_values_phys"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "Vt": "vt",
        "Vh": "vh",
        "V": "v",
        "Vg": "vg",
        "SwInstanceRef": "sw_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=True, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")
    vg_id = Column(types.Integer, ForeignKey('vg.rid', use_alter=True))
    vg = relationship('Vg', foreign_keys=[vg_id], uselist=True, cascade="all")
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=True, cascade="all")

class SwValuesCoded(Base):

    __tablename__ = "sw_values_coded"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "Vt": "vt",
        "Vh": "vh",
        "V": "v",
        "Vg": "vg",
        "SwInstanceRef": "sw_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=True, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")
    vg_id = Column(types.Integer, ForeignKey('vg.rid', use_alter=True))
    vg = relationship('Vg', foreign_keys=[vg_id], uselist=True, cascade="all")
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=True, cascade="all")

class SwGenericAxisParamTypeRef(Base):

    __tablename__ = "sw_generic_axis_param_type_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwGenericAxisParam(Base):

    __tablename__ = "sw_generic_axis_param"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwGenericAxisParamTypeRef": "sw_generic_axis_param_type_ref",
        "Vf": "vf",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_generic_axis_param_type_ref_id = Column(types.Integer, ForeignKey('sw_generic_axis_param_type_ref.rid', use_alter=True))
    sw_generic_axis_param_type_ref = relationship('SwGenericAxisParamTypeRef', foreign_keys=[sw_generic_axis_param_type_ref_id], uselist=False, cascade="all")
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")

class Vf(Base):

    __tablename__ = "vf"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwSystemconstPhysRef": "sw_systemconst_phys_ref",
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_systemconst_phys_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_phys_ref.rid', use_alter=True))
    sw_systemconst_phys_ref = relationship('SwSystemconstPhysRef', foreign_keys=[sw_systemconst_phys_ref_id], uselist=True, cascade="all")

class SwAxisGeneric(Base):

    __tablename__ = "sw_axis_generic"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisTypeRef": "sw_axis_type_ref",
        "SwNumberOfAxisPoints": "sw_number_of_axis_points",
        "SwGenericAxisParams": "sw_generic_axis_params",
        "SwValuesPhys": "sw_values_phys",
        "SwValuesCoded": "sw_values_coded",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_axis_type_ref_id = Column(types.Integer, ForeignKey('sw_axis_type_ref.rid', use_alter=True))
    sw_axis_type_ref = relationship('SwAxisTypeRef', foreign_keys=[sw_axis_type_ref_id], uselist=False, cascade="all")
    sw_number_of_axis_points_id = Column(types.Integer, ForeignKey('sw_number_of_axis_points.rid', use_alter=True))
    sw_number_of_axis_points = relationship('SwNumberOfAxisPoints', foreign_keys=[sw_number_of_axis_points_id], uselist=False, cascade="all")
    sw_generic_axis_params_id = Column(types.Integer, ForeignKey('sw_generic_axis_params.rid', use_alter=True))
    sw_generic_axis_params = relationship('SwGenericAxisParams', foreign_keys=[sw_generic_axis_params_id], uselist=False, cascade="all")
    sw_values_phys_id = Column(types.Integer, ForeignKey('sw_values_phys.rid', use_alter=True))
    sw_values_phys = relationship('SwValuesPhys', foreign_keys=[sw_values_phys_id], uselist=False, cascade="all")
    sw_values_coded_id = Column(types.Integer, ForeignKey('sw_values_coded.rid', use_alter=True))
    sw_values_coded = relationship('SwValuesCoded', foreign_keys=[sw_values_coded_id], uselist=False, cascade="all")

class Vt(Base):

    __tablename__ = "vt"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Vh(Base):

    __tablename__ = "vh"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class V(Base):

    __tablename__ = "v"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    content = StdDecimal()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Vg(Base):

    __tablename__ = "vg"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "Vf": "vf",
        "Vt": "vt",
        "Vh": "vh",
        "V": "v",
        "Vg": "vg",
        "SwInstanceRef": "sw_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=True, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")
    vg_id = Column(types.Integer, ForeignKey('vg.rid', use_alter=True))
    vg = relationship('Vg', foreign_keys=[vg_id], uselist=True, cascade="all")
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=True, cascade="all")

class SwInstanceRef(Base):

    __tablename__ = "sw_instance_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAxisIndividual(Base):

    __tablename__ = "sw_axis_individual"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRefs": "sw_variable_refs",
        "SwCompuMethodRef": "sw_compu_method_ref",
        "SwUnitRef": "sw_unit_ref",
        "SwBitRepresentation": "sw_bit_representation",
        "SwMaxAxisPoints": "sw_max_axis_points",
        "SwMinAxisPoints": "sw_min_axis_points",
        "SwDataConstrRef": "sw_data_constr_ref",
        "SwAxisGeneric": "sw_axis_generic",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_refs_id = Column(types.Integer, ForeignKey('sw_variable_refs.rid', use_alter=True))
    sw_variable_refs = relationship('SwVariableRefs', foreign_keys=[sw_variable_refs_id], uselist=False, cascade="all")
    sw_compu_method_ref_id = Column(types.Integer, ForeignKey('sw_compu_method_ref.rid', use_alter=True))
    sw_compu_method_ref = relationship('SwCompuMethodRef', foreign_keys=[sw_compu_method_ref_id], uselist=False, cascade="all")
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    sw_bit_representation_id = Column(types.Integer, ForeignKey('sw_bit_representation.rid', use_alter=True))
    sw_bit_representation = relationship('SwBitRepresentation', foreign_keys=[sw_bit_representation_id], uselist=False, cascade="all")
    sw_max_axis_points_id = Column(types.Integer, ForeignKey('sw_max_axis_points.rid', use_alter=True))
    sw_max_axis_points = relationship('SwMaxAxisPoints', foreign_keys=[sw_max_axis_points_id], uselist=False, cascade="all")
    sw_min_axis_points_id = Column(types.Integer, ForeignKey('sw_min_axis_points.rid', use_alter=True))
    sw_min_axis_points = relationship('SwMinAxisPoints', foreign_keys=[sw_min_axis_points_id], uselist=False, cascade="all")
    sw_data_constr_ref_id = Column(types.Integer, ForeignKey('sw_data_constr_ref.rid', use_alter=True))
    sw_data_constr_ref = relationship('SwDataConstrRef', foreign_keys=[sw_data_constr_ref_id], uselist=False, cascade="all")
    sw_axis_generic_id = Column(types.Integer, ForeignKey('sw_axis_generic.rid', use_alter=True))
    sw_axis_generic = relationship('SwAxisGeneric', foreign_keys=[sw_axis_generic_id], uselist=False, cascade="all")

class SwDisplayFormat(Base):

    __tablename__ = "sw_display_format"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAxisGrouped(Base):

    __tablename__ = "sw_axis_grouped"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisIndex": "sw_axis_index",
        "SwCalprmRef": "sw_calprm_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_axis_index_id = Column(types.Integer, ForeignKey('sw_axis_index.rid', use_alter=True))
    sw_axis_index = relationship('SwAxisIndex', foreign_keys=[sw_axis_index_id], uselist=False, cascade="all")
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=False, cascade="all")

class SwCalprmAxis(Base):

    __tablename__ = "sw_calprm_axis"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisIndex": "sw_axis_index",
        "SwAxisIndividual": "sw_axis_individual",
        "SwAxisGrouped": "sw_axis_grouped",
        "SwCalibrationAccess": "sw_calibration_access",
        "SwDisplayFormat": "sw_display_format",
        "SwBaseTypeRef": "sw_base_type_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_axis_index_id = Column(types.Integer, ForeignKey('sw_axis_index.rid', use_alter=True))
    sw_axis_index = relationship('SwAxisIndex', foreign_keys=[sw_axis_index_id], uselist=False, cascade="all")
    sw_axis_individual_id = Column(types.Integer, ForeignKey('sw_axis_individual.rid', use_alter=True))
    sw_axis_individual = relationship('SwAxisIndividual', foreign_keys=[sw_axis_individual_id], uselist=False, cascade="all")
    sw_axis_grouped_id = Column(types.Integer, ForeignKey('sw_axis_grouped.rid', use_alter=True))
    sw_axis_grouped = relationship('SwAxisGrouped', foreign_keys=[sw_axis_grouped_id], uselist=False, cascade="all")
    sw_calibration_access_id = Column(types.Integer, ForeignKey('sw_calibration_access.rid', use_alter=True))
    sw_calibration_access = relationship('SwCalibrationAccess', foreign_keys=[sw_calibration_access_id], uselist=False, cascade="all")
    sw_display_format_id = Column(types.Integer, ForeignKey('sw_display_format.rid', use_alter=True))
    sw_display_format = relationship('SwDisplayFormat', foreign_keys=[sw_display_format_id], uselist=False, cascade="all")
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=False, cascade="all")

class SwClassAttrImplRef(Base):

    __tablename__ = "sw_class_attr_impl_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCalprmPointer(Base):

    __tablename__ = "sw_calprm_pointer"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwTemplateRef": "sw_template_ref",
        "SwClassAttrImplRef": "sw_class_attr_impl_ref",
        "Desc": "_desc",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_template_ref_id = Column(types.Integer, ForeignKey('sw_template_ref.rid', use_alter=True))
    sw_template_ref = relationship('SwTemplateRef', foreign_keys=[sw_template_ref_id], uselist=False, cascade="all")
    sw_class_attr_impl_ref_id = Column(types.Integer, ForeignKey('sw_class_attr_impl_ref.rid', use_alter=True))
    sw_class_attr_impl_ref = relationship('SwClassAttrImplRef', foreign_keys=[sw_class_attr_impl_ref_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")

class SwCalprmTarget(Base):

    __tablename__ = "sw_calprm_target"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=False, cascade="all")

class SwCalprmMaxTextSize(Base):

    __tablename__ = "sw_calprm_max_text_size"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwFillCharacter(Base):

    __tablename__ = "sw_fill_character"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCalprmText(Base):

    __tablename__ = "sw_calprm_text"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmMaxTextSize": "sw_calprm_max_text_size",
        "SwBaseTypeRef": "sw_base_type_ref",
        "SwFillCharacter": "sw_fill_character",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_max_text_size_id = Column(types.Integer, ForeignKey('sw_calprm_max_text_size.rid', use_alter=True))
    sw_calprm_max_text_size = relationship('SwCalprmMaxTextSize', foreign_keys=[sw_calprm_max_text_size_id], uselist=False, cascade="all")
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=False, cascade="all")
    sw_fill_character_id = Column(types.Integer, ForeignKey('sw_fill_character.rid', use_alter=True))
    sw_fill_character = relationship('SwFillCharacter', foreign_keys=[sw_fill_character_id], uselist=False, cascade="all")

class SwCalprmValueAxisLabels(Base):

    __tablename__ = "sw_calprm_value_axis_labels"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=True, cascade="all")

class SwCodeSyntaxRef(Base):

    __tablename__ = "sw_code_syntax_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwComparisonVariables(Base):

    __tablename__ = "sw_comparison_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")

class SwDataDependencyFormula(Base):

    __tablename__ = "sw_data_dependency_formula"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwDataDependencyArgs(Base):

    __tablename__ = "sw_data_dependency_args"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwCalprmRef": "sw_calprm_ref",
        "SwVariableRef": "sw_variable_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=True, cascade="all")
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")

class SwDataDependency(Base):

    __tablename__ = "sw_data_dependency"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Desc": "_desc",
        "SwDataDependencyFormula": "sw_data_dependency_formula",
        "SwDataDependencyArgs": "sw_data_dependency_args",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_data_dependency_formula_id = Column(types.Integer, ForeignKey('sw_data_dependency_formula.rid', use_alter=True))
    sw_data_dependency_formula = relationship('SwDataDependencyFormula', foreign_keys=[sw_data_dependency_formula_id], uselist=False, cascade="all")
    sw_data_dependency_args_id = Column(types.Integer, ForeignKey('sw_data_dependency_args.rid', use_alter=True))
    sw_data_dependency_args = relationship('SwDataDependencyArgs', foreign_keys=[sw_data_dependency_args_id], uselist=False, cascade="all")

class SwHostVariable(Base):

    __tablename__ = "sw_host_variable"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=False, cascade="all")

class SwImplPolicy(Base):

    __tablename__ = "sw_impl_policy"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwIntendedResolution(Base):

    __tablename__ = "sw_intended_resolution"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwInterpolationMethod(Base):

    __tablename__ = "sw_interpolation_method"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwIsVirtual(Base):

    __tablename__ = "sw_is_virtual"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcBaseTypeRef(Base):

    __tablename__ = "sw_mc_base_type_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutRef(Base):

    __tablename__ = "sw_record_layout_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwTaskRef(Base):

    __tablename__ = "sw_task_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVariableKind(Base):

    __tablename__ = "sw_variable_kind"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVarInitValue(Base):

    __tablename__ = "sw_var_init_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVarNotAvlValue(Base):

    __tablename__ = "sw_var_not_avl_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVcdCriterionRefs(Base):

    __tablename__ = "sw_vcd_criterion_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterionRef": "sw_vcd_criterion_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_vcd_criterion_ref_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_ref.rid', use_alter=True))
    sw_vcd_criterion_ref = relationship('SwVcdCriterionRef', foreign_keys=[sw_vcd_criterion_ref_id], uselist=True, cascade="all")

class SwDataDefProps(Base):

    __tablename__ = "sw_data_def_props"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Annotations": "annotations",
        "SwAddrMethodRef": "sw_addr_method_ref",
        "SwAliasName": "sw_alias_name",
        "SwBaseTypeRef": "sw_base_type_ref",
        "SwBitRepresentation": "sw_bit_representation",
        "SwCalibrationAccess": "sw_calibration_access",
        "SwCalprmAxisSet": "sw_calprm_axis_set",
        "SwCalprmNoEffectValue": "sw_calprm_no_effect_value",
        "SwCalprmPointer": "sw_calprm_pointer",
        "SwCalprmTarget": "sw_calprm_target",
        "SwCalprmText": "sw_calprm_text",
        "SwCalprmValueAxisLabels": "sw_calprm_value_axis_labels",
        "SwCodeSyntaxRef": "sw_code_syntax_ref",
        "SwComparisonVariables": "sw_comparison_variables",
        "SwCompuMethodRef": "sw_compu_method_ref",
        "SwDataConstrRef": "sw_data_constr_ref",
        "SwDataDependency": "sw_data_dependency",
        "SwDisplayFormat": "sw_display_format",
        "SwHostVariable": "sw_host_variable",
        "SwImplPolicy": "sw_impl_policy",
        "SwIntendedResolution": "sw_intended_resolution",
        "SwInterpolationMethod": "sw_interpolation_method",
        "SwIsVirtual": "sw_is_virtual",
        "SwMcBaseTypeRef": "sw_mc_base_type_ref",
        "SwRecordLayoutRef": "sw_record_layout_ref",
        "SwRefreshTiming": "sw_refresh_timing",
        "SwTaskRef": "sw_task_ref",
        "SwTemplateRef": "sw_template_ref",
        "SwUnitRef": "sw_unit_ref",
        "SwVariableKind": "sw_variable_kind",
        "SwVarInitValue": "sw_var_init_value",
        "SwVarNotAvlValue": "sw_var_not_avl_value",
        "SwVcdCriterionRefs": "sw_vcd_criterion_refs",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    sw_addr_method_ref_id = Column(types.Integer, ForeignKey('sw_addr_method_ref.rid', use_alter=True))
    sw_addr_method_ref = relationship('SwAddrMethodRef', foreign_keys=[sw_addr_method_ref_id], uselist=False, cascade="all")
    sw_alias_name_id = Column(types.Integer, ForeignKey('sw_alias_name.rid', use_alter=True))
    sw_alias_name = relationship('SwAliasName', foreign_keys=[sw_alias_name_id], uselist=False, cascade="all")
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=False, cascade="all")
    sw_bit_representation_id = Column(types.Integer, ForeignKey('sw_bit_representation.rid', use_alter=True))
    sw_bit_representation = relationship('SwBitRepresentation', foreign_keys=[sw_bit_representation_id], uselist=False, cascade="all")
    sw_calibration_access_id = Column(types.Integer, ForeignKey('sw_calibration_access.rid', use_alter=True))
    sw_calibration_access = relationship('SwCalibrationAccess', foreign_keys=[sw_calibration_access_id], uselist=False, cascade="all")
    sw_calprm_axis_set_id = Column(types.Integer, ForeignKey('sw_calprm_axis_set.rid', use_alter=True))
    sw_calprm_axis_set = relationship('SwCalprmAxisSet', foreign_keys=[sw_calprm_axis_set_id], uselist=False, cascade="all")
    sw_calprm_no_effect_value_id = Column(types.Integer, ForeignKey('sw_calprm_no_effect_value.rid', use_alter=True))
    sw_calprm_no_effect_value = relationship('SwCalprmNoEffectValue', foreign_keys=[sw_calprm_no_effect_value_id], uselist=False, cascade="all")
    sw_calprm_pointer_id = Column(types.Integer, ForeignKey('sw_calprm_pointer.rid', use_alter=True))
    sw_calprm_pointer = relationship('SwCalprmPointer', foreign_keys=[sw_calprm_pointer_id], uselist=False, cascade="all")
    sw_calprm_target_id = Column(types.Integer, ForeignKey('sw_calprm_target.rid', use_alter=True))
    sw_calprm_target = relationship('SwCalprmTarget', foreign_keys=[sw_calprm_target_id], uselist=False, cascade="all")
    sw_calprm_text_id = Column(types.Integer, ForeignKey('sw_calprm_text.rid', use_alter=True))
    sw_calprm_text = relationship('SwCalprmText', foreign_keys=[sw_calprm_text_id], uselist=False, cascade="all")
    sw_calprm_value_axis_labels_id = Column(types.Integer, ForeignKey('sw_calprm_value_axis_labels.rid', use_alter=True))
    sw_calprm_value_axis_labels = relationship('SwCalprmValueAxisLabels', foreign_keys=[sw_calprm_value_axis_labels_id], uselist=False, cascade="all")
    sw_code_syntax_ref_id = Column(types.Integer, ForeignKey('sw_code_syntax_ref.rid', use_alter=True))
    sw_code_syntax_ref = relationship('SwCodeSyntaxRef', foreign_keys=[sw_code_syntax_ref_id], uselist=False, cascade="all")
    sw_comparison_variables_id = Column(types.Integer, ForeignKey('sw_comparison_variables.rid', use_alter=True))
    sw_comparison_variables = relationship('SwComparisonVariables', foreign_keys=[sw_comparison_variables_id], uselist=False, cascade="all")
    sw_compu_method_ref_id = Column(types.Integer, ForeignKey('sw_compu_method_ref.rid', use_alter=True))
    sw_compu_method_ref = relationship('SwCompuMethodRef', foreign_keys=[sw_compu_method_ref_id], uselist=False, cascade="all")
    sw_data_constr_ref_id = Column(types.Integer, ForeignKey('sw_data_constr_ref.rid', use_alter=True))
    sw_data_constr_ref = relationship('SwDataConstrRef', foreign_keys=[sw_data_constr_ref_id], uselist=False, cascade="all")
    sw_data_dependency_id = Column(types.Integer, ForeignKey('sw_data_dependency.rid', use_alter=True))
    sw_data_dependency = relationship('SwDataDependency', foreign_keys=[sw_data_dependency_id], uselist=False, cascade="all")
    sw_display_format_id = Column(types.Integer, ForeignKey('sw_display_format.rid', use_alter=True))
    sw_display_format = relationship('SwDisplayFormat', foreign_keys=[sw_display_format_id], uselist=False, cascade="all")
    sw_host_variable_id = Column(types.Integer, ForeignKey('sw_host_variable.rid', use_alter=True))
    sw_host_variable = relationship('SwHostVariable', foreign_keys=[sw_host_variable_id], uselist=False, cascade="all")
    sw_impl_policy_id = Column(types.Integer, ForeignKey('sw_impl_policy.rid', use_alter=True))
    sw_impl_policy = relationship('SwImplPolicy', foreign_keys=[sw_impl_policy_id], uselist=False, cascade="all")
    sw_intended_resolution_id = Column(types.Integer, ForeignKey('sw_intended_resolution.rid', use_alter=True))
    sw_intended_resolution = relationship('SwIntendedResolution', foreign_keys=[sw_intended_resolution_id], uselist=False, cascade="all")
    sw_interpolation_method_id = Column(types.Integer, ForeignKey('sw_interpolation_method.rid', use_alter=True))
    sw_interpolation_method = relationship('SwInterpolationMethod', foreign_keys=[sw_interpolation_method_id], uselist=False, cascade="all")
    sw_is_virtual_id = Column(types.Integer, ForeignKey('sw_is_virtual.rid', use_alter=True))
    sw_is_virtual = relationship('SwIsVirtual', foreign_keys=[sw_is_virtual_id], uselist=False, cascade="all")
    sw_mc_base_type_ref_id = Column(types.Integer, ForeignKey('sw_mc_base_type_ref.rid', use_alter=True))
    sw_mc_base_type_ref = relationship('SwMcBaseTypeRef', foreign_keys=[sw_mc_base_type_ref_id], uselist=False, cascade="all")
    sw_record_layout_ref_id = Column(types.Integer, ForeignKey('sw_record_layout_ref.rid', use_alter=True))
    sw_record_layout_ref = relationship('SwRecordLayoutRef', foreign_keys=[sw_record_layout_ref_id], uselist=False, cascade="all")
    sw_refresh_timing_id = Column(types.Integer, ForeignKey('sw_refresh_timing.rid', use_alter=True))
    sw_refresh_timing = relationship('SwRefreshTiming', foreign_keys=[sw_refresh_timing_id], uselist=False, cascade="all")
    sw_task_ref_id = Column(types.Integer, ForeignKey('sw_task_ref.rid', use_alter=True))
    sw_task_ref = relationship('SwTaskRef', foreign_keys=[sw_task_ref_id], uselist=False, cascade="all")
    sw_template_ref_id = Column(types.Integer, ForeignKey('sw_template_ref.rid', use_alter=True))
    sw_template_ref = relationship('SwTemplateRef', foreign_keys=[sw_template_ref_id], uselist=False, cascade="all")
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    sw_variable_kind_id = Column(types.Integer, ForeignKey('sw_variable_kind.rid', use_alter=True))
    sw_variable_kind = relationship('SwVariableKind', foreign_keys=[sw_variable_kind_id], uselist=False, cascade="all")
    sw_var_init_value_id = Column(types.Integer, ForeignKey('sw_var_init_value.rid', use_alter=True))
    sw_var_init_value = relationship('SwVarInitValue', foreign_keys=[sw_var_init_value_id], uselist=False, cascade="all")
    sw_var_not_avl_value_id = Column(types.Integer, ForeignKey('sw_var_not_avl_value.rid', use_alter=True))
    sw_var_not_avl_value = relationship('SwVarNotAvlValue', foreign_keys=[sw_var_not_avl_value_id], uselist=False, cascade="all")
    sw_vcd_criterion_refs_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_refs.rid', use_alter=True))
    sw_vcd_criterion_refs = relationship('SwVcdCriterionRefs', foreign_keys=[sw_vcd_criterion_refs_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwTemplate(Base):

    __tablename__ = "sw_template"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwDataDefProps": "sw_data_def_props",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")

class SwVcdCriterionRef(Base):

    __tablename__ = "sw_vcd_criterion_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCalprms(Base):

    __tablename__ = "sw_calprms"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwCalprm": "sw_calprm",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_calprm_id = Column(types.Integer, ForeignKey('sw_calprm.rid', use_alter=True))
    sw_calprm = relationship('SwCalprm', foreign_keys=[sw_calprm_id], uselist=True, cascade="all")

class SwArraysize(Base):

    __tablename__ = "sw_arraysize"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "V": "v",
        "Vf": "vf",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")

class SwVariable(Base):

    __tablename__ = "sw_variable"
    ATTRIBUTES = {
        "CALIBRATION": "calibration",
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwArraysize": "sw_arraysize",
        "SwDataDefProps": "sw_data_def_props",
        "SwVariables": "sw_variables",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    ENUMS = {
        "calibration": ['CALIBRATION', 'NO-CALIBRATION', 'NOT-IN-MC-SYSTEM'],
    }
    calibration = StdString()
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")
    sw_variables_id = Column(types.Integer, ForeignKey('sw_variables.rid', use_alter=True))
    sw_variables = relationship('SwVariables', foreign_keys=[sw_variables_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwSystemconsts(Base):

    __tablename__ = "sw_systemconsts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconst": "sw_systemconst",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_id = Column(types.Integer, ForeignKey('sw_systemconst.rid', use_alter=True))
    sw_systemconst = relationship('SwSystemconst', foreign_keys=[sw_systemconst_id], uselist=True, cascade="all")

class SwCalprm(Base):

    __tablename__ = "sw_calprm"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwArraysize": "sw_arraysize",
        "SwDataDefProps": "sw_data_def_props",
        "SwCalprms": "sw_calprms",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")
    sw_calprms_id = Column(types.Integer, ForeignKey('sw_calprms.rid', use_alter=True))
    sw_calprms = relationship('SwCalprms', foreign_keys=[sw_calprms_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwClassInstances(Base):

    __tablename__ = "sw_class_instances"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstance": "sw_class_instance",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_instance_id = Column(types.Integer, ForeignKey('sw_class_instance.rid', use_alter=True))
    sw_class_instance = relationship('SwClassInstance', foreign_keys=[sw_class_instance_id], uselist=True, cascade="all")

class SwSystemconst(Base):

    __tablename__ = "sw_systemconst"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwValuesPhys": "sw_values_phys",
        "SwValuesCoded": "sw_values_coded",
        "SwDataDefProps": "sw_data_def_props",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_values_phys_id = Column(types.Integer, ForeignKey('sw_values_phys.rid', use_alter=True))
    sw_values_phys = relationship('SwValuesPhys', foreign_keys=[sw_values_phys_id], uselist=False, cascade="all")
    sw_values_coded_id = Column(types.Integer, ForeignKey('sw_values_coded.rid', use_alter=True))
    sw_values_coded = relationship('SwValuesCoded', foreign_keys=[sw_values_coded_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")

class SwCompuMethods(Base):

    __tablename__ = "sw_compu_methods"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwCompuMethod": "sw_compu_method",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_compu_method_id = Column(types.Integer, ForeignKey('sw_compu_method.rid', use_alter=True))
    sw_compu_method = relationship('SwCompuMethod', foreign_keys=[sw_compu_method_id], uselist=True, cascade="all")

class SwClassRef(Base):

    __tablename__ = "sw_class_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwClassInstance(Base):

    __tablename__ = "sw_class_instance"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwArraysize": "sw_arraysize",
        "SwClassRef": "sw_class_ref",
        "SwClassAttrImplRef": "sw_class_attr_impl_ref",
        "SwDataDefProps": "sw_data_def_props",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_class_ref_id = Column(types.Integer, ForeignKey('sw_class_ref.rid', use_alter=True))
    sw_class_ref = relationship('SwClassRef', foreign_keys=[sw_class_ref_id], uselist=False, cascade="all")
    sw_class_attr_impl_ref_id = Column(types.Integer, ForeignKey('sw_class_attr_impl_ref.rid', use_alter=True))
    sw_class_attr_impl_ref = relationship('SwClassAttrImplRef', foreign_keys=[sw_class_attr_impl_ref_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwAddrMethods(Base):

    __tablename__ = "sw_addr_methods"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwAddrMethod": "sw_addr_method",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_addr_method_id = Column(types.Integer, ForeignKey('sw_addr_method.rid', use_alter=True))
    sw_addr_method = relationship('SwAddrMethod', foreign_keys=[sw_addr_method_id], uselist=True, cascade="all")

class SwPhysConstrs1(Base):

    __tablename__ = "sw_phys_constrs_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwScaleConstr": "sw_scale_constr",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_scale_constr_id = Column(types.Integer, ForeignKey('sw_scale_constr.rid', use_alter=True))
    sw_scale_constr = relationship('SwScaleConstr', foreign_keys=[sw_scale_constr_id], uselist=True, cascade="all")

class SwInternalConstrs1(Base):

    __tablename__ = "sw_internal_constrs_1"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwScaleConstr": "sw_scale_constr",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_scale_constr_id = Column(types.Integer, ForeignKey('sw_scale_constr.rid', use_alter=True))
    sw_scale_constr = relationship('SwScaleConstr', foreign_keys=[sw_scale_constr_id], uselist=True, cascade="all")

class LowerLimit(Base):

    __tablename__ = "lower_limit"
    ATTRIBUTES = {
        "INTERVAL-TYPE": "interval_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "interval_type": ['OPEN', 'CLOSED'],
    }
    TERMINAL = True
    interval_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class UpperLimit(Base):

    __tablename__ = "upper_limit"
    ATTRIBUTES = {
        "INTERVAL-TYPE": "interval_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "interval_type": ['OPEN', 'CLOSED'],
    }
    TERMINAL = True
    interval_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwScaleConstr(Base):

    __tablename__ = "sw_scale_constr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LowerLimit": "lower_limit",
        "UpperLimit": "upper_limit",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    lower_limit_id = Column(types.Integer, ForeignKey('lower_limit.rid', use_alter=True))
    lower_limit = relationship('LowerLimit', foreign_keys=[lower_limit_id], uselist=False, cascade="all")
    upper_limit_id = Column(types.Integer, ForeignKey('upper_limit.rid', use_alter=True))
    upper_limit = relationship('UpperLimit', foreign_keys=[upper_limit_id], uselist=False, cascade="all")

class SwCompuIdentity(Base):

    __tablename__ = "sw_compu_identity"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCompuScales(Base):

    __tablename__ = "sw_compu_scales"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuScale": "sw_compu_scale",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_compu_scale_id = Column(types.Integer, ForeignKey('sw_compu_scale.rid', use_alter=True))
    sw_compu_scale = relationship('SwCompuScale', foreign_keys=[sw_compu_scale_id], uselist=True, cascade="all")

class SwCompuDefaultValue(Base):

    __tablename__ = "sw_compu_default_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCompuInternalToPhys(Base):

    __tablename__ = "sw_compu_internal_to_phys"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuScales": "sw_compu_scales",
        "SwCompuDefaultValue": "sw_compu_default_value",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_compu_scales_id = Column(types.Integer, ForeignKey('sw_compu_scales.rid', use_alter=True))
    sw_compu_scales = relationship('SwCompuScales', foreign_keys=[sw_compu_scales_id], uselist=False, cascade="all")
    sw_compu_default_value_id = Column(types.Integer, ForeignKey('sw_compu_default_value.rid', use_alter=True))
    sw_compu_default_value = relationship('SwCompuDefaultValue', foreign_keys=[sw_compu_default_value_id], uselist=False, cascade="all")

class CIdentifier(Base):

    __tablename__ = "c_identifier"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCompuInverseValue(Base):

    __tablename__ = "sw_compu_inverse_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "V": "v",
        "Vt": "vt",
        "Vh": "vh",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=False, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=False, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=False, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=False, cascade="all")

class SwCompuConst(Base):

    __tablename__ = "sw_compu_const"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "V": "v",
        "Vt": "vt",
        "Vh": "vh",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=False, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=False, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=False, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=False, cascade="all")

class SwCompuNumerator(Base):

    __tablename__ = "sw_compu_numerator"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "V": "v",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")

class SwCompuProgramCode(Base):

    __tablename__ = "sw_compu_program_code"
    ATTRIBUTES = {
        "LANG-SUBSET": "lang_subset",
        "USED-LIBS": "used_libs",
        "PROGRAM-LANG": "program_lang",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    lang_subset = StdString()
    used_libs = StdString()
    program_lang = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCompuDenominator(Base):

    __tablename__ = "sw_compu_denominator"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "V": "v",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")

class SwCompuRationalCoeffs(Base):

    __tablename__ = "sw_compu_rational_coeffs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuNumerator": "sw_compu_numerator",
        "SwCompuDenominator": "sw_compu_denominator",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_compu_numerator_id = Column(types.Integer, ForeignKey('sw_compu_numerator.rid', use_alter=True))
    sw_compu_numerator = relationship('SwCompuNumerator', foreign_keys=[sw_compu_numerator_id], uselist=False, cascade="all")
    sw_compu_denominator_id = Column(types.Integer, ForeignKey('sw_compu_denominator.rid', use_alter=True))
    sw_compu_denominator = relationship('SwCompuDenominator', foreign_keys=[sw_compu_denominator_id], uselist=False, cascade="all")

class SwCompuGenericMath(Base):

    __tablename__ = "sw_compu_generic_math"
    ATTRIBUTES = {
        "LEVEL": "level",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwSystemconstPhysRef": "sw_systemconst_phys_ref",
    }
    level = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_systemconst_phys_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_phys_ref.rid', use_alter=True))
    sw_systemconst_phys_ref = relationship('SwSystemconstPhysRef', foreign_keys=[sw_systemconst_phys_ref_id], uselist=True, cascade="all")

class SwCompuScale(Base):

    __tablename__ = "sw_compu_scale"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CIdentifier": "c_identifier",
        "Desc": "_desc",
        "LowerLimit": "lower_limit",
        "UpperLimit": "upper_limit",
        "SwCompuInverseValue": "sw_compu_inverse_value",
        "SwCompuConst": "sw_compu_const",
        "SwCompuRationalCoeffs": "sw_compu_rational_coeffs",
        "SwCompuProgramCode": "sw_compu_program_code",
        "SwCompuGenericMath": "sw_compu_generic_math",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    c_identifier_id = Column(types.Integer, ForeignKey('c_identifier.rid', use_alter=True))
    c_identifier = relationship('CIdentifier', foreign_keys=[c_identifier_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    lower_limit_id = Column(types.Integer, ForeignKey('lower_limit.rid', use_alter=True))
    lower_limit = relationship('LowerLimit', foreign_keys=[lower_limit_id], uselist=False, cascade="all")
    upper_limit_id = Column(types.Integer, ForeignKey('upper_limit.rid', use_alter=True))
    upper_limit = relationship('UpperLimit', foreign_keys=[upper_limit_id], uselist=False, cascade="all")
    sw_compu_inverse_value_id = Column(types.Integer, ForeignKey('sw_compu_inverse_value.rid', use_alter=True))
    sw_compu_inverse_value = relationship('SwCompuInverseValue', foreign_keys=[sw_compu_inverse_value_id], uselist=False, cascade="all")
    sw_compu_const_id = Column(types.Integer, ForeignKey('sw_compu_const.rid', use_alter=True))
    sw_compu_const = relationship('SwCompuConst', foreign_keys=[sw_compu_const_id], uselist=False, cascade="all")
    sw_compu_rational_coeffs_id = Column(types.Integer, ForeignKey('sw_compu_rational_coeffs.rid', use_alter=True))
    sw_compu_rational_coeffs = relationship('SwCompuRationalCoeffs', foreign_keys=[sw_compu_rational_coeffs_id], uselist=False, cascade="all")
    sw_compu_program_code_id = Column(types.Integer, ForeignKey('sw_compu_program_code.rid', use_alter=True))
    sw_compu_program_code = relationship('SwCompuProgramCode', foreign_keys=[sw_compu_program_code_id], uselist=False, cascade="all")
    sw_compu_generic_math_id = Column(types.Integer, ForeignKey('sw_compu_generic_math.rid', use_alter=True))
    sw_compu_generic_math = relationship('SwCompuGenericMath', foreign_keys=[sw_compu_generic_math_id], uselist=False, cascade="all")

class SwCompuPhysToInternal(Base):

    __tablename__ = "sw_compu_phys_to_internal"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuScales": "sw_compu_scales",
        "SwCompuDefaultValue": "sw_compu_default_value",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_compu_scales_id = Column(types.Integer, ForeignKey('sw_compu_scales.rid', use_alter=True))
    sw_compu_scales = relationship('SwCompuScales', foreign_keys=[sw_compu_scales_id], uselist=False, cascade="all")
    sw_compu_default_value_id = Column(types.Integer, ForeignKey('sw_compu_default_value.rid', use_alter=True))
    sw_compu_default_value = relationship('SwCompuDefaultValue', foreign_keys=[sw_compu_default_value_id], uselist=False, cascade="all")

class SwCompuMethod(Base):

    __tablename__ = "sw_compu_method"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwDisplayFormat": "sw_display_format",
        "SwUnitRef": "sw_unit_ref",
        "SwDataConstrRef": "sw_data_constr_ref",
        "SwPhysConstrs1": "sw_phys_constrs_1",
        "SwInternalConstrs1": "sw_internal_constrs_1",
        "SwCompuIdentity": "sw_compu_identity",
        "SwCompuPhysToInternal": "sw_compu_phys_to_internal",
        "SwCompuInternalToPhys": "sw_compu_internal_to_phys",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_display_format_id = Column(types.Integer, ForeignKey('sw_display_format.rid', use_alter=True))
    sw_display_format = relationship('SwDisplayFormat', foreign_keys=[sw_display_format_id], uselist=False, cascade="all")
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    sw_data_constr_ref_id = Column(types.Integer, ForeignKey('sw_data_constr_ref.rid', use_alter=True))
    sw_data_constr_ref = relationship('SwDataConstrRef', foreign_keys=[sw_data_constr_ref_id], uselist=False, cascade="all")
    sw_phys_constrs_1_id = Column(types.Integer, ForeignKey('sw_phys_constrs_1.rid', use_alter=True))
    sw_phys_constrs_1 = relationship('SwPhysConstrs1', foreign_keys=[sw_phys_constrs_1_id], uselist=False, cascade="all")
    sw_internal_constrs_1_id = Column(types.Integer, ForeignKey('sw_internal_constrs_1.rid', use_alter=True))
    sw_internal_constrs_1 = relationship('SwInternalConstrs1', foreign_keys=[sw_internal_constrs_1_id], uselist=False, cascade="all")
    sw_compu_identity_id = Column(types.Integer, ForeignKey('sw_compu_identity.rid', use_alter=True))
    sw_compu_identity = relationship('SwCompuIdentity', foreign_keys=[sw_compu_identity_id], uselist=False, cascade="all")
    sw_compu_phys_to_internal_id = Column(types.Integer, ForeignKey('sw_compu_phys_to_internal.rid', use_alter=True))
    sw_compu_phys_to_internal = relationship('SwCompuPhysToInternal', foreign_keys=[sw_compu_phys_to_internal_id], uselist=False, cascade="all")
    sw_compu_internal_to_phys_id = Column(types.Integer, ForeignKey('sw_compu_internal_to_phys.rid', use_alter=True))
    sw_compu_internal_to_phys = relationship('SwCompuInternalToPhys', foreign_keys=[sw_compu_internal_to_phys_id], uselist=False, cascade="all")

class SwRecordLayouts(Base):

    __tablename__ = "sw_record_layouts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwRecordLayout": "sw_record_layout",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_record_layout_id = Column(types.Integer, ForeignKey('sw_record_layout.rid', use_alter=True))
    sw_record_layout = relationship('SwRecordLayout', foreign_keys=[sw_record_layout_id], uselist=True, cascade="all")

class SwCpuMemSegRef(Base):

    __tablename__ = "sw_cpu_mem_seg_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAddrMethodDesc(Base):

    __tablename__ = "sw_addr_method_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwAddrMethod(Base):

    __tablename__ = "sw_addr_method"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwCpuMemSegRef": "sw_cpu_mem_seg_ref",
        "SwAddrMethodDesc": "sw_addr_method_desc",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_cpu_mem_seg_ref_id = Column(types.Integer, ForeignKey('sw_cpu_mem_seg_ref.rid', use_alter=True))
    sw_cpu_mem_seg_ref = relationship('SwCpuMemSegRef', foreign_keys=[sw_cpu_mem_seg_ref_id], uselist=False, cascade="all")
    sw_addr_method_desc_id = Column(types.Integer, ForeignKey('sw_addr_method_desc.rid', use_alter=True))
    sw_addr_method_desc = relationship('SwAddrMethodDesc', foreign_keys=[sw_addr_method_desc_id], uselist=False, cascade="all")

class SwCodeSyntaxes(Base):

    __tablename__ = "sw_code_syntaxes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwCodeSyntax": "sw_code_syntax",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_code_syntax_id = Column(types.Integer, ForeignKey('sw_code_syntax.rid', use_alter=True))
    sw_code_syntax = relationship('SwCodeSyntax', foreign_keys=[sw_code_syntax_id], uselist=True, cascade="all")

class SwRecordLayout(Base):

    __tablename__ = "sw_record_layout"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwRecordLayoutGroup": "sw_record_layout_group",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_record_layout_group_id = Column(types.Integer, ForeignKey('sw_record_layout_group.rid', use_alter=True))
    sw_record_layout_group = relationship('SwRecordLayoutGroup', foreign_keys=[sw_record_layout_group_id], uselist=True, cascade="all")

class SwRecordLayoutGroupAxis(Base):

    __tablename__ = "sw_record_layout_group_axis"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutGroupIndex(Base):

    __tablename__ = "sw_record_layout_group_index"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutGroupFrom(Base):

    __tablename__ = "sw_record_layout_group_from"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutGroupTo(Base):

    __tablename__ = "sw_record_layout_group_to"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutGroupStep(Base):

    __tablename__ = "sw_record_layout_group_step"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutComponent(Base):

    __tablename__ = "sw_record_layout_component"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutGroup(Base):

    __tablename__ = "sw_record_layout_group"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Desc": "_desc",
        "SwRecordLayoutGroupAxis": "sw_record_layout_group_axis",
        "SwRecordLayoutGroupIndex": "sw_record_layout_group_index",
        "SwGenericAxisParamTypeRef": "sw_generic_axis_param_type_ref",
        "SwRecordLayoutGroupFrom": "sw_record_layout_group_from",
        "SwRecordLayoutGroupTo": "sw_record_layout_group_to",
        "SwRecordLayoutGroupStep": "sw_record_layout_group_step",
        "SwRecordLayoutComponent": "sw_record_layout_component",
        "SwRecordLayoutRef": "sw_record_layout_ref",
        "SwRecordLayoutV": "sw_record_layout_v",
        "SwRecordLayoutGroup": "sw_record_layout_group",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_record_layout_group_axis_id = Column(types.Integer, ForeignKey('sw_record_layout_group_axis.rid', use_alter=True))
    sw_record_layout_group_axis = relationship('SwRecordLayoutGroupAxis', foreign_keys=[sw_record_layout_group_axis_id], uselist=False, cascade="all")
    sw_record_layout_group_index_id = Column(types.Integer, ForeignKey('sw_record_layout_group_index.rid', use_alter=True))
    sw_record_layout_group_index = relationship('SwRecordLayoutGroupIndex', foreign_keys=[sw_record_layout_group_index_id], uselist=False, cascade="all")
    sw_generic_axis_param_type_ref_id = Column(types.Integer, ForeignKey('sw_generic_axis_param_type_ref.rid', use_alter=True))
    sw_generic_axis_param_type_ref = relationship('SwGenericAxisParamTypeRef', foreign_keys=[sw_generic_axis_param_type_ref_id], uselist=False, cascade="all")
    sw_record_layout_group_from_id = Column(types.Integer, ForeignKey('sw_record_layout_group_from.rid', use_alter=True))
    sw_record_layout_group_from = relationship('SwRecordLayoutGroupFrom', foreign_keys=[sw_record_layout_group_from_id], uselist=False, cascade="all")
    sw_record_layout_group_to_id = Column(types.Integer, ForeignKey('sw_record_layout_group_to.rid', use_alter=True))
    sw_record_layout_group_to = relationship('SwRecordLayoutGroupTo', foreign_keys=[sw_record_layout_group_to_id], uselist=False, cascade="all")
    sw_record_layout_group_step_id = Column(types.Integer, ForeignKey('sw_record_layout_group_step.rid', use_alter=True))
    sw_record_layout_group_step = relationship('SwRecordLayoutGroupStep', foreign_keys=[sw_record_layout_group_step_id], uselist=False, cascade="all")
    sw_record_layout_component_id = Column(types.Integer, ForeignKey('sw_record_layout_component.rid', use_alter=True))
    sw_record_layout_component = relationship('SwRecordLayoutComponent', foreign_keys=[sw_record_layout_component_id], uselist=False, cascade="all")
    sw_record_layout_ref_id = Column(types.Integer, ForeignKey('sw_record_layout_ref.rid', use_alter=True))
    sw_record_layout_ref = relationship('SwRecordLayoutRef', foreign_keys=[sw_record_layout_ref_id], uselist=True, cascade="all")
    sw_record_layout_v_id = Column(types.Integer, ForeignKey('sw_record_layout_v.rid', use_alter=True))
    sw_record_layout_v = relationship('SwRecordLayoutV', foreign_keys=[sw_record_layout_v_id], uselist=True, cascade="all")
    sw_record_layout_group_id = Column(types.Integer, ForeignKey('sw_record_layout_group.rid', use_alter=True))
    sw_record_layout_group = relationship('SwRecordLayoutGroup', foreign_keys=[sw_record_layout_group_id], uselist=True, cascade="all")

class SwRecordLayoutVAxis(Base):

    __tablename__ = "sw_record_layout_v_axis"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutVProp(Base):

    __tablename__ = "sw_record_layout_v_prop"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutVIndex(Base):

    __tablename__ = "sw_record_layout_v_index"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutVFixValue(Base):

    __tablename__ = "sw_record_layout_v_fix_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRecordLayoutV(Base):

    __tablename__ = "sw_record_layout_v"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Desc": "_desc",
        "SwBaseTypeRef": "sw_base_type_ref",
        "SwRecordLayoutVAxis": "sw_record_layout_v_axis",
        "SwRecordLayoutVProp": "sw_record_layout_v_prop",
        "SwRecordLayoutVIndex": "sw_record_layout_v_index",
        "SwGenericAxisParamTypeRef": "sw_generic_axis_param_type_ref",
        "SwRecordLayoutVFixValue": "sw_record_layout_v_fix_value",
        "SwRecordLayoutRef": "sw_record_layout_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=False, cascade="all")
    sw_record_layout_v_axis_id = Column(types.Integer, ForeignKey('sw_record_layout_v_axis.rid', use_alter=True))
    sw_record_layout_v_axis = relationship('SwRecordLayoutVAxis', foreign_keys=[sw_record_layout_v_axis_id], uselist=False, cascade="all")
    sw_record_layout_v_prop_id = Column(types.Integer, ForeignKey('sw_record_layout_v_prop.rid', use_alter=True))
    sw_record_layout_v_prop = relationship('SwRecordLayoutVProp', foreign_keys=[sw_record_layout_v_prop_id], uselist=False, cascade="all")
    sw_record_layout_v_index_id = Column(types.Integer, ForeignKey('sw_record_layout_v_index.rid', use_alter=True))
    sw_record_layout_v_index = relationship('SwRecordLayoutVIndex', foreign_keys=[sw_record_layout_v_index_id], uselist=False, cascade="all")
    sw_generic_axis_param_type_ref_id = Column(types.Integer, ForeignKey('sw_generic_axis_param_type_ref.rid', use_alter=True))
    sw_generic_axis_param_type_ref = relationship('SwGenericAxisParamTypeRef', foreign_keys=[sw_generic_axis_param_type_ref_id], uselist=False, cascade="all")
    sw_record_layout_v_fix_value_id = Column(types.Integer, ForeignKey('sw_record_layout_v_fix_value.rid', use_alter=True))
    sw_record_layout_v_fix_value = relationship('SwRecordLayoutVFixValue', foreign_keys=[sw_record_layout_v_fix_value_id], uselist=False, cascade="all")
    sw_record_layout_ref_id = Column(types.Integer, ForeignKey('sw_record_layout_ref.rid', use_alter=True))
    sw_record_layout_ref = relationship('SwRecordLayoutRef', foreign_keys=[sw_record_layout_ref_id], uselist=False, cascade="all")

class SwBaseTypes(Base):

    __tablename__ = "sw_base_types"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwBaseType": "sw_base_type",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_base_type_id = Column(types.Integer, ForeignKey('sw_base_type.rid', use_alter=True))
    sw_base_type = relationship('SwBaseType', foreign_keys=[sw_base_type_id], uselist=True, cascade="all")

class SwCodeSyntaxDesc(Base):

    __tablename__ = "sw_code_syntax_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwCodeSyntax(Base):

    __tablename__ = "sw_code_syntax"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwCodeSyntaxDesc": "sw_code_syntax_desc",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_code_syntax_desc_id = Column(types.Integer, ForeignKey('sw_code_syntax_desc.rid', use_alter=True))
    sw_code_syntax_desc = relationship('SwCodeSyntaxDesc', foreign_keys=[sw_code_syntax_desc_id], uselist=False, cascade="all")

class SwDataConstrs(Base):

    __tablename__ = "sw_data_constrs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwDataConstr": "sw_data_constr",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_data_constr_id = Column(types.Integer, ForeignKey('sw_data_constr.rid', use_alter=True))
    sw_data_constr = relationship('SwDataConstr', foreign_keys=[sw_data_constr_id], uselist=True, cascade="all")

class SwBaseTypeSize(Base):

    __tablename__ = "sw_base_type_size"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCodedType(Base):

    __tablename__ = "sw_coded_type"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemAlignment(Base):

    __tablename__ = "sw_mem_alignment"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class ByteOrder(Base):

    __tablename__ = "byte_order"
    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "_type": ['MOST-SIGNIFICANT-BYTE-FIRST', 'MOST-SIGNIFICANT-BYTE-LAST'],
    }
    TERMINAL = True
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwBaseType(Base):

    __tablename__ = "sw_base_type"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwBaseTypeSize": "sw_base_type_size",
        "SwCodedType": "sw_coded_type",
        "SwMemAlignment": "sw_mem_alignment",
        "ByteOrder": "byte_order",
        "SwBaseTypeRef": "sw_base_type_ref",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_base_type_size_id = Column(types.Integer, ForeignKey('sw_base_type_size.rid', use_alter=True))
    sw_base_type_size = relationship('SwBaseTypeSize', foreign_keys=[sw_base_type_size_id], uselist=False, cascade="all")
    sw_coded_type_id = Column(types.Integer, ForeignKey('sw_coded_type.rid', use_alter=True))
    sw_coded_type = relationship('SwCodedType', foreign_keys=[sw_coded_type_id], uselist=False, cascade="all")
    sw_mem_alignment_id = Column(types.Integer, ForeignKey('sw_mem_alignment.rid', use_alter=True))
    sw_mem_alignment = relationship('SwMemAlignment', foreign_keys=[sw_mem_alignment_id], uselist=False, cascade="all")
    byte_order_id = Column(types.Integer, ForeignKey('byte_order.rid', use_alter=True))
    byte_order = relationship('ByteOrder', foreign_keys=[byte_order_id], uselist=False, cascade="all")
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=False, cascade="all")

class SwAxisTypes(Base):

    __tablename__ = "sw_axis_types"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwAxisType": "sw_axis_type",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_axis_type_id = Column(types.Integer, ForeignKey('sw_axis_type.rid', use_alter=True))
    sw_axis_type = relationship('SwAxisType', foreign_keys=[sw_axis_type_id], uselist=True, cascade="all")

class SwConstrObjects(Base):

    __tablename__ = "sw_constr_objects"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwCalprmRef": "sw_calprm_ref",
        "SwCompuMethodRef": "sw_compu_method_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=True, cascade="all")
    sw_compu_method_ref_id = Column(types.Integer, ForeignKey('sw_compu_method_ref.rid', use_alter=True))
    sw_compu_method_ref = relationship('SwCompuMethodRef', foreign_keys=[sw_compu_method_ref_id], uselist=True, cascade="all")

class SwDataConstr(Base):

    __tablename__ = "sw_data_constr"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwConstrObjects": "sw_constr_objects",
        "SwDataConstrRule": "sw_data_constr_rule",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_constr_objects_id = Column(types.Integer, ForeignKey('sw_constr_objects.rid', use_alter=True))
    sw_constr_objects = relationship('SwConstrObjects', foreign_keys=[sw_constr_objects_id], uselist=False, cascade="all")
    sw_data_constr_rule_id = Column(types.Integer, ForeignKey('sw_data_constr_rule.rid', use_alter=True))
    sw_data_constr_rule = relationship('SwDataConstrRule', foreign_keys=[sw_data_constr_rule_id], uselist=True, cascade="all")

class SwConstrLevel(Base):

    __tablename__ = "sw_constr_level"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMaxGradient(Base):

    __tablename__ = "sw_max_gradient"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwScaleConstrs(Base):

    __tablename__ = "sw_scale_constrs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwScaleConstr": "sw_scale_constr",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_scale_constr_id = Column(types.Integer, ForeignKey('sw_scale_constr.rid', use_alter=True))
    sw_scale_constr = relationship('SwScaleConstr', foreign_keys=[sw_scale_constr_id], uselist=True, cascade="all")

class SwMaxDiff(Base):

    __tablename__ = "sw_max_diff"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMonotony(Base):

    __tablename__ = "sw_monotony"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwRelatedConstrs(Base):

    __tablename__ = "sw_related_constrs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwDataDependency": "sw_data_dependency",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_data_dependency_id = Column(types.Integer, ForeignKey('sw_data_dependency.rid', use_alter=True))
    sw_data_dependency = relationship('SwDataDependency', foreign_keys=[sw_data_dependency_id], uselist=True, cascade="all")

class SwInternalConstrs(Base):

    __tablename__ = "sw_internal_constrs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LowerLimit": "lower_limit",
        "UpperLimit": "upper_limit",
        "SwScaleConstrs": "sw_scale_constrs",
        "SwMaxDiff": "sw_max_diff",
        "SwMonotony": "sw_monotony",
        "SwRelatedConstrs": "sw_related_constrs",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    lower_limit_id = Column(types.Integer, ForeignKey('lower_limit.rid', use_alter=True))
    lower_limit = relationship('LowerLimit', foreign_keys=[lower_limit_id], uselist=False, cascade="all")
    upper_limit_id = Column(types.Integer, ForeignKey('upper_limit.rid', use_alter=True))
    upper_limit = relationship('UpperLimit', foreign_keys=[upper_limit_id], uselist=False, cascade="all")
    sw_scale_constrs_id = Column(types.Integer, ForeignKey('sw_scale_constrs.rid', use_alter=True))
    sw_scale_constrs = relationship('SwScaleConstrs', foreign_keys=[sw_scale_constrs_id], uselist=False, cascade="all")
    sw_max_diff_id = Column(types.Integer, ForeignKey('sw_max_diff.rid', use_alter=True))
    sw_max_diff = relationship('SwMaxDiff', foreign_keys=[sw_max_diff_id], uselist=False, cascade="all")
    sw_monotony_id = Column(types.Integer, ForeignKey('sw_monotony.rid', use_alter=True))
    sw_monotony = relationship('SwMonotony', foreign_keys=[sw_monotony_id], uselist=False, cascade="all")
    sw_related_constrs_id = Column(types.Integer, ForeignKey('sw_related_constrs.rid', use_alter=True))
    sw_related_constrs = relationship('SwRelatedConstrs', foreign_keys=[sw_related_constrs_id], uselist=False, cascade="all")

class SwPhysConstrs(Base):

    __tablename__ = "sw_phys_constrs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LowerLimit": "lower_limit",
        "UpperLimit": "upper_limit",
        "SwScaleConstrs": "sw_scale_constrs",
        "SwUnitRef": "sw_unit_ref",
        "SwMaxDiff": "sw_max_diff",
        "SwMonotony": "sw_monotony",
        "SwRelatedConstrs": "sw_related_constrs",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    lower_limit_id = Column(types.Integer, ForeignKey('lower_limit.rid', use_alter=True))
    lower_limit = relationship('LowerLimit', foreign_keys=[lower_limit_id], uselist=False, cascade="all")
    upper_limit_id = Column(types.Integer, ForeignKey('upper_limit.rid', use_alter=True))
    upper_limit = relationship('UpperLimit', foreign_keys=[upper_limit_id], uselist=False, cascade="all")
    sw_scale_constrs_id = Column(types.Integer, ForeignKey('sw_scale_constrs.rid', use_alter=True))
    sw_scale_constrs = relationship('SwScaleConstrs', foreign_keys=[sw_scale_constrs_id], uselist=False, cascade="all")
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    sw_max_diff_id = Column(types.Integer, ForeignKey('sw_max_diff.rid', use_alter=True))
    sw_max_diff = relationship('SwMaxDiff', foreign_keys=[sw_max_diff_id], uselist=False, cascade="all")
    sw_monotony_id = Column(types.Integer, ForeignKey('sw_monotony.rid', use_alter=True))
    sw_monotony = relationship('SwMonotony', foreign_keys=[sw_monotony_id], uselist=False, cascade="all")
    sw_related_constrs_id = Column(types.Integer, ForeignKey('sw_related_constrs.rid', use_alter=True))
    sw_related_constrs = relationship('SwRelatedConstrs', foreign_keys=[sw_related_constrs_id], uselist=False, cascade="all")

class SwDataConstrRule(Base):

    __tablename__ = "sw_data_constr_rule"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwConstrLevel": "sw_constr_level",
        "SwMaxGradient": "sw_max_gradient",
        "SwPhysConstrs": "sw_phys_constrs",
        "SwInternalConstrs": "sw_internal_constrs",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_constr_level_id = Column(types.Integer, ForeignKey('sw_constr_level.rid', use_alter=True))
    sw_constr_level = relationship('SwConstrLevel', foreign_keys=[sw_constr_level_id], uselist=False, cascade="all")
    sw_max_gradient_id = Column(types.Integer, ForeignKey('sw_max_gradient.rid', use_alter=True))
    sw_max_gradient = relationship('SwMaxGradient', foreign_keys=[sw_max_gradient_id], uselist=False, cascade="all")
    sw_phys_constrs_id = Column(types.Integer, ForeignKey('sw_phys_constrs.rid', use_alter=True))
    sw_phys_constrs = relationship('SwPhysConstrs', foreign_keys=[sw_phys_constrs_id], uselist=False, cascade="all")
    sw_internal_constrs_id = Column(types.Integer, ForeignKey('sw_internal_constrs.rid', use_alter=True))
    sw_internal_constrs = relationship('SwInternalConstrs', foreign_keys=[sw_internal_constrs_id], uselist=False, cascade="all")

class SwDataDictionarySpec(Base):

    __tablename__ = "sw_data_dictionary_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "Desc": "_desc",
        "SwUnits": "sw_units",
        "SwTemplates": "sw_templates",
        "SwVariables": "sw_variables",
        "SwCalprms": "sw_calprms",
        "SwSystemconsts": "sw_systemconsts",
        "SwClassInstances": "sw_class_instances",
        "SwCompuMethods": "sw_compu_methods",
        "SwAddrMethods": "sw_addr_methods",
        "SwRecordLayouts": "sw_record_layouts",
        "SwCodeSyntaxes": "sw_code_syntaxes",
        "SwBaseTypes": "sw_base_types",
        "SwDataConstrs": "sw_data_constrs",
        "SwAxisTypes": "sw_axis_types",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_units_id = Column(types.Integer, ForeignKey('sw_units.rid', use_alter=True))
    sw_units = relationship('SwUnits', foreign_keys=[sw_units_id], uselist=False, cascade="all")
    sw_templates_id = Column(types.Integer, ForeignKey('sw_templates.rid', use_alter=True))
    sw_templates = relationship('SwTemplates', foreign_keys=[sw_templates_id], uselist=False, cascade="all")
    sw_variables_id = Column(types.Integer, ForeignKey('sw_variables.rid', use_alter=True))
    sw_variables = relationship('SwVariables', foreign_keys=[sw_variables_id], uselist=False, cascade="all")
    sw_calprms_id = Column(types.Integer, ForeignKey('sw_calprms.rid', use_alter=True))
    sw_calprms = relationship('SwCalprms', foreign_keys=[sw_calprms_id], uselist=False, cascade="all")
    sw_systemconsts_id = Column(types.Integer, ForeignKey('sw_systemconsts.rid', use_alter=True))
    sw_systemconsts = relationship('SwSystemconsts', foreign_keys=[sw_systemconsts_id], uselist=False, cascade="all")
    sw_class_instances_id = Column(types.Integer, ForeignKey('sw_class_instances.rid', use_alter=True))
    sw_class_instances = relationship('SwClassInstances', foreign_keys=[sw_class_instances_id], uselist=False, cascade="all")
    sw_compu_methods_id = Column(types.Integer, ForeignKey('sw_compu_methods.rid', use_alter=True))
    sw_compu_methods = relationship('SwCompuMethods', foreign_keys=[sw_compu_methods_id], uselist=False, cascade="all")
    sw_addr_methods_id = Column(types.Integer, ForeignKey('sw_addr_methods.rid', use_alter=True))
    sw_addr_methods = relationship('SwAddrMethods', foreign_keys=[sw_addr_methods_id], uselist=False, cascade="all")
    sw_record_layouts_id = Column(types.Integer, ForeignKey('sw_record_layouts.rid', use_alter=True))
    sw_record_layouts = relationship('SwRecordLayouts', foreign_keys=[sw_record_layouts_id], uselist=False, cascade="all")
    sw_code_syntaxes_id = Column(types.Integer, ForeignKey('sw_code_syntaxes.rid', use_alter=True))
    sw_code_syntaxes = relationship('SwCodeSyntaxes', foreign_keys=[sw_code_syntaxes_id], uselist=False, cascade="all")
    sw_base_types_id = Column(types.Integer, ForeignKey('sw_base_types.rid', use_alter=True))
    sw_base_types = relationship('SwBaseTypes', foreign_keys=[sw_base_types_id], uselist=False, cascade="all")
    sw_data_constrs_id = Column(types.Integer, ForeignKey('sw_data_constrs.rid', use_alter=True))
    sw_data_constrs = relationship('SwDataConstrs', foreign_keys=[sw_data_constrs_id], uselist=False, cascade="all")
    sw_axis_types_id = Column(types.Integer, ForeignKey('sw_axis_types.rid', use_alter=True))
    sw_axis_types = relationship('SwAxisTypes', foreign_keys=[sw_axis_types_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwGenericAxisDesc(Base):

    __tablename__ = "sw_generic_axis_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")

class SwGenericAxisParamTypes(Base):

    __tablename__ = "sw_generic_axis_param_types"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwGenericAxisParamType": "sw_generic_axis_param_type",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_generic_axis_param_type_id = Column(types.Integer, ForeignKey('sw_generic_axis_param_type.rid', use_alter=True))
    sw_generic_axis_param_type = relationship('SwGenericAxisParamType', foreign_keys=[sw_generic_axis_param_type_id], uselist=True, cascade="all")

class SwAxisType(Base):

    __tablename__ = "sw_axis_type"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwGenericAxisDesc": "sw_generic_axis_desc",
        "SwGenericAxisParamTypes": "sw_generic_axis_param_types",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_generic_axis_desc_id = Column(types.Integer, ForeignKey('sw_generic_axis_desc.rid', use_alter=True))
    sw_generic_axis_desc = relationship('SwGenericAxisDesc', foreign_keys=[sw_generic_axis_desc_id], uselist=False, cascade="all")
    sw_generic_axis_param_types_id = Column(types.Integer, ForeignKey('sw_generic_axis_param_types.rid', use_alter=True))
    sw_generic_axis_param_types = relationship('SwGenericAxisParamTypes', foreign_keys=[sw_generic_axis_param_types_id], uselist=False, cascade="all")

class SwGenericAxisParamType(Base):

    __tablename__ = "sw_generic_axis_param_type"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwDataConstrRef": "sw_data_constr_ref",
        "SwGenericAxisParamType": "sw_generic_axis_param_type",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_data_constr_ref_id = Column(types.Integer, ForeignKey('sw_data_constr_ref.rid', use_alter=True))
    sw_data_constr_ref = relationship('SwDataConstrRef', foreign_keys=[sw_data_constr_ref_id], uselist=False, cascade="all")
    sw_generic_axis_param_type_id = Column(types.Integer, ForeignKey('sw_generic_axis_param_type.rid', use_alter=True))
    sw_generic_axis_param_type = relationship('SwGenericAxisParamType', foreign_keys=[sw_generic_axis_param_type_id], uselist=True, cascade="all")

class SwInstanceSpec(Base):

    __tablename__ = "sw_instance_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwInstanceTree": "sw_instance_tree",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_instance_tree_id = Column(types.Integer, ForeignKey('sw_instance_tree.rid', use_alter=True))
    sw_instance_tree = relationship('SwInstanceTree', foreign_keys=[sw_instance_tree_id], uselist=True, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwRootFeatures(Base):

    __tablename__ = "sw_root_features"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRef": "sw_feature_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_ref_id = Column(types.Integer, ForeignKey('sw_feature_ref.rid', use_alter=True))
    sw_feature_ref = relationship('SwFeatureRef', foreign_keys=[sw_feature_ref_id], uselist=True, cascade="all")

class SwFeatureDef(Base):

    __tablename__ = "sw_feature_def"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwFeatureDesc(Base):

    __tablename__ = "sw_feature_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwFulfils(Base):

    __tablename__ = "sw_fulfils"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FunctionRef": "function_ref",
        "RequirementRef": "requirement_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    function_ref_id = Column(types.Integer, ForeignKey('function_ref.rid', use_alter=True))
    function_ref = relationship('FunctionRef', foreign_keys=[function_ref_id], uselist=True, cascade="all")
    requirement_ref_id = Column(types.Integer, ForeignKey('requirement_ref.rid', use_alter=True))
    requirement_ref = relationship('RequirementRef', foreign_keys=[requirement_ref_id], uselist=True, cascade="all")

class SwClassMethods(Base):

    __tablename__ = "sw_class_methods"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassMethod": "sw_class_method",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_method_id = Column(types.Integer, ForeignKey('sw_class_method.rid', use_alter=True))
    sw_class_method = relationship('SwClassMethod', foreign_keys=[sw_class_method_id], uselist=True, cascade="all")

class FunctionRef(Base):

    __tablename__ = "function_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "F-EXT-ID-CLASS": "f_ext_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    f_ext_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class RequirementRef(Base):

    __tablename__ = "requirement_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVariablePrototypes(Base):

    __tablename__ = "sw_variable_prototypes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablePrototype": "sw_variable_prototype",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_prototype_id = Column(types.Integer, ForeignKey('sw_variable_prototype.rid', use_alter=True))
    sw_variable_prototype = relationship('SwVariablePrototype', foreign_keys=[sw_variable_prototype_id], uselist=True, cascade="all")

class ShortLabel(Base):

    __tablename__ = "short_label"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwClassMethodReturn(Base):

    __tablename__ = "sw_class_method_return"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")

class SwClassMethod(Base):

    __tablename__ = "sw_class_method"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "ShortLabel": "short_label",
        "Desc": "_desc",
        "SwClassMethodReturn": "sw_class_method_return",
        "SwClassMethodArg": "sw_class_method_arg",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    short_label_id = Column(types.Integer, ForeignKey('short_label.rid', use_alter=True))
    short_label = relationship('ShortLabel', foreign_keys=[short_label_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_class_method_return_id = Column(types.Integer, ForeignKey('sw_class_method_return.rid', use_alter=True))
    sw_class_method_return = relationship('SwClassMethodReturn', foreign_keys=[sw_class_method_return_id], uselist=False, cascade="all")
    sw_class_method_arg_id = Column(types.Integer, ForeignKey('sw_class_method_arg.rid', use_alter=True))
    sw_class_method_arg = relationship('SwClassMethodArg', foreign_keys=[sw_class_method_arg_id], uselist=True, cascade="all")

class SwClassMethodArg(Base):

    __tablename__ = "sw_class_method_arg"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "ShortLabel": "short_label",
        "Remark": "remark",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    short_label_id = Column(types.Integer, ForeignKey('short_label.rid', use_alter=True))
    short_label = relationship('ShortLabel', foreign_keys=[short_label_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")

class SwClassAttrImpls(Base):

    __tablename__ = "sw_class_attr_impls"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassAttrImpl": "sw_class_attr_impl",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_attr_impl_id = Column(types.Integer, ForeignKey('sw_class_attr_impl.rid', use_alter=True))
    sw_class_attr_impl = relationship('SwClassAttrImpl', foreign_keys=[sw_class_attr_impl_id], uselist=True, cascade="all")

class SwCalprmPrototypes(Base):

    __tablename__ = "sw_calprm_prototypes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmPrototype": "sw_calprm_prototype",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_prototype_id = Column(types.Integer, ForeignKey('sw_calprm_prototype.rid', use_alter=True))
    sw_calprm_prototype = relationship('SwCalprmPrototype', foreign_keys=[sw_calprm_prototype_id], uselist=True, cascade="all")

class SwSyscond(Base):

    __tablename__ = "sw_syscond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": "sw_systemconst_coded_ref",
        "SwSystemconstPhysRef": "sw_systemconst_phys_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_coded_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_coded_ref.rid', use_alter=True))
    sw_systemconst_coded_ref = relationship('SwSystemconstCodedRef', foreign_keys=[sw_systemconst_coded_ref_id], uselist=True, cascade="all")
    sw_systemconst_phys_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_phys_ref.rid', use_alter=True))
    sw_systemconst_phys_ref = relationship('SwSystemconstPhysRef', foreign_keys=[sw_systemconst_phys_ref_id], uselist=True, cascade="all")

class SwVariablePrototype(Base):

    __tablename__ = "sw_variable_prototype"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwArraysize": "sw_arraysize",
        "SwUnitRef": "sw_unit_ref",
        "SwSyscond": "sw_syscond",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    sw_syscond_id = Column(types.Integer, ForeignKey('sw_syscond.rid', use_alter=True))
    sw_syscond = relationship('SwSyscond', foreign_keys=[sw_syscond_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwClassPrototypes(Base):

    __tablename__ = "sw_class_prototypes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassPrototype": "sw_class_prototype",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_prototype_id = Column(types.Integer, ForeignKey('sw_class_prototype.rid', use_alter=True))
    sw_class_prototype = relationship('SwClassPrototype', foreign_keys=[sw_class_prototype_id], uselist=True, cascade="all")

class SwCalprmPrototype(Base):

    __tablename__ = "sw_calprm_prototype"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwArraysize": "sw_arraysize",
        "SwSyscond": "sw_syscond",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_syscond_id = Column(types.Integer, ForeignKey('sw_syscond.rid', use_alter=True))
    sw_syscond = relationship('SwSyscond', foreign_keys=[sw_syscond_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwClassAttr(Base):

    __tablename__ = "sw_class_attr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablePrototypes": "sw_variable_prototypes",
        "SwCalprmPrototypes": "sw_calprm_prototypes",
        "SwClassPrototypes": "sw_class_prototypes",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_prototypes_id = Column(types.Integer, ForeignKey('sw_variable_prototypes.rid', use_alter=True))
    sw_variable_prototypes = relationship('SwVariablePrototypes', foreign_keys=[sw_variable_prototypes_id], uselist=False, cascade="all")
    sw_calprm_prototypes_id = Column(types.Integer, ForeignKey('sw_calprm_prototypes.rid', use_alter=True))
    sw_calprm_prototypes = relationship('SwCalprmPrototypes', foreign_keys=[sw_calprm_prototypes_id], uselist=False, cascade="all")
    sw_class_prototypes_id = Column(types.Integer, ForeignKey('sw_class_prototypes.rid', use_alter=True))
    sw_class_prototypes = relationship('SwClassPrototypes', foreign_keys=[sw_class_prototypes_id], uselist=False, cascade="all")

class SwClassPrototype(Base):

    __tablename__ = "sw_class_prototype"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwClassRef": "sw_class_ref",
        "SwArraysize": "sw_arraysize",
        "SwSyscond": "sw_syscond",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_class_ref_id = Column(types.Integer, ForeignKey('sw_class_ref.rid', use_alter=True))
    sw_class_ref = relationship('SwClassRef', foreign_keys=[sw_class_ref_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_syscond_id = Column(types.Integer, ForeignKey('sw_syscond.rid', use_alter=True))
    sw_syscond = relationship('SwSyscond', foreign_keys=[sw_syscond_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwVariablesRead(Base):

    __tablename__ = "sw_variables_read"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwVariableRefSyscond": "sw_variable_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")
    sw_variable_ref_syscond_id = Column(types.Integer, ForeignKey('sw_variable_ref_syscond.rid', use_alter=True))
    sw_variable_ref_syscond = relationship('SwVariableRefSyscond', foreign_keys=[sw_variable_ref_syscond_id], uselist=True, cascade="all")

class SwVariableImpls(Base):

    __tablename__ = "sw_variable_impls"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableImpl": "sw_variable_impl",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_impl_id = Column(types.Integer, ForeignKey('sw_variable_impl.rid', use_alter=True))
    sw_variable_impl = relationship('SwVariableImpl', foreign_keys=[sw_variable_impl_id], uselist=True, cascade="all")

class SwCalprmImpls(Base):

    __tablename__ = "sw_calprm_impls"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmImpl": "sw_calprm_impl",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_impl_id = Column(types.Integer, ForeignKey('sw_calprm_impl.rid', use_alter=True))
    sw_calprm_impl = relationship('SwCalprmImpl', foreign_keys=[sw_calprm_impl_id], uselist=True, cascade="all")

class SwVariablePrototypeRef(Base):

    __tablename__ = "sw_variable_prototype_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVariableImpl(Base):

    __tablename__ = "sw_variable_impl"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablePrototypeRef": "sw_variable_prototype_ref",
        "SwDataDefProps": "sw_data_def_props",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_prototype_ref_id = Column(types.Integer, ForeignKey('sw_variable_prototype_ref.rid', use_alter=True))
    sw_variable_prototype_ref = relationship('SwVariablePrototypeRef', foreign_keys=[sw_variable_prototype_ref_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")

class SwClassImpls(Base):

    __tablename__ = "sw_class_impls"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassImpl": "sw_class_impl",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_impl_id = Column(types.Integer, ForeignKey('sw_class_impl.rid', use_alter=True))
    sw_class_impl = relationship('SwClassImpl', foreign_keys=[sw_class_impl_id], uselist=True, cascade="all")

class SwCalprmPrototypeRef(Base):

    __tablename__ = "sw_calprm_prototype_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCalprmImpl(Base):

    __tablename__ = "sw_calprm_impl"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmPrototypeRef": "sw_calprm_prototype_ref",
        "SwDataDefProps": "sw_data_def_props",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_prototype_ref_id = Column(types.Integer, ForeignKey('sw_calprm_prototype_ref.rid', use_alter=True))
    sw_calprm_prototype_ref = relationship('SwCalprmPrototypeRef', foreign_keys=[sw_calprm_prototype_ref_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")

class SwClassAttrImpl(Base):

    __tablename__ = "sw_class_attr_impl"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwDataDefProps": "sw_data_def_props",
        "SwVariableImpls": "sw_variable_impls",
        "SwCalprmImpls": "sw_calprm_impls",
        "SwClassImpls": "sw_class_impls",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")
    sw_variable_impls_id = Column(types.Integer, ForeignKey('sw_variable_impls.rid', use_alter=True))
    sw_variable_impls = relationship('SwVariableImpls', foreign_keys=[sw_variable_impls_id], uselist=False, cascade="all")
    sw_calprm_impls_id = Column(types.Integer, ForeignKey('sw_calprm_impls.rid', use_alter=True))
    sw_calprm_impls = relationship('SwCalprmImpls', foreign_keys=[sw_calprm_impls_id], uselist=False, cascade="all")
    sw_class_impls_id = Column(types.Integer, ForeignKey('sw_class_impls.rid', use_alter=True))
    sw_class_impls = relationship('SwClassImpls', foreign_keys=[sw_class_impls_id], uselist=False, cascade="all")

class SwClassPrototypeRef(Base):

    __tablename__ = "sw_class_prototype_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwClassImpl(Base):

    __tablename__ = "sw_class_impl"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassPrototypeRef": "sw_class_prototype_ref",
        "SwClassAttrImplRef": "sw_class_attr_impl_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_prototype_ref_id = Column(types.Integer, ForeignKey('sw_class_prototype_ref.rid', use_alter=True))
    sw_class_prototype_ref = relationship('SwClassPrototypeRef', foreign_keys=[sw_class_prototype_ref_id], uselist=False, cascade="all")
    sw_class_attr_impl_ref_id = Column(types.Integer, ForeignKey('sw_class_attr_impl_ref.rid', use_alter=True))
    sw_class_attr_impl_ref = relationship('SwClassAttrImplRef', foreign_keys=[sw_class_attr_impl_ref_id], uselist=False, cascade="all")

class SwFeatureExportCalprms(Base):

    __tablename__ = "sw_feature_export_calprms"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": "sw_calprm_ref",
        "SwCalprmRefSyscond": "sw_calprm_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=True, cascade="all")
    sw_calprm_ref_syscond_id = Column(types.Integer, ForeignKey('sw_calprm_ref_syscond.rid', use_alter=True))
    sw_calprm_ref_syscond = relationship('SwCalprmRefSyscond', foreign_keys=[sw_calprm_ref_syscond_id], uselist=True, cascade="all")

class SwVariablesWrite(Base):

    __tablename__ = "sw_variables_write"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwVariableRefSyscond": "sw_variable_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")
    sw_variable_ref_syscond_id = Column(types.Integer, ForeignKey('sw_variable_ref_syscond.rid', use_alter=True))
    sw_variable_ref_syscond = relationship('SwVariableRefSyscond', foreign_keys=[sw_variable_ref_syscond_id], uselist=True, cascade="all")

class SwVariablesReadWrite(Base):

    __tablename__ = "sw_variables_read_write"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwVariableRefSyscond": "sw_variable_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")
    sw_variable_ref_syscond_id = Column(types.Integer, ForeignKey('sw_variable_ref_syscond.rid', use_alter=True))
    sw_variable_ref_syscond = relationship('SwVariableRefSyscond', foreign_keys=[sw_variable_ref_syscond_id], uselist=True, cascade="all")

class SwVariableRefSyscond(Base):

    __tablename__ = "sw_variable_ref_syscond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwSyscond": "sw_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=False, cascade="all")
    sw_syscond_id = Column(types.Integer, ForeignKey('sw_syscond.rid', use_alter=True))
    sw_syscond = relationship('SwSyscond', foreign_keys=[sw_syscond_id], uselist=False, cascade="all")

class SwFeatureExportVariables(Base):

    __tablename__ = "sw_feature_export_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesRead": "sw_variables_read",
        "SwVariablesWrite": "sw_variables_write",
        "SwVariablesReadWrite": "sw_variables_read_write",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variables_read_id = Column(types.Integer, ForeignKey('sw_variables_read.rid', use_alter=True))
    sw_variables_read = relationship('SwVariablesRead', foreign_keys=[sw_variables_read_id], uselist=False, cascade="all")
    sw_variables_write_id = Column(types.Integer, ForeignKey('sw_variables_write.rid', use_alter=True))
    sw_variables_write = relationship('SwVariablesWrite', foreign_keys=[sw_variables_write_id], uselist=False, cascade="all")
    sw_variables_read_write_id = Column(types.Integer, ForeignKey('sw_variables_read_write.rid', use_alter=True))
    sw_variables_read_write = relationship('SwVariablesReadWrite', foreign_keys=[sw_variables_read_write_id], uselist=False, cascade="all")

class SwFeatureImportVariables(Base):

    __tablename__ = "sw_feature_import_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesRead": "sw_variables_read",
        "SwVariablesWrite": "sw_variables_write",
        "SwVariablesReadWrite": "sw_variables_read_write",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variables_read_id = Column(types.Integer, ForeignKey('sw_variables_read.rid', use_alter=True))
    sw_variables_read = relationship('SwVariablesRead', foreign_keys=[sw_variables_read_id], uselist=False, cascade="all")
    sw_variables_write_id = Column(types.Integer, ForeignKey('sw_variables_write.rid', use_alter=True))
    sw_variables_write = relationship('SwVariablesWrite', foreign_keys=[sw_variables_write_id], uselist=False, cascade="all")
    sw_variables_read_write_id = Column(types.Integer, ForeignKey('sw_variables_read_write.rid', use_alter=True))
    sw_variables_read_write = relationship('SwVariablesReadWrite', foreign_keys=[sw_variables_read_write_id], uselist=False, cascade="all")

class SwFeatureLocalVariables(Base):

    __tablename__ = "sw_feature_local_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesReadWrite": "sw_variables_read_write",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variables_read_write_id = Column(types.Integer, ForeignKey('sw_variables_read_write.rid', use_alter=True))
    sw_variables_read_write = relationship('SwVariablesReadWrite', foreign_keys=[sw_variables_read_write_id], uselist=False, cascade="all")

class SwFeatureModelOnlyVariables(Base):

    __tablename__ = "sw_feature_model_only_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=True, cascade="all")

class SwFeatureVariables(Base):

    __tablename__ = "sw_feature_variables"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureExportVariables": "sw_feature_export_variables",
        "SwFeatureImportVariables": "sw_feature_import_variables",
        "SwFeatureLocalVariables": "sw_feature_local_variables",
        "SwFeatureModelOnlyVariables": "sw_feature_model_only_variables",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_export_variables_id = Column(types.Integer, ForeignKey('sw_feature_export_variables.rid', use_alter=True))
    sw_feature_export_variables = relationship('SwFeatureExportVariables', foreign_keys=[sw_feature_export_variables_id], uselist=False, cascade="all")
    sw_feature_import_variables_id = Column(types.Integer, ForeignKey('sw_feature_import_variables.rid', use_alter=True))
    sw_feature_import_variables = relationship('SwFeatureImportVariables', foreign_keys=[sw_feature_import_variables_id], uselist=False, cascade="all")
    sw_feature_local_variables_id = Column(types.Integer, ForeignKey('sw_feature_local_variables.rid', use_alter=True))
    sw_feature_local_variables = relationship('SwFeatureLocalVariables', foreign_keys=[sw_feature_local_variables_id], uselist=False, cascade="all")
    sw_feature_model_only_variables_id = Column(types.Integer, ForeignKey('sw_feature_model_only_variables.rid', use_alter=True))
    sw_feature_model_only_variables = relationship('SwFeatureModelOnlyVariables', foreign_keys=[sw_feature_model_only_variables_id], uselist=False, cascade="all")

class SwFeatureExportClassInstances(Base):

    __tablename__ = "sw_feature_export_class_instances"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": "sw_class_instance_ref",
        "SwInstanceRefSyscond": "sw_instance_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_instance_ref_id = Column(types.Integer, ForeignKey('sw_class_instance_ref.rid', use_alter=True))
    sw_class_instance_ref = relationship('SwClassInstanceRef', foreign_keys=[sw_class_instance_ref_id], uselist=True, cascade="all")
    sw_instance_ref_syscond_id = Column(types.Integer, ForeignKey('sw_instance_ref_syscond.rid', use_alter=True))
    sw_instance_ref_syscond = relationship('SwInstanceRefSyscond', foreign_keys=[sw_instance_ref_syscond_id], uselist=True, cascade="all")

class SwFeatureImportCalprms(Base):

    __tablename__ = "sw_feature_import_calprms"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": "sw_calprm_ref",
        "SwCalprmRefSyscond": "sw_calprm_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=True, cascade="all")
    sw_calprm_ref_syscond_id = Column(types.Integer, ForeignKey('sw_calprm_ref_syscond.rid', use_alter=True))
    sw_calprm_ref_syscond = relationship('SwCalprmRefSyscond', foreign_keys=[sw_calprm_ref_syscond_id], uselist=True, cascade="all")

class SwCalprmRefSyscond(Base):

    __tablename__ = "sw_calprm_ref_syscond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": "sw_calprm_ref",
        "SwSyscond": "sw_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=False, cascade="all")
    sw_syscond_id = Column(types.Integer, ForeignKey('sw_syscond.rid', use_alter=True))
    sw_syscond = relationship('SwSyscond', foreign_keys=[sw_syscond_id], uselist=False, cascade="all")

class SwFeatureLocalParams(Base):

    __tablename__ = "sw_feature_local_params"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": "sw_calprm_ref",
        "SwCalprmRefSyscond": "sw_calprm_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=True, cascade="all")
    sw_calprm_ref_syscond_id = Column(types.Integer, ForeignKey('sw_calprm_ref_syscond.rid', use_alter=True))
    sw_calprm_ref_syscond = relationship('SwCalprmRefSyscond', foreign_keys=[sw_calprm_ref_syscond_id], uselist=True, cascade="all")

class SwFeatureParams(Base):

    __tablename__ = "sw_feature_params"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureExportCalprms": "sw_feature_export_calprms",
        "SwFeatureImportCalprms": "sw_feature_import_calprms",
        "SwFeatureLocalParams": "sw_feature_local_params",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_export_calprms_id = Column(types.Integer, ForeignKey('sw_feature_export_calprms.rid', use_alter=True))
    sw_feature_export_calprms = relationship('SwFeatureExportCalprms', foreign_keys=[sw_feature_export_calprms_id], uselist=False, cascade="all")
    sw_feature_import_calprms_id = Column(types.Integer, ForeignKey('sw_feature_import_calprms.rid', use_alter=True))
    sw_feature_import_calprms = relationship('SwFeatureImportCalprms', foreign_keys=[sw_feature_import_calprms_id], uselist=False, cascade="all")
    sw_feature_local_params_id = Column(types.Integer, ForeignKey('sw_feature_local_params.rid', use_alter=True))
    sw_feature_local_params = relationship('SwFeatureLocalParams', foreign_keys=[sw_feature_local_params_id], uselist=False, cascade="all")

class SwTestDesc(Base):

    __tablename__ = "sw_test_desc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwFeatureImportClassInstances(Base):

    __tablename__ = "sw_feature_import_class_instances"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": "sw_class_instance_ref",
        "SwInstanceRefSyscond": "sw_instance_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_instance_ref_id = Column(types.Integer, ForeignKey('sw_class_instance_ref.rid', use_alter=True))
    sw_class_instance_ref = relationship('SwClassInstanceRef', foreign_keys=[sw_class_instance_ref_id], uselist=True, cascade="all")
    sw_instance_ref_syscond_id = Column(types.Integer, ForeignKey('sw_instance_ref_syscond.rid', use_alter=True))
    sw_instance_ref_syscond = relationship('SwInstanceRefSyscond', foreign_keys=[sw_instance_ref_syscond_id], uselist=True, cascade="all")

class SwClassInstanceRef(Base):

    __tablename__ = "sw_class_instance_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwInstanceRefSyscond(Base):

    __tablename__ = "sw_instance_ref_syscond"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": "sw_class_instance_ref",
        "SwSyscond": "sw_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_instance_ref_id = Column(types.Integer, ForeignKey('sw_class_instance_ref.rid', use_alter=True))
    sw_class_instance_ref = relationship('SwClassInstanceRef', foreign_keys=[sw_class_instance_ref_id], uselist=False, cascade="all")
    sw_syscond_id = Column(types.Integer, ForeignKey('sw_syscond.rid', use_alter=True))
    sw_syscond = relationship('SwSyscond', foreign_keys=[sw_syscond_id], uselist=False, cascade="all")

class SwFeatureLocalClassInstances(Base):

    __tablename__ = "sw_feature_local_class_instances"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": "sw_class_instance_ref",
        "SwInstanceRefSyscond": "sw_instance_ref_syscond",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_instance_ref_id = Column(types.Integer, ForeignKey('sw_class_instance_ref.rid', use_alter=True))
    sw_class_instance_ref = relationship('SwClassInstanceRef', foreign_keys=[sw_class_instance_ref_id], uselist=True, cascade="all")
    sw_instance_ref_syscond_id = Column(types.Integer, ForeignKey('sw_instance_ref_syscond.rid', use_alter=True))
    sw_instance_ref_syscond = relationship('SwInstanceRefSyscond', foreign_keys=[sw_instance_ref_syscond_id], uselist=True, cascade="all")

class SwFeatureClassInstances(Base):

    __tablename__ = "sw_feature_class_instances"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureExportClassInstances": "sw_feature_export_class_instances",
        "SwFeatureImportClassInstances": "sw_feature_import_class_instances",
        "SwFeatureLocalClassInstances": "sw_feature_local_class_instances",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_export_class_instances_id = Column(types.Integer, ForeignKey('sw_feature_export_class_instances.rid', use_alter=True))
    sw_feature_export_class_instances = relationship('SwFeatureExportClassInstances', foreign_keys=[sw_feature_export_class_instances_id], uselist=False, cascade="all")
    sw_feature_import_class_instances_id = Column(types.Integer, ForeignKey('sw_feature_import_class_instances.rid', use_alter=True))
    sw_feature_import_class_instances = relationship('SwFeatureImportClassInstances', foreign_keys=[sw_feature_import_class_instances_id], uselist=False, cascade="all")
    sw_feature_local_class_instances_id = Column(types.Integer, ForeignKey('sw_feature_local_class_instances.rid', use_alter=True))
    sw_feature_local_class_instances = relationship('SwFeatureLocalClassInstances', foreign_keys=[sw_feature_local_class_instances_id], uselist=False, cascade="all")

class SwApplicationNotes(Base):

    __tablename__ = "sw_application_notes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwMaintenanceNotes(Base):

    __tablename__ = "sw_maintenance_notes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwCarbDoc(Base):

    __tablename__ = "sw_carb_doc"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SwClass(Base):

    __tablename__ = "sw_class"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwFeatureDef": "sw_feature_def",
        "SwFeatureDesc": "sw_feature_desc",
        "SwFulfils": "sw_fulfils",
        "SwClassMethods": "sw_class_methods",
        "SwClassAttr": "sw_class_attr",
        "SwClassAttrImpls": "sw_class_attr_impls",
        "SwDataDefProps": "sw_data_def_props",
        "SwFeatureVariables": "sw_feature_variables",
        "SwFeatureParams": "sw_feature_params",
        "SwFeatureClassInstances": "sw_feature_class_instances",
        "SwTestDesc": "sw_test_desc",
        "SwApplicationNotes": "sw_application_notes",
        "SwMaintenanceNotes": "sw_maintenance_notes",
        "SwCarbDoc": "sw_carb_doc",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_feature_def_id = Column(types.Integer, ForeignKey('sw_feature_def.rid', use_alter=True))
    sw_feature_def = relationship('SwFeatureDef', foreign_keys=[sw_feature_def_id], uselist=False, cascade="all")
    sw_feature_desc_id = Column(types.Integer, ForeignKey('sw_feature_desc.rid', use_alter=True))
    sw_feature_desc = relationship('SwFeatureDesc', foreign_keys=[sw_feature_desc_id], uselist=False, cascade="all")
    sw_fulfils_id = Column(types.Integer, ForeignKey('sw_fulfils.rid', use_alter=True))
    sw_fulfils = relationship('SwFulfils', foreign_keys=[sw_fulfils_id], uselist=False, cascade="all")
    sw_class_methods_id = Column(types.Integer, ForeignKey('sw_class_methods.rid', use_alter=True))
    sw_class_methods = relationship('SwClassMethods', foreign_keys=[sw_class_methods_id], uselist=False, cascade="all")
    sw_class_attr_id = Column(types.Integer, ForeignKey('sw_class_attr.rid', use_alter=True))
    sw_class_attr = relationship('SwClassAttr', foreign_keys=[sw_class_attr_id], uselist=False, cascade="all")
    sw_class_attr_impls_id = Column(types.Integer, ForeignKey('sw_class_attr_impls.rid', use_alter=True))
    sw_class_attr_impls = relationship('SwClassAttrImpls', foreign_keys=[sw_class_attr_impls_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")
    sw_feature_variables_id = Column(types.Integer, ForeignKey('sw_feature_variables.rid', use_alter=True))
    sw_feature_variables = relationship('SwFeatureVariables', foreign_keys=[sw_feature_variables_id], uselist=False, cascade="all")
    sw_feature_params_id = Column(types.Integer, ForeignKey('sw_feature_params.rid', use_alter=True))
    sw_feature_params = relationship('SwFeatureParams', foreign_keys=[sw_feature_params_id], uselist=False, cascade="all")
    sw_feature_class_instances_id = Column(types.Integer, ForeignKey('sw_feature_class_instances.rid', use_alter=True))
    sw_feature_class_instances = relationship('SwFeatureClassInstances', foreign_keys=[sw_feature_class_instances_id], uselist=False, cascade="all")
    sw_test_desc_id = Column(types.Integer, ForeignKey('sw_test_desc.rid', use_alter=True))
    sw_test_desc = relationship('SwTestDesc', foreign_keys=[sw_test_desc_id], uselist=False, cascade="all")
    sw_application_notes_id = Column(types.Integer, ForeignKey('sw_application_notes.rid', use_alter=True))
    sw_application_notes = relationship('SwApplicationNotes', foreign_keys=[sw_application_notes_id], uselist=False, cascade="all")
    sw_maintenance_notes_id = Column(types.Integer, ForeignKey('sw_maintenance_notes.rid', use_alter=True))
    sw_maintenance_notes = relationship('SwMaintenanceNotes', foreign_keys=[sw_maintenance_notes_id], uselist=False, cascade="all")
    sw_carb_doc_id = Column(types.Integer, ForeignKey('sw_carb_doc.rid', use_alter=True))
    sw_carb_doc = relationship('SwCarbDoc', foreign_keys=[sw_carb_doc_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwFeatureDesignData(Base):

    __tablename__ = "sw_feature_design_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesRead": "sw_variables_read",
        "SwVariablesWrite": "sw_variables_write",
        "SwVariablesReadWrite": "sw_variables_read_write",
        "SwFeatureLocalParams": "sw_feature_local_params",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variables_read_id = Column(types.Integer, ForeignKey('sw_variables_read.rid', use_alter=True))
    sw_variables_read = relationship('SwVariablesRead', foreign_keys=[sw_variables_read_id], uselist=False, cascade="all")
    sw_variables_write_id = Column(types.Integer, ForeignKey('sw_variables_write.rid', use_alter=True))
    sw_variables_write = relationship('SwVariablesWrite', foreign_keys=[sw_variables_write_id], uselist=False, cascade="all")
    sw_variables_read_write_id = Column(types.Integer, ForeignKey('sw_variables_read_write.rid', use_alter=True))
    sw_variables_read_write = relationship('SwVariablesReadWrite', foreign_keys=[sw_variables_read_write_id], uselist=False, cascade="all")
    sw_feature_local_params_id = Column(types.Integer, ForeignKey('sw_feature_local_params.rid', use_alter=True))
    sw_feature_local_params = relationship('SwFeatureLocalParams', foreign_keys=[sw_feature_local_params_id], uselist=False, cascade="all")

class SwEffectFlows(Base):

    __tablename__ = "sw_effect_flows"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwEffectFlow": "sw_effect_flow",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_effect_flow_id = Column(types.Integer, ForeignKey('sw_effect_flow.rid', use_alter=True))
    sw_effect_flow = relationship('SwEffectFlow', foreign_keys=[sw_effect_flow_id], uselist=True, cascade="all")

class SwSystemconstRefs(Base):

    __tablename__ = "sw_systemconst_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstRef": "sw_systemconst_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_systemconst_ref_id = Column(types.Integer, ForeignKey('sw_systemconst_ref.rid', use_alter=True))
    sw_systemconst_ref = relationship('SwSystemconstRef', foreign_keys=[sw_systemconst_ref_id], uselist=True, cascade="all")

class SwEffectFlow(Base):

    __tablename__ = "sw_effect_flow"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwEffectingVariable": "sw_effecting_variable",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=False, cascade="all")
    sw_effecting_variable_id = Column(types.Integer, ForeignKey('sw_effecting_variable.rid', use_alter=True))
    sw_effecting_variable = relationship('SwEffectingVariable', foreign_keys=[sw_effecting_variable_id], uselist=True, cascade="all")

class SwEffectingVariable(Base):

    __tablename__ = "sw_effecting_variable"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": "sw_variable_ref",
        "SwEffect": "sw_effect",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=False, cascade="all")
    sw_effect_id = Column(types.Integer, ForeignKey('sw_effect.rid', use_alter=True))
    sw_effect = relationship('SwEffect', foreign_keys=[sw_effect_id], uselist=True, cascade="all")

class SwEffect(Base):

    __tablename__ = "sw_effect"
    ATTRIBUTES = {
        "ORIGIN": "origin",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    origin = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwFeatureDecomposition(Base):

    __tablename__ = "sw_feature_decomposition"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSubcomponent": "sw_subcomponent",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_subcomponent_id = Column(types.Integer, ForeignKey('sw_subcomponent.rid', use_alter=True))
    sw_subcomponent = relationship('SwSubcomponent', foreign_keys=[sw_subcomponent_id], uselist=True, cascade="all")

class SwSystemconstRef(Base):

    __tablename__ = "sw_systemconst_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwFeature(Base):

    __tablename__ = "sw_feature"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwFeatureDef": "sw_feature_def",
        "SwFeatureDesc": "sw_feature_desc",
        "SwFulfils": "sw_fulfils",
        "SwFeatureDesignData": "sw_feature_design_data",
        "SwEffectFlows": "sw_effect_flows",
        "SwFeatureVariables": "sw_feature_variables",
        "SwFeatureParams": "sw_feature_params",
        "SwFeatureClassInstances": "sw_feature_class_instances",
        "SwSystemconstRefs": "sw_systemconst_refs",
        "SwDataDictionarySpec": "sw_data_dictionary_spec",
        "SwTestDesc": "sw_test_desc",
        "SwApplicationNotes": "sw_application_notes",
        "SwMaintenanceNotes": "sw_maintenance_notes",
        "SwCarbDoc": "sw_carb_doc",
        "SwFeatureDecomposition": "sw_feature_decomposition",
        "Annotations": "annotations",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_feature_def_id = Column(types.Integer, ForeignKey('sw_feature_def.rid', use_alter=True))
    sw_feature_def = relationship('SwFeatureDef', foreign_keys=[sw_feature_def_id], uselist=False, cascade="all")
    sw_feature_desc_id = Column(types.Integer, ForeignKey('sw_feature_desc.rid', use_alter=True))
    sw_feature_desc = relationship('SwFeatureDesc', foreign_keys=[sw_feature_desc_id], uselist=False, cascade="all")
    sw_fulfils_id = Column(types.Integer, ForeignKey('sw_fulfils.rid', use_alter=True))
    sw_fulfils = relationship('SwFulfils', foreign_keys=[sw_fulfils_id], uselist=False, cascade="all")
    sw_feature_design_data_id = Column(types.Integer, ForeignKey('sw_feature_design_data.rid', use_alter=True))
    sw_feature_design_data = relationship('SwFeatureDesignData', foreign_keys=[sw_feature_design_data_id], uselist=False, cascade="all")
    sw_effect_flows_id = Column(types.Integer, ForeignKey('sw_effect_flows.rid', use_alter=True))
    sw_effect_flows = relationship('SwEffectFlows', foreign_keys=[sw_effect_flows_id], uselist=False, cascade="all")
    sw_feature_variables_id = Column(types.Integer, ForeignKey('sw_feature_variables.rid', use_alter=True))
    sw_feature_variables = relationship('SwFeatureVariables', foreign_keys=[sw_feature_variables_id], uselist=False, cascade="all")
    sw_feature_params_id = Column(types.Integer, ForeignKey('sw_feature_params.rid', use_alter=True))
    sw_feature_params = relationship('SwFeatureParams', foreign_keys=[sw_feature_params_id], uselist=False, cascade="all")
    sw_feature_class_instances_id = Column(types.Integer, ForeignKey('sw_feature_class_instances.rid', use_alter=True))
    sw_feature_class_instances = relationship('SwFeatureClassInstances', foreign_keys=[sw_feature_class_instances_id], uselist=False, cascade="all")
    sw_systemconst_refs_id = Column(types.Integer, ForeignKey('sw_systemconst_refs.rid', use_alter=True))
    sw_systemconst_refs = relationship('SwSystemconstRefs', foreign_keys=[sw_systemconst_refs_id], uselist=False, cascade="all")
    sw_data_dictionary_spec_id = Column(types.Integer, ForeignKey('sw_data_dictionary_spec.rid', use_alter=True))
    sw_data_dictionary_spec = relationship('SwDataDictionarySpec', foreign_keys=[sw_data_dictionary_spec_id], uselist=False, cascade="all")
    sw_test_desc_id = Column(types.Integer, ForeignKey('sw_test_desc.rid', use_alter=True))
    sw_test_desc = relationship('SwTestDesc', foreign_keys=[sw_test_desc_id], uselist=False, cascade="all")
    sw_application_notes_id = Column(types.Integer, ForeignKey('sw_application_notes.rid', use_alter=True))
    sw_application_notes = relationship('SwApplicationNotes', foreign_keys=[sw_application_notes_id], uselist=False, cascade="all")
    sw_maintenance_notes_id = Column(types.Integer, ForeignKey('sw_maintenance_notes.rid', use_alter=True))
    sw_maintenance_notes = relationship('SwMaintenanceNotes', foreign_keys=[sw_maintenance_notes_id], uselist=False, cascade="all")
    sw_carb_doc_id = Column(types.Integer, ForeignKey('sw_carb_doc.rid', use_alter=True))
    sw_carb_doc = relationship('SwCarbDoc', foreign_keys=[sw_carb_doc_id], uselist=False, cascade="all")
    sw_feature_decomposition_id = Column(types.Integer, ForeignKey('sw_feature_decomposition.rid', use_alter=True))
    sw_feature_decomposition = relationship('SwFeatureDecomposition', foreign_keys=[sw_feature_decomposition_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwFeatureRef(Base):

    __tablename__ = "sw_feature_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwProcesses(Base):

    __tablename__ = "sw_processes"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwProcess": "sw_process",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_process_id = Column(types.Integer, ForeignKey('sw_process.rid', use_alter=True))
    sw_process = relationship('SwProcess', foreign_keys=[sw_process_id], uselist=True, cascade="all")

class SwSubcomponent(Base):

    __tablename__ = "sw_subcomponent"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRef": "sw_feature_ref",
        "SwProcesses": "sw_processes",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_ref_id = Column(types.Integer, ForeignKey('sw_feature_ref.rid', use_alter=True))
    sw_feature_ref = relationship('SwFeatureRef', foreign_keys=[sw_feature_ref_id], uselist=False, cascade="all")
    sw_processes_id = Column(types.Integer, ForeignKey('sw_processes.rid', use_alter=True))
    sw_processes = relationship('SwProcesses', foreign_keys=[sw_processes_id], uselist=False, cascade="all")

class SwProcess(Base):

    __tablename__ = "sw_process"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "ShortLabel": "short_label",
        "SwTaskRef": "sw_task_ref",
        "Desc": "_desc",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    short_label_id = Column(types.Integer, ForeignKey('short_label.rid', use_alter=True))
    short_label = relationship('ShortLabel', foreign_keys=[short_label_id], uselist=False, cascade="all")
    sw_task_ref_id = Column(types.Integer, ForeignKey('sw_task_ref.rid', use_alter=True))
    sw_task_ref = relationship('SwTaskRef', foreign_keys=[sw_task_ref_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")

class SwComponentSpec(Base):

    __tablename__ = "sw_component_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwComponents": "sw_components",
        "SwRootFeatures": "sw_root_features",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_components_id = Column(types.Integer, ForeignKey('sw_components.rid', use_alter=True))
    sw_components = relationship('SwComponents', foreign_keys=[sw_components_id], uselist=False, cascade="all")
    sw_root_features_id = Column(types.Integer, ForeignKey('sw_root_features.rid', use_alter=True))
    sw_root_features = relationship('SwRootFeatures', foreign_keys=[sw_root_features_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwCollections(Base):

    __tablename__ = "sw_collections"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollection": "sw_collection",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_id = Column(types.Integer, ForeignKey('sw_collection.rid', use_alter=True))
    sw_collection = relationship('SwCollection', foreign_keys=[sw_collection_id], uselist=True, cascade="all")

class DisplayName(Base):

    __tablename__ = "display_name"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class Flag(Base):

    __tablename__ = "flag"
    ATTRIBUTES = {
        "Value": "value",
        "S": "s",
        "SI": "si",
        "C": "c",
        "LC": "lc",
        "VIEW": "_view",
        "T": "t",
        "TI": "ti",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    s = StdString()
    si = StdString()
    c = StdString()
    lc = StdString()
    _view = StdString()
    t = StdString()
    ti = StdString()

class Revision(Base):

    __tablename__ = "revision"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "SYSCOND": "syscond",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    syscond = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwCollectionRef(Base):

    __tablename__ = "sw_collection_ref"
    ATTRIBUTES = {
        "INVERT": "invert",
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "invert": ['INVERT', 'NO-INVERT'],
    }
    TERMINAL = True
    invert = StdString()
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsCollections(Base):

    __tablename__ = "sw_cs_collections"
    ATTRIBUTES = {
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "SwCsCollection": "sw_cs_collection",
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    sw_cs_collection_id = Column(types.Integer, ForeignKey('sw_cs_collection.rid', use_alter=True))
    sw_cs_collection = relationship('SwCsCollection', foreign_keys=[sw_cs_collection_id], uselist=True, cascade="all")

class SymbolicFile(Base):

    __tablename__ = "symbolic_file"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwCsHistory(Base):

    __tablename__ = "sw_cs_history"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CsEntry": "cs_entry",
        "SwCsEntry": "sw_cs_entry",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    cs_entry_id = Column(types.Integer, ForeignKey('cs_entry.rid', use_alter=True))
    cs_entry = relationship('CsEntry', foreign_keys=[cs_entry_id], uselist=True, cascade="all")
    sw_cs_entry_id = Column(types.Integer, ForeignKey('sw_cs_entry.rid', use_alter=True))
    sw_cs_entry = relationship('SwCsEntry', foreign_keys=[sw_cs_entry_id], uselist=True, cascade="all")

class Csus(Base):

    __tablename__ = "csus"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwCsState(Base):

    __tablename__ = "sw_cs_state"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsContext(Base):

    __tablename__ = "sw_cs_context"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsProjectInfo(Base):

    __tablename__ = "sw_cs_project_info"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsTargetVariant(Base):

    __tablename__ = "sw_cs_target_variant"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsTestObject(Base):

    __tablename__ = "sw_cs_test_object"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsProgramIdentifier(Base):

    __tablename__ = "sw_cs_program_identifier"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsDataIdentifier(Base):

    __tablename__ = "sw_cs_data_identifier"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCsPerformedBy(Base):

    __tablename__ = "sw_cs_performed_by"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Cspr(Base):

    __tablename__ = "cspr"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwCsField(Base):

    __tablename__ = "sw_cs_field"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwVcdCriterionValues(Base):

    __tablename__ = "sw_vcd_criterion_values"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterionValue": "sw_vcd_criterion_value",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_vcd_criterion_value_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_value.rid', use_alter=True))
    sw_vcd_criterion_value = relationship('SwVcdCriterionValue', foreign_keys=[sw_vcd_criterion_value_id], uselist=True, cascade="all")

class SwVcdCriterionValue(Base):

    __tablename__ = "sw_vcd_criterion_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterionRef": "sw_vcd_criterion_ref",
        "Vt": "vt",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_vcd_criterion_ref_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_ref.rid', use_alter=True))
    sw_vcd_criterion_ref = relationship('SwVcdCriterionRef', foreign_keys=[sw_vcd_criterion_ref_id], uselist=False, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=False, cascade="all")

class UnitDisplayName(Base):

    __tablename__ = "unit_display_name"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
        "space": "space",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "space": ['default', 'preserve'],
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    space = StdString()

class SwValueCont(Base):

    __tablename__ = "sw_value_cont"
    ATTRIBUTES = {
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "UnitDisplayName": "unit_display_name",
        "SwArraysize": "sw_arraysize",
        "SwValuesPhys": "sw_values_phys",
        "SwValuesCoded": "sw_values_coded",
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    unit_display_name_id = Column(types.Integer, ForeignKey('unit_display_name.rid', use_alter=True))
    unit_display_name = relationship('UnitDisplayName', foreign_keys=[unit_display_name_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_values_phys_id = Column(types.Integer, ForeignKey('sw_values_phys.rid', use_alter=True))
    sw_values_phys = relationship('SwValuesPhys', foreign_keys=[sw_values_phys_id], uselist=False, cascade="all")
    sw_values_coded_id = Column(types.Integer, ForeignKey('sw_values_coded.rid', use_alter=True))
    sw_values_coded = relationship('SwValuesCoded', foreign_keys=[sw_values_coded_id], uselist=False, cascade="all")

class SwModelLink(Base):

    __tablename__ = "sw_model_link"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "F-ID-CLASS": "f_id_class",
        "SPACE": "space",
        "ID-REF": "id_ref",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    f_id_class = StdString()
    space = StdString()
    id_ref = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwArrayIndex(Base):

    __tablename__ = "sw_array_index"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAxisConts(Base):

    __tablename__ = "sw_axis_conts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisCont": "sw_axis_cont",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_axis_cont_id = Column(types.Integer, ForeignKey('sw_axis_cont.rid', use_alter=True))
    sw_axis_cont = relationship('SwAxisCont', foreign_keys=[sw_axis_cont_id], uselist=True, cascade="all")

class SwInstancePropsVariants(Base):

    __tablename__ = "sw_instance_props_variants"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwInstancePropsVariant": "sw_instance_props_variant",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_instance_props_variant_id = Column(types.Integer, ForeignKey('sw_instance_props_variant.rid', use_alter=True))
    sw_instance_props_variant = relationship('SwInstancePropsVariant', foreign_keys=[sw_instance_props_variant_id], uselist=True, cascade="all")

class SwCsFlags(Base):

    __tablename__ = "sw_cs_flags"
    ATTRIBUTES = {
        "S": "s",
        "SI": "si",
        "C": "c",
        "LC": "lc",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "SwCsFlag": "sw_cs_flag",
    }
    s = StdString()
    si = StdString()
    c = StdString()
    lc = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    sw_cs_flag_id = Column(types.Integer, ForeignKey('sw_cs_flag.rid', use_alter=True))
    sw_cs_flag = relationship('SwCsFlag', foreign_keys=[sw_cs_flag_id], uselist=True, cascade="all")

class SwAddrInfos(Base):

    __tablename__ = "sw_addr_infos"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAddrInfo": "sw_addr_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_addr_info_id = Column(types.Integer, ForeignKey('sw_addr_info.rid', use_alter=True))
    sw_addr_info = relationship('SwAddrInfo', foreign_keys=[sw_addr_info_id], uselist=True, cascade="all")

class SwBaseAddr(Base):

    __tablename__ = "sw_base_addr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAddrOffset(Base):

    __tablename__ = "sw_addr_offset"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Csdi(Base):

    __tablename__ = "csdi"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class Cspi(Base):

    __tablename__ = "cspi"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class Cswp(Base):

    __tablename__ = "cswp"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class Csto(Base):

    __tablename__ = "csto"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class Cstv(Base):

    __tablename__ = "cstv"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwCsEntry(Base):

    __tablename__ = "sw_cs_entry"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCsState": "sw_cs_state",
        "State": "state",
        "SwCsContext": "sw_cs_context",
        "SwCsProjectInfo": "sw_cs_project_info",
        "SwCsTargetVariant": "sw_cs_target_variant",
        "SwCsTestObject": "sw_cs_test_object",
        "SwCsProgramIdentifier": "sw_cs_program_identifier",
        "SwCsDataIdentifier": "sw_cs_data_identifier",
        "SwCsPerformedBy": "sw_cs_performed_by",
        "Csus": "csus",
        "Cspr": "cspr",
        "Cswp": "cswp",
        "Csto": "csto",
        "Cstv": "cstv",
        "Cspi": "cspi",
        "Csdi": "csdi",
        "Remark": "remark",
        "Date": "date",
        "Sd": "sd",
        "SwCsField": "sw_cs_field",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_cs_state_id = Column(types.Integer, ForeignKey('sw_cs_state.rid', use_alter=True))
    sw_cs_state = relationship('SwCsState', foreign_keys=[sw_cs_state_id], uselist=False, cascade="all")
    state_id = Column(types.Integer, ForeignKey('state.rid', use_alter=True))
    state = relationship('State', foreign_keys=[state_id], uselist=False, cascade="all")
    sw_cs_context_id = Column(types.Integer, ForeignKey('sw_cs_context.rid', use_alter=True))
    sw_cs_context = relationship('SwCsContext', foreign_keys=[sw_cs_context_id], uselist=False, cascade="all")
    sw_cs_project_info_id = Column(types.Integer, ForeignKey('sw_cs_project_info.rid', use_alter=True))
    sw_cs_project_info = relationship('SwCsProjectInfo', foreign_keys=[sw_cs_project_info_id], uselist=False, cascade="all")
    sw_cs_target_variant_id = Column(types.Integer, ForeignKey('sw_cs_target_variant.rid', use_alter=True))
    sw_cs_target_variant = relationship('SwCsTargetVariant', foreign_keys=[sw_cs_target_variant_id], uselist=False, cascade="all")
    sw_cs_test_object_id = Column(types.Integer, ForeignKey('sw_cs_test_object.rid', use_alter=True))
    sw_cs_test_object = relationship('SwCsTestObject', foreign_keys=[sw_cs_test_object_id], uselist=False, cascade="all")
    sw_cs_program_identifier_id = Column(types.Integer, ForeignKey('sw_cs_program_identifier.rid', use_alter=True))
    sw_cs_program_identifier = relationship('SwCsProgramIdentifier', foreign_keys=[sw_cs_program_identifier_id], uselist=False, cascade="all")
    sw_cs_data_identifier_id = Column(types.Integer, ForeignKey('sw_cs_data_identifier.rid', use_alter=True))
    sw_cs_data_identifier = relationship('SwCsDataIdentifier', foreign_keys=[sw_cs_data_identifier_id], uselist=False, cascade="all")
    sw_cs_performed_by_id = Column(types.Integer, ForeignKey('sw_cs_performed_by.rid', use_alter=True))
    sw_cs_performed_by = relationship('SwCsPerformedBy', foreign_keys=[sw_cs_performed_by_id], uselist=False, cascade="all")
    csus_id = Column(types.Integer, ForeignKey('csus.rid', use_alter=True))
    csus = relationship('Csus', foreign_keys=[csus_id], uselist=False, cascade="all")
    cspr_id = Column(types.Integer, ForeignKey('cspr.rid', use_alter=True))
    cspr = relationship('Cspr', foreign_keys=[cspr_id], uselist=False, cascade="all")
    cswp_id = Column(types.Integer, ForeignKey('cswp.rid', use_alter=True))
    cswp = relationship('Cswp', foreign_keys=[cswp_id], uselist=False, cascade="all")
    csto_id = Column(types.Integer, ForeignKey('csto.rid', use_alter=True))
    csto = relationship('Csto', foreign_keys=[csto_id], uselist=False, cascade="all")
    cstv_id = Column(types.Integer, ForeignKey('cstv.rid', use_alter=True))
    cstv = relationship('Cstv', foreign_keys=[cstv_id], uselist=False, cascade="all")
    cspi_id = Column(types.Integer, ForeignKey('cspi.rid', use_alter=True))
    cspi = relationship('Cspi', foreign_keys=[cspi_id], uselist=False, cascade="all")
    csdi_id = Column(types.Integer, ForeignKey('csdi.rid', use_alter=True))
    csdi = relationship('Csdi', foreign_keys=[csdi_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")
    date_id = Column(types.Integer, ForeignKey('date.rid', use_alter=True))
    date = relationship('Date', foreign_keys=[date_id], uselist=False, cascade="all")
    sd_id = Column(types.Integer, ForeignKey('sd.rid', use_alter=True))
    sd = relationship('Sd', foreign_keys=[sd_id], uselist=True, cascade="all")
    sw_cs_field_id = Column(types.Integer, ForeignKey('sw_cs_field.rid', use_alter=True))
    sw_cs_field = relationship('SwCsField', foreign_keys=[sw_cs_field_id], uselist=True, cascade="all")

class CsEntry(Base):

    __tablename__ = "cs_entry"
    ATTRIBUTES = {
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "State": "state",
        "Date": "date",
        "Csus": "csus",
        "Cspr": "cspr",
        "Cswp": "cswp",
        "Csto": "csto",
        "Cstv": "cstv",
        "Cspi": "cspi",
        "Csdi": "csdi",
        "Remark": "remark",
        "Sd": "sd",
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    state_id = Column(types.Integer, ForeignKey('state.rid', use_alter=True))
    state = relationship('State', foreign_keys=[state_id], uselist=False, cascade="all")
    date_id = Column(types.Integer, ForeignKey('date.rid', use_alter=True))
    date = relationship('Date', foreign_keys=[date_id], uselist=False, cascade="all")
    csus_id = Column(types.Integer, ForeignKey('csus.rid', use_alter=True))
    csus = relationship('Csus', foreign_keys=[csus_id], uselist=False, cascade="all")
    cspr_id = Column(types.Integer, ForeignKey('cspr.rid', use_alter=True))
    cspr = relationship('Cspr', foreign_keys=[cspr_id], uselist=False, cascade="all")
    cswp_id = Column(types.Integer, ForeignKey('cswp.rid', use_alter=True))
    cswp = relationship('Cswp', foreign_keys=[cswp_id], uselist=False, cascade="all")
    csto_id = Column(types.Integer, ForeignKey('csto.rid', use_alter=True))
    csto = relationship('Csto', foreign_keys=[csto_id], uselist=False, cascade="all")
    cstv_id = Column(types.Integer, ForeignKey('cstv.rid', use_alter=True))
    cstv = relationship('Cstv', foreign_keys=[cstv_id], uselist=False, cascade="all")
    cspi_id = Column(types.Integer, ForeignKey('cspi.rid', use_alter=True))
    cspi = relationship('Cspi', foreign_keys=[cspi_id], uselist=False, cascade="all")
    csdi_id = Column(types.Integer, ForeignKey('csdi.rid', use_alter=True))
    csdi = relationship('Csdi', foreign_keys=[csdi_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")
    sd_id = Column(types.Integer, ForeignKey('sd.rid', use_alter=True))
    sd = relationship('Sd', foreign_keys=[sd_id], uselist=True, cascade="all")

class SwCsFlag(Base):

    __tablename__ = "sw_cs_flag"
    ATTRIBUTES = {
        "C": "c",
        "LC": "lc",
        "T": "t",
        "TI": "ti",
        "S": "s",
        "SI": "si",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "Category": "category",
        "Flag": "flag",
        "Csus": "csus",
        "Date": "date",
        "Remark": "remark",
    }
    c = StdString()
    lc = StdString()
    t = StdString()
    ti = StdString()
    s = StdString()
    si = StdString()
    _view = StdString()
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    flag_id = Column(types.Integer, ForeignKey('flag.rid', use_alter=True))
    flag = relationship('Flag', foreign_keys=[flag_id], uselist=False, cascade="all")
    csus_id = Column(types.Integer, ForeignKey('csus.rid', use_alter=True))
    csus = relationship('Csus', foreign_keys=[csus_id], uselist=False, cascade="all")
    date_id = Column(types.Integer, ForeignKey('date.rid', use_alter=True))
    date = relationship('Date', foreign_keys=[date_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")

class SwMcInstanceInterfaces(Base):

    __tablename__ = "sw_mc_instance_interfaces"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInstanceInterface": "sw_mc_instance_interface",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_instance_interface_id = Column(types.Integer, ForeignKey('sw_mc_instance_interface.rid', use_alter=True))
    sw_mc_instance_interface = relationship('SwMcInstanceInterface', foreign_keys=[sw_mc_instance_interface_id], uselist=True, cascade="all")

class SwSizeofInstance(Base):

    __tablename__ = "sw_sizeof_instance"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwAddrInfo(Base):

    __tablename__ = "sw_addr_info"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCpuMemSegRef": "sw_cpu_mem_seg_ref",
        "SwBaseAddr": "sw_base_addr",
        "SwAddrOffset": "sw_addr_offset",
        "SwSizeofInstance": "sw_sizeof_instance",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_cpu_mem_seg_ref_id = Column(types.Integer, ForeignKey('sw_cpu_mem_seg_ref.rid', use_alter=True))
    sw_cpu_mem_seg_ref = relationship('SwCpuMemSegRef', foreign_keys=[sw_cpu_mem_seg_ref_id], uselist=False, cascade="all")
    sw_base_addr_id = Column(types.Integer, ForeignKey('sw_base_addr.rid', use_alter=True))
    sw_base_addr = relationship('SwBaseAddr', foreign_keys=[sw_base_addr_id], uselist=False, cascade="all")
    sw_addr_offset_id = Column(types.Integer, ForeignKey('sw_addr_offset.rid', use_alter=True))
    sw_addr_offset = relationship('SwAddrOffset', foreign_keys=[sw_addr_offset_id], uselist=False, cascade="all")
    sw_sizeof_instance_id = Column(types.Integer, ForeignKey('sw_sizeof_instance.rid', use_alter=True))
    sw_sizeof_instance = relationship('SwSizeofInstance', foreign_keys=[sw_sizeof_instance_id], uselist=False, cascade="all")

class SwInstance(Base):

    __tablename__ = "sw_instance"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "SwArrayIndex": "sw_array_index",
        "Desc": "_desc",
        "Category": "category",
        "DisplayName": "display_name",
        "SwValueCont": "sw_value_cont",
        "SwAxisConts": "sw_axis_conts",
        "SwModelLink": "sw_model_link",
        "SwCsFlags": "sw_cs_flags",
        "SwCsHistory": "sw_cs_history",
        "AdminData": "admin_data",
        "SwFeatureRef": "sw_feature_ref",
        "SwInstancePropsVariants": "sw_instance_props_variants",
        "SwInstance": "sw_instance",
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    sw_array_index_id = Column(types.Integer, ForeignKey('sw_array_index.rid', use_alter=True))
    sw_array_index = relationship('SwArrayIndex', foreign_keys=[sw_array_index_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    display_name_id = Column(types.Integer, ForeignKey('display_name.rid', use_alter=True))
    display_name = relationship('DisplayName', foreign_keys=[display_name_id], uselist=False, cascade="all")
    sw_value_cont_id = Column(types.Integer, ForeignKey('sw_value_cont.rid', use_alter=True))
    sw_value_cont = relationship('SwValueCont', foreign_keys=[sw_value_cont_id], uselist=False, cascade="all")
    sw_axis_conts_id = Column(types.Integer, ForeignKey('sw_axis_conts.rid', use_alter=True))
    sw_axis_conts = relationship('SwAxisConts', foreign_keys=[sw_axis_conts_id], uselist=False, cascade="all")
    sw_model_link_id = Column(types.Integer, ForeignKey('sw_model_link.rid', use_alter=True))
    sw_model_link = relationship('SwModelLink', foreign_keys=[sw_model_link_id], uselist=False, cascade="all")
    sw_cs_flags_id = Column(types.Integer, ForeignKey('sw_cs_flags.rid', use_alter=True))
    sw_cs_flags = relationship('SwCsFlags', foreign_keys=[sw_cs_flags_id], uselist=False, cascade="all")
    sw_cs_history_id = Column(types.Integer, ForeignKey('sw_cs_history.rid', use_alter=True))
    sw_cs_history = relationship('SwCsHistory', foreign_keys=[sw_cs_history_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_feature_ref_id = Column(types.Integer, ForeignKey('sw_feature_ref.rid', use_alter=True))
    sw_feature_ref = relationship('SwFeatureRef', foreign_keys=[sw_feature_ref_id], uselist=False, cascade="all")
    sw_instance_props_variants_id = Column(types.Integer, ForeignKey('sw_instance_props_variants.rid', use_alter=True))
    sw_instance_props_variants = relationship('SwInstancePropsVariants', foreign_keys=[sw_instance_props_variants_id], uselist=False, cascade="all")
    sw_instance_id = Column(types.Integer, ForeignKey('sw_instance.rid', use_alter=True))
    sw_instance = relationship('SwInstance', foreign_keys=[sw_instance_id], uselist=True, cascade="all")

class SwValuesCodedHex(Base):

    __tablename__ = "sw_values_coded_hex"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "Vt": "vt",
        "Vh": "vh",
        "V": "v",
        "Vg": "vg",
        "SwInstanceRef": "sw_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=True, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")
    vg_id = Column(types.Integer, ForeignKey('vg.rid', use_alter=True))
    vg = relationship('Vg', foreign_keys=[vg_id], uselist=True, cascade="all")
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=True, cascade="all")

class SwAxisCont(Base):

    __tablename__ = "sw_axis_cont"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUnitRef": "sw_unit_ref",
        "UnitDisplayName": "unit_display_name",
        "SwAxisIndex": "sw_axis_index",
        "SwValuesPhys": "sw_values_phys",
        "SwValuesCoded": "sw_values_coded",
        "SwValuesCodedHex": "sw_values_coded_hex",
        "Category": "category",
        "SwArraysize": "sw_arraysize",
        "SwInstanceRef": "sw_instance_ref",
        "SwValuesGeneric": "sw_values_generic",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=False, cascade="all")
    unit_display_name_id = Column(types.Integer, ForeignKey('unit_display_name.rid', use_alter=True))
    unit_display_name = relationship('UnitDisplayName', foreign_keys=[unit_display_name_id], uselist=False, cascade="all")
    sw_axis_index_id = Column(types.Integer, ForeignKey('sw_axis_index.rid', use_alter=True))
    sw_axis_index = relationship('SwAxisIndex', foreign_keys=[sw_axis_index_id], uselist=False, cascade="all")
    sw_values_phys_id = Column(types.Integer, ForeignKey('sw_values_phys.rid', use_alter=True))
    sw_values_phys = relationship('SwValuesPhys', foreign_keys=[sw_values_phys_id], uselist=False, cascade="all")
    sw_values_coded_id = Column(types.Integer, ForeignKey('sw_values_coded.rid', use_alter=True))
    sw_values_coded = relationship('SwValuesCoded', foreign_keys=[sw_values_coded_id], uselist=False, cascade="all")
    sw_values_coded_hex_id = Column(types.Integer, ForeignKey('sw_values_coded_hex.rid', use_alter=True))
    sw_values_coded_hex = relationship('SwValuesCodedHex', foreign_keys=[sw_values_coded_hex_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    sw_arraysize_id = Column(types.Integer, ForeignKey('sw_arraysize.rid', use_alter=True))
    sw_arraysize = relationship('SwArraysize', foreign_keys=[sw_arraysize_id], uselist=False, cascade="all")
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=False, cascade="all")
    sw_values_generic_id = Column(types.Integer, ForeignKey('sw_values_generic.rid', use_alter=True))
    sw_values_generic = relationship('SwValuesGeneric', foreign_keys=[sw_values_generic_id], uselist=True, cascade="all")

class SwValuesGeneric(Base):

    __tablename__ = "sw_values_generic"
    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
        "Vt": "vt",
        "Vh": "vh",
        "V": "v",
        "Vg": "vg",
        "SwInstanceRef": "sw_instance_ref",
    }
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=True, cascade="all")
    vh_id = Column(types.Integer, ForeignKey('vh.rid', use_alter=True))
    vh = relationship('Vh', foreign_keys=[vh_id], uselist=True, cascade="all")
    v_id = Column(types.Integer, ForeignKey('v.rid', use_alter=True))
    v = relationship('V', foreign_keys=[v_id], uselist=True, cascade="all")
    vg_id = Column(types.Integer, ForeignKey('vg.rid', use_alter=True))
    vg = relationship('Vg', foreign_keys=[vg_id], uselist=True, cascade="all")
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=True, cascade="all")

class SwInstancePropsVariant(Base):

    __tablename__ = "sw_instance_props_variant"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "Desc": "_desc",
        "SwVcdCriterionValues": "sw_vcd_criterion_values",
        "SwValueCont": "sw_value_cont",
        "SwCsFlags": "sw_cs_flags",
        "SwAddrInfos": "sw_addr_infos",
        "SwAxisConts": "sw_axis_conts",
        "SwDataDefProps": "sw_data_def_props",
        "SwMcInstanceInterfaces": "sw_mc_instance_interfaces",
        "SwCsHistory": "sw_cs_history",
        "Annotations": "annotations",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_vcd_criterion_values_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_values.rid', use_alter=True))
    sw_vcd_criterion_values = relationship('SwVcdCriterionValues', foreign_keys=[sw_vcd_criterion_values_id], uselist=False, cascade="all")
    sw_value_cont_id = Column(types.Integer, ForeignKey('sw_value_cont.rid', use_alter=True))
    sw_value_cont = relationship('SwValueCont', foreign_keys=[sw_value_cont_id], uselist=False, cascade="all")
    sw_cs_flags_id = Column(types.Integer, ForeignKey('sw_cs_flags.rid', use_alter=True))
    sw_cs_flags = relationship('SwCsFlags', foreign_keys=[sw_cs_flags_id], uselist=False, cascade="all")
    sw_addr_infos_id = Column(types.Integer, ForeignKey('sw_addr_infos.rid', use_alter=True))
    sw_addr_infos = relationship('SwAddrInfos', foreign_keys=[sw_addr_infos_id], uselist=False, cascade="all")
    sw_axis_conts_id = Column(types.Integer, ForeignKey('sw_axis_conts.rid', use_alter=True))
    sw_axis_conts = relationship('SwAxisConts', foreign_keys=[sw_axis_conts_id], uselist=False, cascade="all")
    sw_data_def_props_id = Column(types.Integer, ForeignKey('sw_data_def_props.rid', use_alter=True))
    sw_data_def_props = relationship('SwDataDefProps', foreign_keys=[sw_data_def_props_id], uselist=False, cascade="all")
    sw_mc_instance_interfaces_id = Column(types.Integer, ForeignKey('sw_mc_instance_interfaces.rid', use_alter=True))
    sw_mc_instance_interfaces = relationship('SwMcInstanceInterfaces', foreign_keys=[sw_mc_instance_interfaces_id], uselist=False, cascade="all")
    sw_cs_history_id = Column(types.Integer, ForeignKey('sw_cs_history.rid', use_alter=True))
    sw_cs_history = relationship('SwCsHistory', foreign_keys=[sw_cs_history_id], uselist=False, cascade="all")
    annotations_id = Column(types.Integer, ForeignKey('annotations.rid', use_alter=True))
    annotations = relationship('Annotations', foreign_keys=[annotations_id], uselist=False, cascade="all")

class SwMcInterfaceRef(Base):

    __tablename__ = "sw_mc_interface_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcInterfaceSourceRef(Base):

    __tablename__ = "sw_mc_interface_source_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcInterfaceAvlSources(Base):

    __tablename__ = "sw_mc_interface_avl_sources"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceSourceRef": "sw_mc_interface_source_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_interface_source_ref_id = Column(types.Integer, ForeignKey('sw_mc_interface_source_ref.rid', use_alter=True))
    sw_mc_interface_source_ref = relationship('SwMcInterfaceSourceRef', foreign_keys=[sw_mc_interface_source_ref_id], uselist=True, cascade="all")

class SwMcInterfaceDefaultSource(Base):

    __tablename__ = "sw_mc_interface_default_source"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceSourceRef": "sw_mc_interface_source_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_interface_source_ref_id = Column(types.Integer, ForeignKey('sw_mc_interface_source_ref.rid', use_alter=True))
    sw_mc_interface_source_ref = relationship('SwMcInterfaceSourceRef', foreign_keys=[sw_mc_interface_source_ref_id], uselist=False, cascade="all")

class SwMcKpBlobConts(Base):

    __tablename__ = "sw_mc_kp_blob_conts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcDpBlobConts(Base):

    __tablename__ = "sw_mc_dp_blob_conts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcPaBlobConts(Base):

    __tablename__ = "sw_mc_pa_blob_conts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcAddrMappings(Base):

    __tablename__ = "sw_mc_addr_mappings"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcAddrMapping": "sw_mc_addr_mapping",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_addr_mapping_id = Column(types.Integer, ForeignKey('sw_mc_addr_mapping.rid', use_alter=True))
    sw_mc_addr_mapping = relationship('SwMcAddrMapping', foreign_keys=[sw_mc_addr_mapping_id], uselist=True, cascade="all")

class SwMcInstanceInterface(Base):

    __tablename__ = "sw_mc_instance_interface"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceRef": "sw_mc_interface_ref",
        "SwMcInterfaceDefaultSource": "sw_mc_interface_default_source",
        "SwMcInterfaceAvlSources": "sw_mc_interface_avl_sources",
        "SwMcKpBlobConts": "sw_mc_kp_blob_conts",
        "SwMcDpBlobConts": "sw_mc_dp_blob_conts",
        "SwMcPaBlobConts": "sw_mc_pa_blob_conts",
        "SwMcAddrMappings": "sw_mc_addr_mappings",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_interface_ref_id = Column(types.Integer, ForeignKey('sw_mc_interface_ref.rid', use_alter=True))
    sw_mc_interface_ref = relationship('SwMcInterfaceRef', foreign_keys=[sw_mc_interface_ref_id], uselist=False, cascade="all")
    sw_mc_interface_default_source_id = Column(types.Integer, ForeignKey('sw_mc_interface_default_source.rid', use_alter=True))
    sw_mc_interface_default_source = relationship('SwMcInterfaceDefaultSource', foreign_keys=[sw_mc_interface_default_source_id], uselist=False, cascade="all")
    sw_mc_interface_avl_sources_id = Column(types.Integer, ForeignKey('sw_mc_interface_avl_sources.rid', use_alter=True))
    sw_mc_interface_avl_sources = relationship('SwMcInterfaceAvlSources', foreign_keys=[sw_mc_interface_avl_sources_id], uselist=False, cascade="all")
    sw_mc_kp_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_kp_blob_conts.rid', use_alter=True))
    sw_mc_kp_blob_conts = relationship('SwMcKpBlobConts', foreign_keys=[sw_mc_kp_blob_conts_id], uselist=False, cascade="all")
    sw_mc_dp_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_dp_blob_conts.rid', use_alter=True))
    sw_mc_dp_blob_conts = relationship('SwMcDpBlobConts', foreign_keys=[sw_mc_dp_blob_conts_id], uselist=False, cascade="all")
    sw_mc_pa_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_pa_blob_conts.rid', use_alter=True))
    sw_mc_pa_blob_conts = relationship('SwMcPaBlobConts', foreign_keys=[sw_mc_pa_blob_conts_id], uselist=False, cascade="all")
    sw_mc_addr_mappings_id = Column(types.Integer, ForeignKey('sw_mc_addr_mappings.rid', use_alter=True))
    sw_mc_addr_mappings = relationship('SwMcAddrMappings', foreign_keys=[sw_mc_addr_mappings_id], uselist=False, cascade="all")

class SwMcOriginalAddr(Base):

    __tablename__ = "sw_mc_original_addr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcMappedAddr(Base):

    __tablename__ = "sw_mc_mapped_addr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcAddrMappedSize(Base):

    __tablename__ = "sw_mc_addr_mapped_size"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcAddrMapping(Base):

    __tablename__ = "sw_mc_addr_mapping"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcOriginalAddr": "sw_mc_original_addr",
        "SwMcMappedAddr": "sw_mc_mapped_addr",
        "SwMcAddrMappedSize": "sw_mc_addr_mapped_size",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_original_addr_id = Column(types.Integer, ForeignKey('sw_mc_original_addr.rid', use_alter=True))
    sw_mc_original_addr = relationship('SwMcOriginalAddr', foreign_keys=[sw_mc_original_addr_id], uselist=False, cascade="all")
    sw_mc_mapped_addr_id = Column(types.Integer, ForeignKey('sw_mc_mapped_addr.rid', use_alter=True))
    sw_mc_mapped_addr = relationship('SwMcMappedAddr', foreign_keys=[sw_mc_mapped_addr_id], uselist=False, cascade="all")
    sw_mc_addr_mapped_size_id = Column(types.Integer, ForeignKey('sw_mc_addr_mapped_size.rid', use_alter=True))
    sw_mc_addr_mapped_size = relationship('SwMcAddrMappedSize', foreign_keys=[sw_mc_addr_mapped_size_id], uselist=False, cascade="all")

class SwUserGroups(Base):

    __tablename__ = "sw_user_groups"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserGroup": "sw_user_group",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_user_group_id = Column(types.Integer, ForeignKey('sw_user_group.rid', use_alter=True))
    sw_user_group = relationship('SwUserGroup', foreign_keys=[sw_user_group_id], uselist=True, cascade="all")

class SwCollectionSpec(Base):

    __tablename__ = "sw_collection_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwCollections": "sw_collections",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_collections_id = Column(types.Integer, ForeignKey('sw_collections.rid', use_alter=True))
    sw_collections = relationship('SwCollections', foreign_keys=[sw_collections_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwCollectionRules(Base):

    __tablename__ = "sw_collection_rules"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRule": "sw_collection_rule",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_rule_id = Column(types.Integer, ForeignKey('sw_collection_rule.rid', use_alter=True))
    sw_collection_rule = relationship('SwCollectionRule', foreign_keys=[sw_collection_rule_id], uselist=True, cascade="all")

class SwCollectionRefs(Base):

    __tablename__ = "sw_collection_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRef": "sw_collection_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_ref_id = Column(types.Integer, ForeignKey('sw_collection_ref.rid', use_alter=True))
    sw_collection_ref = relationship('SwCollectionRef', foreign_keys=[sw_collection_ref_id], uselist=True, cascade="all")

class SwCollectionRegexps(Base):

    __tablename__ = "sw_collection_regexps"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRegexp": "sw_collection_regexp",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_regexp_id = Column(types.Integer, ForeignKey('sw_collection_regexp.rid', use_alter=True))
    sw_collection_regexp = relationship('SwCollectionRegexp', foreign_keys=[sw_collection_regexp_id], uselist=True, cascade="all")

class SwCollectionWildcards(Base):

    __tablename__ = "sw_collection_wildcards"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionWildcard": "sw_collection_wildcard",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_wildcard_id = Column(types.Integer, ForeignKey('sw_collection_wildcard.rid', use_alter=True))
    sw_collection_wildcard = relationship('SwCollectionWildcard', foreign_keys=[sw_collection_wildcard_id], uselist=True, cascade="all")

class SwCollectionRegexp(Base):

    __tablename__ = "sw_collection_regexp"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCollectionScripts(Base):

    __tablename__ = "sw_collection_scripts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionScript": "sw_collection_script",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_script_id = Column(types.Integer, ForeignKey('sw_collection_script.rid', use_alter=True))
    sw_collection_script = relationship('SwCollectionScript', foreign_keys=[sw_collection_script_id], uselist=True, cascade="all")

class SwCollectionWildcard(Base):

    __tablename__ = "sw_collection_wildcard"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCollectionRule(Base):

    __tablename__ = "sw_collection_rule"
    ATTRIBUTES = {
        "SCOPE": "scope",
        "RESOLVE-REFS": "resolve_refs",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRegexps": "sw_collection_regexps",
        "SwCollectionWildcards": "sw_collection_wildcards",
        "SwCollectionScripts": "sw_collection_scripts",
    }
    ENUMS = {
        "scope": ['SW-ADDR-METHOD', 'SW-AXIS-TYPE', 'SW-BASE-TYPE', 'SW-CALPRM', 'SW-CLASS-INSTANCE', 'SW-CODE-SYNTAX', 'SW-COMPU-METHOD', 'SW-DATA-CONSTR', 'SW-FEATURE', 'SW-INSTANCE', 'SW-RECORD-LAYOUT', 'SW-SYSTEMCONST', 'SW-UNIT', 'SW-VARIABLE', 'ALL'],
        "resolve_refs": ['RESOLVE-REFS', 'NOT-RESOLVE-REFS'],
    }
    scope = StdString()
    resolve_refs = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_collection_regexps_id = Column(types.Integer, ForeignKey('sw_collection_regexps.rid', use_alter=True))
    sw_collection_regexps = relationship('SwCollectionRegexps', foreign_keys=[sw_collection_regexps_id], uselist=False, cascade="all")
    sw_collection_wildcards_id = Column(types.Integer, ForeignKey('sw_collection_wildcards.rid', use_alter=True))
    sw_collection_wildcards = relationship('SwCollectionWildcards', foreign_keys=[sw_collection_wildcards_id], uselist=False, cascade="all")
    sw_collection_scripts_id = Column(types.Integer, ForeignKey('sw_collection_scripts.rid', use_alter=True))
    sw_collection_scripts = relationship('SwCollectionScripts', foreign_keys=[sw_collection_scripts_id], uselist=False, cascade="all")

class SwCollectionScript(Base):

    __tablename__ = "sw_collection_script"
    ATTRIBUTES = {
        "LANGUAGE": "language",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    language = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwFeatureRefs(Base):

    __tablename__ = "sw_feature_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRef": "sw_feature_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_ref_id = Column(types.Integer, ForeignKey('sw_feature_ref.rid', use_alter=True))
    sw_feature_ref = relationship('SwFeatureRef', foreign_keys=[sw_feature_ref_id], uselist=True, cascade="all")

class SwCsCollection(Base):

    __tablename__ = "sw_cs_collection"
    ATTRIBUTES = {
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "Category": "category",
        "SwFeatureRef": "sw_feature_ref",
        "Revision": "revision",
        "SwCollectionRef": "sw_collection_ref",
        "SwCsHistory": "sw_cs_history",
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    sw_feature_ref_id = Column(types.Integer, ForeignKey('sw_feature_ref.rid', use_alter=True))
    sw_feature_ref = relationship('SwFeatureRef', foreign_keys=[sw_feature_ref_id], uselist=False, cascade="all")
    revision_id = Column(types.Integer, ForeignKey('revision.rid', use_alter=True))
    revision = relationship('Revision', foreign_keys=[revision_id], uselist=False, cascade="all")
    sw_collection_ref_id = Column(types.Integer, ForeignKey('sw_collection_ref.rid', use_alter=True))
    sw_collection_ref = relationship('SwCollectionRef', foreign_keys=[sw_collection_ref_id], uselist=False, cascade="all")
    sw_cs_history_id = Column(types.Integer, ForeignKey('sw_cs_history.rid', use_alter=True))
    sw_cs_history = relationship('SwCsHistory', foreign_keys=[sw_cs_history_id], uselist=False, cascade="all")

class SwUnitRefs(Base):

    __tablename__ = "sw_unit_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUnitRef": "sw_unit_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_unit_ref_id = Column(types.Integer, ForeignKey('sw_unit_ref.rid', use_alter=True))
    sw_unit_ref = relationship('SwUnitRef', foreign_keys=[sw_unit_ref_id], uselist=True, cascade="all")

class SwCalprmRefs(Base):

    __tablename__ = "sw_calprm_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": "sw_calprm_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=True, cascade="all")

class SwInstanceRefs(Base):

    __tablename__ = "sw_instance_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwInstanceRef": "sw_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=True, cascade="all")

class SwClassInstanceRefs(Base):

    __tablename__ = "sw_class_instance_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": "sw_class_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_class_instance_ref_id = Column(types.Integer, ForeignKey('sw_class_instance_ref.rid', use_alter=True))
    sw_class_instance_ref = relationship('SwClassInstanceRef', foreign_keys=[sw_class_instance_ref_id], uselist=True, cascade="all")

class SwCompuMethodRefs(Base):

    __tablename__ = "sw_compu_method_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuMethodRef": "sw_compu_method_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_compu_method_ref_id = Column(types.Integer, ForeignKey('sw_compu_method_ref.rid', use_alter=True))
    sw_compu_method_ref = relationship('SwCompuMethodRef', foreign_keys=[sw_compu_method_ref_id], uselist=True, cascade="all")

class SwAddrMethodRefs(Base):

    __tablename__ = "sw_addr_method_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAddrMethodRef": "sw_addr_method_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_addr_method_ref_id = Column(types.Integer, ForeignKey('sw_addr_method_ref.rid', use_alter=True))
    sw_addr_method_ref = relationship('SwAddrMethodRef', foreign_keys=[sw_addr_method_ref_id], uselist=True, cascade="all")

class SwRecordLayoutRefs(Base):

    __tablename__ = "sw_record_layout_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwRecordLayoutRef": "sw_record_layout_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_record_layout_ref_id = Column(types.Integer, ForeignKey('sw_record_layout_ref.rid', use_alter=True))
    sw_record_layout_ref = relationship('SwRecordLayoutRef', foreign_keys=[sw_record_layout_ref_id], uselist=True, cascade="all")

class SwCodeSyntaxRefs(Base):

    __tablename__ = "sw_code_syntax_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCodeSyntaxRef": "sw_code_syntax_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_code_syntax_ref_id = Column(types.Integer, ForeignKey('sw_code_syntax_ref.rid', use_alter=True))
    sw_code_syntax_ref = relationship('SwCodeSyntaxRef', foreign_keys=[sw_code_syntax_ref_id], uselist=True, cascade="all")

class SwBaseTypeRefs(Base):

    __tablename__ = "sw_base_type_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwBaseTypeRef": "sw_base_type_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=True, cascade="all")

class SwDataConstrRefs(Base):

    __tablename__ = "sw_data_constr_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwDataConstrRef": "sw_data_constr_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_data_constr_ref_id = Column(types.Integer, ForeignKey('sw_data_constr_ref.rid', use_alter=True))
    sw_data_constr_ref = relationship('SwDataConstrRef', foreign_keys=[sw_data_constr_ref_id], uselist=True, cascade="all")

class SwAxisTypeRefs(Base):

    __tablename__ = "sw_axis_type_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisTypeRef": "sw_axis_type_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_axis_type_ref_id = Column(types.Integer, ForeignKey('sw_axis_type_ref.rid', use_alter=True))
    sw_axis_type_ref = relationship('SwAxisTypeRef', foreign_keys=[sw_axis_type_ref_id], uselist=True, cascade="all")

class SwCollectionCont(Base):

    __tablename__ = "sw_collection_cont"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRefs": "sw_feature_refs",
        "SwUnitRefs": "sw_unit_refs",
        "SwVariableRefs": "sw_variable_refs",
        "SwCalprmRefs": "sw_calprm_refs",
        "SwInstanceRefs": "sw_instance_refs",
        "SwClassInstanceRefs": "sw_class_instance_refs",
        "SwCompuMethodRefs": "sw_compu_method_refs",
        "SwAddrMethodRefs": "sw_addr_method_refs",
        "SwRecordLayoutRefs": "sw_record_layout_refs",
        "SwCodeSyntaxRefs": "sw_code_syntax_refs",
        "SwBaseTypeRefs": "sw_base_type_refs",
        "SwSystemconstRefs": "sw_systemconst_refs",
        "SwDataConstrRefs": "sw_data_constr_refs",
        "SwAxisTypeRefs": "sw_axis_type_refs",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_feature_refs_id = Column(types.Integer, ForeignKey('sw_feature_refs.rid', use_alter=True))
    sw_feature_refs = relationship('SwFeatureRefs', foreign_keys=[sw_feature_refs_id], uselist=False, cascade="all")
    sw_unit_refs_id = Column(types.Integer, ForeignKey('sw_unit_refs.rid', use_alter=True))
    sw_unit_refs = relationship('SwUnitRefs', foreign_keys=[sw_unit_refs_id], uselist=False, cascade="all")
    sw_variable_refs_id = Column(types.Integer, ForeignKey('sw_variable_refs.rid', use_alter=True))
    sw_variable_refs = relationship('SwVariableRefs', foreign_keys=[sw_variable_refs_id], uselist=False, cascade="all")
    sw_calprm_refs_id = Column(types.Integer, ForeignKey('sw_calprm_refs.rid', use_alter=True))
    sw_calprm_refs = relationship('SwCalprmRefs', foreign_keys=[sw_calprm_refs_id], uselist=False, cascade="all")
    sw_instance_refs_id = Column(types.Integer, ForeignKey('sw_instance_refs.rid', use_alter=True))
    sw_instance_refs = relationship('SwInstanceRefs', foreign_keys=[sw_instance_refs_id], uselist=False, cascade="all")
    sw_class_instance_refs_id = Column(types.Integer, ForeignKey('sw_class_instance_refs.rid', use_alter=True))
    sw_class_instance_refs = relationship('SwClassInstanceRefs', foreign_keys=[sw_class_instance_refs_id], uselist=False, cascade="all")
    sw_compu_method_refs_id = Column(types.Integer, ForeignKey('sw_compu_method_refs.rid', use_alter=True))
    sw_compu_method_refs = relationship('SwCompuMethodRefs', foreign_keys=[sw_compu_method_refs_id], uselist=False, cascade="all")
    sw_addr_method_refs_id = Column(types.Integer, ForeignKey('sw_addr_method_refs.rid', use_alter=True))
    sw_addr_method_refs = relationship('SwAddrMethodRefs', foreign_keys=[sw_addr_method_refs_id], uselist=False, cascade="all")
    sw_record_layout_refs_id = Column(types.Integer, ForeignKey('sw_record_layout_refs.rid', use_alter=True))
    sw_record_layout_refs = relationship('SwRecordLayoutRefs', foreign_keys=[sw_record_layout_refs_id], uselist=False, cascade="all")
    sw_code_syntax_refs_id = Column(types.Integer, ForeignKey('sw_code_syntax_refs.rid', use_alter=True))
    sw_code_syntax_refs = relationship('SwCodeSyntaxRefs', foreign_keys=[sw_code_syntax_refs_id], uselist=False, cascade="all")
    sw_base_type_refs_id = Column(types.Integer, ForeignKey('sw_base_type_refs.rid', use_alter=True))
    sw_base_type_refs = relationship('SwBaseTypeRefs', foreign_keys=[sw_base_type_refs_id], uselist=False, cascade="all")
    sw_systemconst_refs_id = Column(types.Integer, ForeignKey('sw_systemconst_refs.rid', use_alter=True))
    sw_systemconst_refs = relationship('SwSystemconstRefs', foreign_keys=[sw_systemconst_refs_id], uselist=False, cascade="all")
    sw_data_constr_refs_id = Column(types.Integer, ForeignKey('sw_data_constr_refs.rid', use_alter=True))
    sw_data_constr_refs = relationship('SwDataConstrRefs', foreign_keys=[sw_data_constr_refs_id], uselist=False, cascade="all")
    sw_axis_type_refs_id = Column(types.Integer, ForeignKey('sw_axis_type_refs.rid', use_alter=True))
    sw_axis_type_refs = relationship('SwAxisTypeRefs', foreign_keys=[sw_axis_type_refs_id], uselist=False, cascade="all")

class SwCollection(Base):

    __tablename__ = "sw_collection"
    ATTRIBUTES = {
        "ROOT": "root",
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "Annotation": "annotation",
        "SwCollectionRules": "sw_collection_rules",
        "SwCollectionRefs": "sw_collection_refs",
        "SwCollectionCont": "sw_collection_cont",
    }
    ENUMS = {
        "root": ['ROOT', 'NO-ROOT'],
    }
    root = StdString()
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    annotation_id = Column(types.Integer, ForeignKey('annotation.rid', use_alter=True))
    annotation = relationship('Annotation', foreign_keys=[annotation_id], uselist=False, cascade="all")
    sw_collection_rules_id = Column(types.Integer, ForeignKey('sw_collection_rules.rid', use_alter=True))
    sw_collection_rules = relationship('SwCollectionRules', foreign_keys=[sw_collection_rules_id], uselist=False, cascade="all")
    sw_collection_refs_id = Column(types.Integer, ForeignKey('sw_collection_refs.rid', use_alter=True))
    sw_collection_refs = relationship('SwCollectionRefs', foreign_keys=[sw_collection_refs_id], uselist=False, cascade="all")
    sw_collection_cont_id = Column(types.Integer, ForeignKey('sw_collection_cont.rid', use_alter=True))
    sw_collection_cont = relationship('SwCollectionCont', foreign_keys=[sw_collection_cont_id], uselist=False, cascade="all")

class SwCpuStandardRecordLayout(Base):

    __tablename__ = "sw_cpu_standard_record_layout"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwRecordLayoutRef": "sw_record_layout_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_record_layout_ref_id = Column(types.Integer, ForeignKey('sw_record_layout_ref.rid', use_alter=True))
    sw_record_layout_ref = relationship('SwRecordLayoutRef', foreign_keys=[sw_record_layout_ref_id], uselist=False, cascade="all")

class SwUserAccessCases(Base):

    __tablename__ = "sw_user_access_cases"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserAccessCase": "sw_user_access_case",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_user_access_case_id = Column(types.Integer, ForeignKey('sw_user_access_case.rid', use_alter=True))
    sw_user_access_case = relationship('SwUserAccessCase', foreign_keys=[sw_user_access_case_id], uselist=True, cascade="all")

class SystemUsers(Base):

    __tablename__ = "system_users"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SystemUser": "system_user",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    system_user_id = Column(types.Integer, ForeignKey('system_user.rid', use_alter=True))
    system_user = relationship('SystemUser', foreign_keys=[system_user_id], uselist=True, cascade="all")

class SwUserGroupRefs(Base):

    __tablename__ = "sw_user_group_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserGroupRef": "sw_user_group_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_user_group_ref_id = Column(types.Integer, ForeignKey('sw_user_group_ref.rid', use_alter=True))
    sw_user_group_ref = relationship('SwUserGroupRef', foreign_keys=[sw_user_group_ref_id], uselist=True, cascade="all")

class SystemUser(Base):

    __tablename__ = "system_user"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwUserGroup(Base):

    __tablename__ = "sw_user_group"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "TeamMemberRefs": "team_member_refs",
        "SystemUsers": "system_users",
        "SwUserGroupRefs": "sw_user_group_refs",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    team_member_refs_id = Column(types.Integer, ForeignKey('team_member_refs.rid', use_alter=True))
    team_member_refs = relationship('TeamMemberRefs', foreign_keys=[team_member_refs_id], uselist=False, cascade="all")
    system_users_id = Column(types.Integer, ForeignKey('system_users.rid', use_alter=True))
    system_users = relationship('SystemUsers', foreign_keys=[system_users_id], uselist=False, cascade="all")
    sw_user_group_refs_id = Column(types.Integer, ForeignKey('sw_user_group_refs.rid', use_alter=True))
    sw_user_group_refs = relationship('SwUserGroupRefs', foreign_keys=[sw_user_group_refs_id], uselist=False, cascade="all")

class SwUserGroupRef(Base):

    __tablename__ = "sw_user_group_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwUserAccessDefintions(Base):

    __tablename__ = "sw_user_access_defintions"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAccessDef": "sw_access_def",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_access_def_id = Column(types.Integer, ForeignKey('sw_access_def.rid', use_alter=True))
    sw_access_def = relationship('SwAccessDef', foreign_keys=[sw_access_def_id], uselist=True, cascade="all")

class SwUserAccessCaseRefs(Base):

    __tablename__ = "sw_user_access_case_refs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserAccessCaseRef": "sw_user_access_case_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_user_access_case_ref_id = Column(types.Integer, ForeignKey('sw_user_access_case_ref.rid', use_alter=True))
    sw_user_access_case_ref = relationship('SwUserAccessCaseRef', foreign_keys=[sw_user_access_case_ref_id], uselist=True, cascade="all")

class SwUserAccessCase(Base):

    __tablename__ = "sw_user_access_case"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwUserAccessCaseRefs": "sw_user_access_case_refs",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_user_access_case_refs_id = Column(types.Integer, ForeignKey('sw_user_access_case_refs.rid', use_alter=True))
    sw_user_access_case_refs = relationship('SwUserAccessCaseRefs', foreign_keys=[sw_user_access_case_refs_id], uselist=False, cascade="all")

class SwUserAccessCaseRef(Base):

    __tablename__ = "sw_user_access_case_ref"
    ATTRIBUTES = {
        "ID-REF": "id_ref",
        "HYTIME": "hytime",
        "HYNAMES": "hynames",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwUserRightSpec(Base):

    __tablename__ = "sw_user_right_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwUserGroups": "sw_user_groups",
        "SwUserAccessCases": "sw_user_access_cases",
        "SwUserAccessDefintions": "sw_user_access_defintions",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_user_groups_id = Column(types.Integer, ForeignKey('sw_user_groups.rid', use_alter=True))
    sw_user_groups = relationship('SwUserGroups', foreign_keys=[sw_user_groups_id], uselist=False, cascade="all")
    sw_user_access_cases_id = Column(types.Integer, ForeignKey('sw_user_access_cases.rid', use_alter=True))
    sw_user_access_cases = relationship('SwUserAccessCases', foreign_keys=[sw_user_access_cases_id], uselist=False, cascade="all")
    sw_user_access_defintions_id = Column(types.Integer, ForeignKey('sw_user_access_defintions.rid', use_alter=True))
    sw_user_access_defintions = relationship('SwUserAccessDefintions', foreign_keys=[sw_user_access_defintions_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwAccessDef(Base):

    __tablename__ = "sw_access_def"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserGroupRef": "sw_user_group_ref",
        "SwUserAccessCaseRef": "sw_user_access_case_ref",
        "SwCollectionRef": "sw_collection_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_user_group_ref_id = Column(types.Integer, ForeignKey('sw_user_group_ref.rid', use_alter=True))
    sw_user_group_ref = relationship('SwUserGroupRef', foreign_keys=[sw_user_group_ref_id], uselist=False, cascade="all")
    sw_user_access_case_ref_id = Column(types.Integer, ForeignKey('sw_user_access_case_ref.rid', use_alter=True))
    sw_user_access_case_ref = relationship('SwUserAccessCaseRef', foreign_keys=[sw_user_access_case_ref_id], uselist=False, cascade="all")
    sw_collection_ref_id = Column(types.Integer, ForeignKey('sw_collection_ref.rid', use_alter=True))
    sw_collection_ref = relationship('SwCollectionRef', foreign_keys=[sw_collection_ref_id], uselist=False, cascade="all")

class SwCalibrationMethods(Base):

    __tablename__ = "sw_calibration_methods"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalibrationMethod": "sw_calibration_method",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calibration_method_id = Column(types.Integer, ForeignKey('sw_calibration_method.rid', use_alter=True))
    sw_calibration_method = relationship('SwCalibrationMethod', foreign_keys=[sw_calibration_method_id], uselist=True, cascade="all")

class SwCpuMemSegs(Base):

    __tablename__ = "sw_cpu_mem_segs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCpuMemSeg": "sw_cpu_mem_seg",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_cpu_mem_seg_id = Column(types.Integer, ForeignKey('sw_cpu_mem_seg.rid', use_alter=True))
    sw_cpu_mem_seg = relationship('SwCpuMemSeg', foreign_keys=[sw_cpu_mem_seg_id], uselist=True, cascade="all")

class SwCpuEpk(Base):

    __tablename__ = "sw_cpu_epk"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemProgramType(Base):

    __tablename__ = "sw_mem_program_type"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemType(Base):

    __tablename__ = "sw_mem_type"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemAttr(Base):

    __tablename__ = "sw_mem_attr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemBaseAddr(Base):

    __tablename__ = "sw_mem_base_addr"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemSize(Base):

    __tablename__ = "sw_mem_size"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMemOffsets(Base):

    __tablename__ = "sw_mem_offsets"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMemOffset": "sw_mem_offset",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mem_offset_id = Column(types.Integer, ForeignKey('sw_mem_offset.rid', use_alter=True))
    sw_mem_offset = relationship('SwMemOffset', foreign_keys=[sw_mem_offset_id], uselist=True, cascade="all")

class SwCpuMemSeg(Base):

    __tablename__ = "sw_cpu_mem_seg"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwMemProgramType": "sw_mem_program_type",
        "SwMemType": "sw_mem_type",
        "SwMemAttr": "sw_mem_attr",
        "SwMemBaseAddr": "sw_mem_base_addr",
        "SwMemSize": "sw_mem_size",
        "SwMemOffsets": "sw_mem_offsets",
        "SwMcInstanceInterfaces": "sw_mc_instance_interfaces",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_mem_program_type_id = Column(types.Integer, ForeignKey('sw_mem_program_type.rid', use_alter=True))
    sw_mem_program_type = relationship('SwMemProgramType', foreign_keys=[sw_mem_program_type_id], uselist=False, cascade="all")
    sw_mem_type_id = Column(types.Integer, ForeignKey('sw_mem_type.rid', use_alter=True))
    sw_mem_type = relationship('SwMemType', foreign_keys=[sw_mem_type_id], uselist=False, cascade="all")
    sw_mem_attr_id = Column(types.Integer, ForeignKey('sw_mem_attr.rid', use_alter=True))
    sw_mem_attr = relationship('SwMemAttr', foreign_keys=[sw_mem_attr_id], uselist=False, cascade="all")
    sw_mem_base_addr_id = Column(types.Integer, ForeignKey('sw_mem_base_addr.rid', use_alter=True))
    sw_mem_base_addr = relationship('SwMemBaseAddr', foreign_keys=[sw_mem_base_addr_id], uselist=False, cascade="all")
    sw_mem_size_id = Column(types.Integer, ForeignKey('sw_mem_size.rid', use_alter=True))
    sw_mem_size = relationship('SwMemSize', foreign_keys=[sw_mem_size_id], uselist=False, cascade="all")
    sw_mem_offsets_id = Column(types.Integer, ForeignKey('sw_mem_offsets.rid', use_alter=True))
    sw_mem_offsets = relationship('SwMemOffsets', foreign_keys=[sw_mem_offsets_id], uselist=False, cascade="all")
    sw_mc_instance_interfaces_id = Column(types.Integer, ForeignKey('sw_mc_instance_interfaces.rid', use_alter=True))
    sw_mc_instance_interfaces = relationship('SwMcInstanceInterfaces', foreign_keys=[sw_mc_instance_interfaces_id], uselist=False, cascade="all")

class SwMemOffset(Base):

    __tablename__ = "sw_mem_offset"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCpuAddrEpk(Base):

    __tablename__ = "sw_cpu_addr_epk"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAddrInfo": "sw_addr_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_addr_info_id = Column(types.Integer, ForeignKey('sw_addr_info.rid', use_alter=True))
    sw_addr_info = relationship('SwAddrInfo', foreign_keys=[sw_addr_info_id], uselist=False, cascade="all")

class SwCpuType(Base):

    __tablename__ = "sw_cpu_type"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCpuCalibrationOffset(Base):

    __tablename__ = "sw_cpu_calibration_offset"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCpuNumberOfInterfaces(Base):

    __tablename__ = "sw_cpu_number_of_interfaces"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwCpuSpec(Base):

    __tablename__ = "sw_cpu_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "ByteOrder": "byte_order",
        "SwBaseTypeSize": "sw_base_type_size",
        "SwMemAlignment": "sw_mem_alignment",
        "SwCpuStandardRecordLayout": "sw_cpu_standard_record_layout",
        "SwCpuMemSegs": "sw_cpu_mem_segs",
        "SwCpuEpk": "sw_cpu_epk",
        "SwCpuAddrEpk": "sw_cpu_addr_epk",
        "SwCpuType": "sw_cpu_type",
        "SwCpuCalibrationOffset": "sw_cpu_calibration_offset",
        "SwCpuNumberOfInterfaces": "sw_cpu_number_of_interfaces",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    byte_order_id = Column(types.Integer, ForeignKey('byte_order.rid', use_alter=True))
    byte_order = relationship('ByteOrder', foreign_keys=[byte_order_id], uselist=False, cascade="all")
    sw_base_type_size_id = Column(types.Integer, ForeignKey('sw_base_type_size.rid', use_alter=True))
    sw_base_type_size = relationship('SwBaseTypeSize', foreign_keys=[sw_base_type_size_id], uselist=False, cascade="all")
    sw_mem_alignment_id = Column(types.Integer, ForeignKey('sw_mem_alignment.rid', use_alter=True))
    sw_mem_alignment = relationship('SwMemAlignment', foreign_keys=[sw_mem_alignment_id], uselist=False, cascade="all")
    sw_cpu_standard_record_layout_id = Column(types.Integer, ForeignKey('sw_cpu_standard_record_layout.rid', use_alter=True))
    sw_cpu_standard_record_layout = relationship('SwCpuStandardRecordLayout', foreign_keys=[sw_cpu_standard_record_layout_id], uselist=False, cascade="all")
    sw_cpu_mem_segs_id = Column(types.Integer, ForeignKey('sw_cpu_mem_segs.rid', use_alter=True))
    sw_cpu_mem_segs = relationship('SwCpuMemSegs', foreign_keys=[sw_cpu_mem_segs_id], uselist=False, cascade="all")
    sw_cpu_epk_id = Column(types.Integer, ForeignKey('sw_cpu_epk.rid', use_alter=True))
    sw_cpu_epk = relationship('SwCpuEpk', foreign_keys=[sw_cpu_epk_id], uselist=False, cascade="all")
    sw_cpu_addr_epk_id = Column(types.Integer, ForeignKey('sw_cpu_addr_epk.rid', use_alter=True))
    sw_cpu_addr_epk = relationship('SwCpuAddrEpk', foreign_keys=[sw_cpu_addr_epk_id], uselist=False, cascade="all")
    sw_cpu_type_id = Column(types.Integer, ForeignKey('sw_cpu_type.rid', use_alter=True))
    sw_cpu_type = relationship('SwCpuType', foreign_keys=[sw_cpu_type_id], uselist=False, cascade="all")
    sw_cpu_calibration_offset_id = Column(types.Integer, ForeignKey('sw_cpu_calibration_offset.rid', use_alter=True))
    sw_cpu_calibration_offset = relationship('SwCpuCalibrationOffset', foreign_keys=[sw_cpu_calibration_offset_id], uselist=False, cascade="all")
    sw_cpu_number_of_interfaces_id = Column(types.Integer, ForeignKey('sw_cpu_number_of_interfaces.rid', use_alter=True))
    sw_cpu_number_of_interfaces = relationship('SwCpuNumberOfInterfaces', foreign_keys=[sw_cpu_number_of_interfaces_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwVcdCriteria(Base):

    __tablename__ = "sw_vcd_criteria"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterion": "sw_vcd_criterion",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_vcd_criterion_id = Column(types.Integer, ForeignKey('sw_vcd_criterion.rid', use_alter=True))
    sw_vcd_criterion = relationship('SwVcdCriterion', foreign_keys=[sw_vcd_criterion_id], uselist=True, cascade="all")

class SwCalibrationMethodSpec(Base):

    __tablename__ = "sw_calibration_method_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwCalibrationMethods": "sw_calibration_methods",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_calibration_methods_id = Column(types.Integer, ForeignKey('sw_calibration_methods.rid', use_alter=True))
    sw_calibration_methods = relationship('SwCalibrationMethods', foreign_keys=[sw_calibration_methods_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwCalibrationMethodVersions(Base):

    __tablename__ = "sw_calibration_method_versions"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalibrationMethodVersion": "sw_calibration_method_version",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_calibration_method_version_id = Column(types.Integer, ForeignKey('sw_calibration_method_version.rid', use_alter=True))
    sw_calibration_method_version = relationship('SwCalibrationMethodVersion', foreign_keys=[sw_calibration_method_version_id], uselist=True, cascade="all")

class SwCalibrationMethod(Base):

    __tablename__ = "sw_calibration_method"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwCalibrationMethodVersions": "sw_calibration_method_versions",
        "AddInfo": "add_info",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_calibration_method_versions_id = Column(types.Integer, ForeignKey('sw_calibration_method_versions.rid', use_alter=True))
    sw_calibration_method_versions = relationship('SwCalibrationMethodVersions', foreign_keys=[sw_calibration_method_versions_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwCalibrationHandle(Base):

    __tablename__ = "sw_calibration_handle"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": "vf",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vf_id = Column(types.Integer, ForeignKey('vf.rid', use_alter=True))
    vf = relationship('Vf', foreign_keys=[vf_id], uselist=True, cascade="all")

class SwCalibrationMethodVersion(Base):

    __tablename__ = "sw_calibration_method_version"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "SwCalibrationHandle": "sw_calibration_handle",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    sw_calibration_handle_id = Column(types.Integer, ForeignKey('sw_calibration_handle.rid', use_alter=True))
    sw_calibration_handle = relationship('SwCalibrationHandle', foreign_keys=[sw_calibration_handle_id], uselist=False, cascade="all")

class SwVcdSpec(Base):

    __tablename__ = "sw_vcd_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwVcdCriteria": "sw_vcd_criteria",
        "AddInfo": "add_info",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_vcd_criteria_id = Column(types.Integer, ForeignKey('sw_vcd_criteria.rid', use_alter=True))
    sw_vcd_criteria = relationship('SwVcdCriteria', foreign_keys=[sw_vcd_criteria_id], uselist=False, cascade="all")
    add_info_id = Column(types.Integer, ForeignKey('add_info.rid', use_alter=True))
    add_info = relationship('AddInfo', foreign_keys=[add_info_id], uselist=False, cascade="all")

class SwSystem(Base):

    __tablename__ = "sw_system"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwArchitecture": "sw_architecture",
        "SwTestSpec": "sw_test_spec",
        "SwDataDictionarySpec": "sw_data_dictionary_spec",
        "SwComponentSpec": "sw_component_spec",
        "SwInstanceSpec": "sw_instance_spec",
        "SwCollectionSpec": "sw_collection_spec",
        "SwUserRightSpec": "sw_user_right_spec",
        "SwCpuSpec": "sw_cpu_spec",
        "SwCalibrationMethodSpec": "sw_calibration_method_spec",
        "SwVcdSpec": "sw_vcd_spec",
        "AddSpec": "add_spec",
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_architecture_id = Column(types.Integer, ForeignKey('sw_architecture.rid', use_alter=True))
    sw_architecture = relationship('SwArchitecture', foreign_keys=[sw_architecture_id], uselist=False, cascade="all")
    sw_test_spec_id = Column(types.Integer, ForeignKey('sw_test_spec.rid', use_alter=True))
    sw_test_spec = relationship('SwTestSpec', foreign_keys=[sw_test_spec_id], uselist=False, cascade="all")
    sw_data_dictionary_spec_id = Column(types.Integer, ForeignKey('sw_data_dictionary_spec.rid', use_alter=True))
    sw_data_dictionary_spec = relationship('SwDataDictionarySpec', foreign_keys=[sw_data_dictionary_spec_id], uselist=False, cascade="all")
    sw_component_spec_id = Column(types.Integer, ForeignKey('sw_component_spec.rid', use_alter=True))
    sw_component_spec = relationship('SwComponentSpec', foreign_keys=[sw_component_spec_id], uselist=False, cascade="all")
    sw_instance_spec_id = Column(types.Integer, ForeignKey('sw_instance_spec.rid', use_alter=True))
    sw_instance_spec = relationship('SwInstanceSpec', foreign_keys=[sw_instance_spec_id], uselist=False, cascade="all")
    sw_collection_spec_id = Column(types.Integer, ForeignKey('sw_collection_spec.rid', use_alter=True))
    sw_collection_spec = relationship('SwCollectionSpec', foreign_keys=[sw_collection_spec_id], uselist=False, cascade="all")
    sw_user_right_spec_id = Column(types.Integer, ForeignKey('sw_user_right_spec.rid', use_alter=True))
    sw_user_right_spec = relationship('SwUserRightSpec', foreign_keys=[sw_user_right_spec_id], uselist=False, cascade="all")
    sw_cpu_spec_id = Column(types.Integer, ForeignKey('sw_cpu_spec.rid', use_alter=True))
    sw_cpu_spec = relationship('SwCpuSpec', foreign_keys=[sw_cpu_spec_id], uselist=False, cascade="all")
    sw_calibration_method_spec_id = Column(types.Integer, ForeignKey('sw_calibration_method_spec.rid', use_alter=True))
    sw_calibration_method_spec = relationship('SwCalibrationMethodSpec', foreign_keys=[sw_calibration_method_spec_id], uselist=False, cascade="all")
    sw_vcd_spec_id = Column(types.Integer, ForeignKey('sw_vcd_spec.rid', use_alter=True))
    sw_vcd_spec = relationship('SwVcdSpec', foreign_keys=[sw_vcd_spec_id], uselist=False, cascade="all")
    add_spec_id = Column(types.Integer, ForeignKey('add_spec.rid', use_alter=True))
    add_spec = relationship('AddSpec', foreign_keys=[add_spec_id], uselist=False, cascade="all")

class SwVcdCriterionPossibleValues(Base):

    __tablename__ = "sw_vcd_criterion_possible_values"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vt": "vt",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    vt_id = Column(types.Integer, ForeignKey('vt.rid', use_alter=True))
    vt = relationship('Vt', foreign_keys=[vt_id], uselist=True, cascade="all")

class SwVcdCriterion(Base):

    __tablename__ = "sw_vcd_criterion"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwCalprmRef": "sw_calprm_ref",
        "SwVariableRef": "sw_variable_ref",
        "SwVcdCriterionPossibleValues": "sw_vcd_criterion_possible_values",
        "SwCompuMethodRef": "sw_compu_method_ref",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_calprm_ref_id = Column(types.Integer, ForeignKey('sw_calprm_ref.rid', use_alter=True))
    sw_calprm_ref = relationship('SwCalprmRef', foreign_keys=[sw_calprm_ref_id], uselist=False, cascade="all")
    sw_variable_ref_id = Column(types.Integer, ForeignKey('sw_variable_ref.rid', use_alter=True))
    sw_variable_ref = relationship('SwVariableRef', foreign_keys=[sw_variable_ref_id], uselist=False, cascade="all")
    sw_vcd_criterion_possible_values_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_possible_values.rid', use_alter=True))
    sw_vcd_criterion_possible_values = relationship('SwVcdCriterionPossibleValues', foreign_keys=[sw_vcd_criterion_possible_values_id], uselist=False, cascade="all")
    sw_compu_method_ref_id = Column(types.Integer, ForeignKey('sw_compu_method_ref.rid', use_alter=True))
    sw_compu_method_ref = relationship('SwCompuMethodRef', foreign_keys=[sw_compu_method_ref_id], uselist=False, cascade="all")

class SwGlossary(Base):

    __tablename__ = "sw_glossary"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "Introduction": "introduction",
        "AdminData": "admin_data",
        "Ncoi1": "ncoi_1",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=False, cascade="all")

class SwMcBaseTypes(Base):

    __tablename__ = "sw_mc_base_types"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcBaseType": "sw_mc_base_type",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_base_type_id = Column(types.Integer, ForeignKey('sw_mc_base_type.rid', use_alter=True))
    sw_mc_base_type = relationship('SwMcBaseType', foreign_keys=[sw_mc_base_type_id], uselist=True, cascade="all")

class SwMcTpBlobLayout(Base):

    __tablename__ = "sw_mc_tp_blob_layout"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcQpBlobLayout(Base):

    __tablename__ = "sw_mc_qp_blob_layout"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcKpBlobLayout(Base):

    __tablename__ = "sw_mc_kp_blob_layout"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcDpBlobLayout(Base):

    __tablename__ = "sw_mc_dp_blob_layout"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcPaBlobLayout(Base):

    __tablename__ = "sw_mc_pa_blob_layout"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcBlobLayouts(Base):

    __tablename__ = "sw_mc_blob_layouts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcTpBlobLayout": "sw_mc_tp_blob_layout",
        "SwMcQpBlobLayout": "sw_mc_qp_blob_layout",
        "SwMcKpBlobLayout": "sw_mc_kp_blob_layout",
        "SwMcDpBlobLayout": "sw_mc_dp_blob_layout",
        "SwMcPaBlobLayout": "sw_mc_pa_blob_layout",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_tp_blob_layout_id = Column(types.Integer, ForeignKey('sw_mc_tp_blob_layout.rid', use_alter=True))
    sw_mc_tp_blob_layout = relationship('SwMcTpBlobLayout', foreign_keys=[sw_mc_tp_blob_layout_id], uselist=False, cascade="all")
    sw_mc_qp_blob_layout_id = Column(types.Integer, ForeignKey('sw_mc_qp_blob_layout.rid', use_alter=True))
    sw_mc_qp_blob_layout = relationship('SwMcQpBlobLayout', foreign_keys=[sw_mc_qp_blob_layout_id], uselist=False, cascade="all")
    sw_mc_kp_blob_layout_id = Column(types.Integer, ForeignKey('sw_mc_kp_blob_layout.rid', use_alter=True))
    sw_mc_kp_blob_layout = relationship('SwMcKpBlobLayout', foreign_keys=[sw_mc_kp_blob_layout_id], uselist=False, cascade="all")
    sw_mc_dp_blob_layout_id = Column(types.Integer, ForeignKey('sw_mc_dp_blob_layout.rid', use_alter=True))
    sw_mc_dp_blob_layout = relationship('SwMcDpBlobLayout', foreign_keys=[sw_mc_dp_blob_layout_id], uselist=False, cascade="all")
    sw_mc_pa_blob_layout_id = Column(types.Integer, ForeignKey('sw_mc_pa_blob_layout.rid', use_alter=True))
    sw_mc_pa_blob_layout = relationship('SwMcPaBlobLayout', foreign_keys=[sw_mc_pa_blob_layout_id], uselist=False, cascade="all")

class SwMcInterface(Base):

    __tablename__ = "sw_mc_interface"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwMcBlobLayouts": "sw_mc_blob_layouts",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_mc_blob_layouts_id = Column(types.Integer, ForeignKey('sw_mc_blob_layouts.rid', use_alter=True))
    sw_mc_blob_layouts = relationship('SwMcBlobLayouts', foreign_keys=[sw_mc_blob_layouts_id], uselist=False, cascade="all")

class SwMcInterfaceImpls(Base):

    __tablename__ = "sw_mc_interface_impls"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceImpl": "sw_mc_interface_impl",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_interface_impl_id = Column(types.Integer, ForeignKey('sw_mc_interface_impl.rid', use_alter=True))
    sw_mc_interface_impl = relationship('SwMcInterfaceImpl', foreign_keys=[sw_mc_interface_impl_id], uselist=True, cascade="all")

class SwMcBaseType(Base):

    __tablename__ = "sw_mc_base_type"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwBaseTypeSize": "sw_base_type_size",
        "SwCodedType": "sw_coded_type",
        "SwMemAlignment": "sw_mem_alignment",
        "ByteOrder": "byte_order",
        "SwBaseTypeRef": "sw_base_type_ref",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_base_type_size_id = Column(types.Integer, ForeignKey('sw_base_type_size.rid', use_alter=True))
    sw_base_type_size = relationship('SwBaseTypeSize', foreign_keys=[sw_base_type_size_id], uselist=False, cascade="all")
    sw_coded_type_id = Column(types.Integer, ForeignKey('sw_coded_type.rid', use_alter=True))
    sw_coded_type = relationship('SwCodedType', foreign_keys=[sw_coded_type_id], uselist=False, cascade="all")
    sw_mem_alignment_id = Column(types.Integer, ForeignKey('sw_mem_alignment.rid', use_alter=True))
    sw_mem_alignment = relationship('SwMemAlignment', foreign_keys=[sw_mem_alignment_id], uselist=False, cascade="all")
    byte_order_id = Column(types.Integer, ForeignKey('byte_order.rid', use_alter=True))
    byte_order = relationship('ByteOrder', foreign_keys=[byte_order_id], uselist=False, cascade="all")
    sw_base_type_ref_id = Column(types.Integer, ForeignKey('sw_base_type_ref.rid', use_alter=True))
    sw_base_type_ref = relationship('SwBaseTypeRef', foreign_keys=[sw_base_type_ref_id], uselist=False, cascade="all")

class SwMcCommunicationSpec(Base):

    __tablename__ = "sw_mc_communication_spec"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": "na",
        "Tbd": "tbd",
        "Tbr": "tbr",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "SwMcInterfaceSpec": "sw_mc_interface_spec",
        "SwMcBaseTypes": "sw_mc_base_types",
        "SwMcInterfaceImpls": "sw_mc_interface_impls",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    na_id = Column(types.Integer, ForeignKey('na.rid', use_alter=True))
    na = relationship('Na', foreign_keys=[na_id], uselist=False, cascade="all")
    tbd_id = Column(types.Integer, ForeignKey('tbd.rid', use_alter=True))
    tbd = relationship('Tbd', foreign_keys=[tbd_id], uselist=False, cascade="all")
    tbr_id = Column(types.Integer, ForeignKey('tbr.rid', use_alter=True))
    tbr = relationship('Tbr', foreign_keys=[tbr_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    sw_mc_interface_spec_id = Column(types.Integer, ForeignKey('sw_mc_interface_spec.rid', use_alter=True))
    sw_mc_interface_spec = relationship('SwMcInterfaceSpec', foreign_keys=[sw_mc_interface_spec_id], uselist=False, cascade="all")
    sw_mc_base_types_id = Column(types.Integer, ForeignKey('sw_mc_base_types.rid', use_alter=True))
    sw_mc_base_types = relationship('SwMcBaseTypes', foreign_keys=[sw_mc_base_types_id], uselist=False, cascade="all")
    sw_mc_interface_impls_id = Column(types.Integer, ForeignKey('sw_mc_interface_impls.rid', use_alter=True))
    sw_mc_interface_impls = relationship('SwMcInterfaceImpls', foreign_keys=[sw_mc_interface_impls_id], uselist=False, cascade="all")

class SwMcBlobValue(Base):

    __tablename__ = "sw_mc_blob_value"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class SwMcGenericInterfaces(Base):

    __tablename__ = "sw_mc_generic_interfaces"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcGenericInterface": "sw_mc_generic_interface",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_generic_interface_id = Column(types.Integer, ForeignKey('sw_mc_generic_interface.rid', use_alter=True))
    sw_mc_generic_interface = relationship('SwMcGenericInterface', foreign_keys=[sw_mc_generic_interface_id], uselist=True, cascade="all")

class SwMcBlobEcuDeposit(Base):

    __tablename__ = "sw_mc_blob_ecu_deposit"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwInstanceRef": "sw_instance_ref",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_instance_ref_id = Column(types.Integer, ForeignKey('sw_instance_ref.rid', use_alter=True))
    sw_instance_ref = relationship('SwInstanceRef', foreign_keys=[sw_instance_ref_id], uselist=False, cascade="all")

class SwMcTpBlobConts(Base):

    __tablename__ = "sw_mc_tp_blob_conts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcBlobValue": "sw_mc_blob_value",
        "SwMcBlobEcuDeposit": "sw_mc_blob_ecu_deposit",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_blob_value_id = Column(types.Integer, ForeignKey('sw_mc_blob_value.rid', use_alter=True))
    sw_mc_blob_value = relationship('SwMcBlobValue', foreign_keys=[sw_mc_blob_value_id], uselist=False, cascade="all")
    sw_mc_blob_ecu_deposit_id = Column(types.Integer, ForeignKey('sw_mc_blob_ecu_deposit.rid', use_alter=True))
    sw_mc_blob_ecu_deposit = relationship('SwMcBlobEcuDeposit', foreign_keys=[sw_mc_blob_ecu_deposit_id], uselist=False, cascade="all")

class SwMcInterfaceSources(Base):

    __tablename__ = "sw_mc_interface_sources"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceSource": "sw_mc_interface_source",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_interface_source_id = Column(types.Integer, ForeignKey('sw_mc_interface_source.rid', use_alter=True))
    sw_mc_interface_source = relationship('SwMcInterfaceSource', foreign_keys=[sw_mc_interface_source_id], uselist=True, cascade="all")

class SwMcGenericInterface(Base):

    __tablename__ = "sw_mc_generic_interface"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "ShortLabel": "short_label",
        "Desc": "_desc",
        "SwMcInterfaceDefaultSource": "sw_mc_interface_default_source",
        "SwMcInterfaceAvlSources": "sw_mc_interface_avl_sources",
        "SwMcKpBlobConts": "sw_mc_kp_blob_conts",
        "SwMcDpBlobConts": "sw_mc_dp_blob_conts",
        "SwMcPaBlobConts": "sw_mc_pa_blob_conts",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    short_label_id = Column(types.Integer, ForeignKey('short_label.rid', use_alter=True))
    short_label = relationship('ShortLabel', foreign_keys=[short_label_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    sw_mc_interface_default_source_id = Column(types.Integer, ForeignKey('sw_mc_interface_default_source.rid', use_alter=True))
    sw_mc_interface_default_source = relationship('SwMcInterfaceDefaultSource', foreign_keys=[sw_mc_interface_default_source_id], uselist=False, cascade="all")
    sw_mc_interface_avl_sources_id = Column(types.Integer, ForeignKey('sw_mc_interface_avl_sources.rid', use_alter=True))
    sw_mc_interface_avl_sources = relationship('SwMcInterfaceAvlSources', foreign_keys=[sw_mc_interface_avl_sources_id], uselist=False, cascade="all")
    sw_mc_kp_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_kp_blob_conts.rid', use_alter=True))
    sw_mc_kp_blob_conts = relationship('SwMcKpBlobConts', foreign_keys=[sw_mc_kp_blob_conts_id], uselist=False, cascade="all")
    sw_mc_dp_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_dp_blob_conts.rid', use_alter=True))
    sw_mc_dp_blob_conts = relationship('SwMcDpBlobConts', foreign_keys=[sw_mc_dp_blob_conts_id], uselist=False, cascade="all")
    sw_mc_pa_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_pa_blob_conts.rid', use_alter=True))
    sw_mc_pa_blob_conts = relationship('SwMcPaBlobConts', foreign_keys=[sw_mc_pa_blob_conts_id], uselist=False, cascade="all")

class SwMcFrames(Base):

    __tablename__ = "sw_mc_frames"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcFrame": "sw_mc_frame",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_frame_id = Column(types.Integer, ForeignKey('sw_mc_frame.rid', use_alter=True))
    sw_mc_frame = relationship('SwMcFrame', foreign_keys=[sw_mc_frame_id], uselist=True, cascade="all")

class SwMcQpBlobConts(Base):

    __tablename__ = "sw_mc_qp_blob_conts"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcBlobValue": "sw_mc_blob_value",
        "SwMcBlobEcuDeposit": "sw_mc_blob_ecu_deposit",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sw_mc_blob_value_id = Column(types.Integer, ForeignKey('sw_mc_blob_value.rid', use_alter=True))
    sw_mc_blob_value = relationship('SwMcBlobValue', foreign_keys=[sw_mc_blob_value_id], uselist=False, cascade="all")
    sw_mc_blob_ecu_deposit_id = Column(types.Integer, ForeignKey('sw_mc_blob_ecu_deposit.rid', use_alter=True))
    sw_mc_blob_ecu_deposit = relationship('SwMcBlobEcuDeposit', foreign_keys=[sw_mc_blob_ecu_deposit_id], uselist=False, cascade="all")

class SwMcInterfaceSource(Base):

    __tablename__ = "sw_mc_interface_source"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwRefreshTiming": "sw_refresh_timing",
        "SwMcQpBlobConts": "sw_mc_qp_blob_conts",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_refresh_timing_id = Column(types.Integer, ForeignKey('sw_refresh_timing.rid', use_alter=True))
    sw_refresh_timing = relationship('SwRefreshTiming', foreign_keys=[sw_refresh_timing_id], uselist=False, cascade="all")
    sw_mc_qp_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_qp_blob_conts.rid', use_alter=True))
    sw_mc_qp_blob_conts = relationship('SwMcQpBlobConts', foreign_keys=[sw_mc_qp_blob_conts_id], uselist=False, cascade="all")

class SwMcInterfaceImpl(Base):

    __tablename__ = "sw_mc_interface_impl"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": "admin_data",
        "SwMcInterfaceRef": "sw_mc_interface_ref",
        "SwMcTpBlobConts": "sw_mc_tp_blob_conts",
        "SwMcGenericInterfaces": "sw_mc_generic_interfaces",
        "SwMcInterfaceSources": "sw_mc_interface_sources",
        "SwMcFrames": "sw_mc_frames",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_mc_interface_ref_id = Column(types.Integer, ForeignKey('sw_mc_interface_ref.rid', use_alter=True))
    sw_mc_interface_ref = relationship('SwMcInterfaceRef', foreign_keys=[sw_mc_interface_ref_id], uselist=False, cascade="all")
    sw_mc_tp_blob_conts_id = Column(types.Integer, ForeignKey('sw_mc_tp_blob_conts.rid', use_alter=True))
    sw_mc_tp_blob_conts = relationship('SwMcTpBlobConts', foreign_keys=[sw_mc_tp_blob_conts_id], uselist=False, cascade="all")
    sw_mc_generic_interfaces_id = Column(types.Integer, ForeignKey('sw_mc_generic_interfaces.rid', use_alter=True))
    sw_mc_generic_interfaces = relationship('SwMcGenericInterfaces', foreign_keys=[sw_mc_generic_interfaces_id], uselist=False, cascade="all")
    sw_mc_interface_sources_id = Column(types.Integer, ForeignKey('sw_mc_interface_sources.rid', use_alter=True))
    sw_mc_interface_sources = relationship('SwMcInterfaceSources', foreign_keys=[sw_mc_interface_sources_id], uselist=False, cascade="all")
    sw_mc_frames_id = Column(types.Integer, ForeignKey('sw_mc_frames.rid', use_alter=True))
    sw_mc_frames = relationship('SwMcFrames', foreign_keys=[sw_mc_frames_id], uselist=False, cascade="all")

class SwMcFrame(Base):

    __tablename__ = "sw_mc_frame"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "AdminData": "admin_data",
        "SwRefreshTiming": "sw_refresh_timing",
        "SwVariableRefs": "sw_variable_refs",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_refresh_timing_id = Column(types.Integer, ForeignKey('sw_refresh_timing.rid', use_alter=True))
    sw_refresh_timing = relationship('SwRefreshTiming', foreign_keys=[sw_refresh_timing_id], uselist=False, cascade="all")
    sw_variable_refs_id = Column(types.Integer, ForeignKey('sw_variable_refs.rid', use_alter=True))
    sw_variable_refs = relationship('SwVariableRefs', foreign_keys=[sw_variable_refs_id], uselist=False, cascade="all")

class SpecialData(Base):

    __tablename__ = "special_data"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sdg": "sdg",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sdg_id = Column(types.Integer, ForeignKey('sdg.rid', use_alter=True))
    sdg = relationship('Sdg', foreign_keys=[sdg_id], uselist=True, cascade="all")

class MsrProcessingLog(Base):

    __tablename__ = "msr_processing_log"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": "p",
        "Verbatim": "verbatim",
        "Figure": "figure",
        "Formula": "formula",
        "List": "_list",
        "DefList": "def_list",
        "LabeledList": "labeled_list",
        "Note": "note",
        "Table": "table",
        "Prms": "prms",
        "MsrQueryP1": "msr_query_p_1",
        "Topic1": "topic_1",
        "MsrQueryTopic1": "msr_query_topic_1",
        "Chapter": "chapter",
        "MsrQueryChapter": "msr_query_chapter",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    p_id = Column(types.Integer, ForeignKey('p.rid', use_alter=True))
    p = relationship('P', foreign_keys=[p_id], uselist=True, cascade="all")
    verbatim_id = Column(types.Integer, ForeignKey('verbatim.rid', use_alter=True))
    verbatim = relationship('Verbatim', foreign_keys=[verbatim_id], uselist=True, cascade="all")
    figure_id = Column(types.Integer, ForeignKey('figure.rid', use_alter=True))
    figure = relationship('Figure', foreign_keys=[figure_id], uselist=True, cascade="all")
    formula_id = Column(types.Integer, ForeignKey('formula.rid', use_alter=True))
    formula = relationship('Formula', foreign_keys=[formula_id], uselist=True, cascade="all")
    list_id = Column(types.Integer, ForeignKey('list.rid', use_alter=True))
    _list = relationship('List', foreign_keys=[list_id], uselist=True, cascade="all")
    def_list_id = Column(types.Integer, ForeignKey('def_list.rid', use_alter=True))
    def_list = relationship('DefList', foreign_keys=[def_list_id], uselist=True, cascade="all")
    labeled_list_id = Column(types.Integer, ForeignKey('labeled_list.rid', use_alter=True))
    labeled_list = relationship('LabeledList', foreign_keys=[labeled_list_id], uselist=True, cascade="all")
    note_id = Column(types.Integer, ForeignKey('note.rid', use_alter=True))
    note = relationship('Note', foreign_keys=[note_id], uselist=True, cascade="all")
    table_id = Column(types.Integer, ForeignKey('table.rid', use_alter=True))
    table = relationship('Table', foreign_keys=[table_id], uselist=True, cascade="all")
    prms_id = Column(types.Integer, ForeignKey('prms.rid', use_alter=True))
    prms = relationship('Prms', foreign_keys=[prms_id], uselist=True, cascade="all")
    msr_query_p_1_id = Column(types.Integer, ForeignKey('msr_query_p_1.rid', use_alter=True))
    msr_query_p_1 = relationship('MsrQueryP1', foreign_keys=[msr_query_p_1_id], uselist=True, cascade="all")
    topic_1_id = Column(types.Integer, ForeignKey('topic_1.rid', use_alter=True))
    topic_1 = relationship('Topic1', foreign_keys=[topic_1_id], uselist=True, cascade="all")
    msr_query_topic_1_id = Column(types.Integer, ForeignKey('msr_query_topic_1.rid', use_alter=True))
    msr_query_topic_1 = relationship('MsrQueryTopic1', foreign_keys=[msr_query_topic_1_id], uselist=True, cascade="all")
    chapter_id = Column(types.Integer, ForeignKey('chapter.rid', use_alter=True))
    chapter = relationship('Chapter', foreign_keys=[chapter_id], uselist=True, cascade="all")
    msr_query_chapter_id = Column(types.Integer, ForeignKey('msr_query_chapter.rid', use_alter=True))
    msr_query_chapter = relationship('MsrQueryChapter', foreign_keys=[msr_query_chapter_id], uselist=True, cascade="all")

class SdgCaption(Base):

    __tablename__ = "sdg_caption"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")

class Sdg(Base):

    __tablename__ = "sdg"
    ATTRIBUTES = {
        "GID": "gid",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SdgCaption": "sdg_caption",
        "Sd": "sd",
        "Sdg": "sdg",
        "Ncoi1": "ncoi_1",
        "Xref": "xref",
    }
    gid = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    sdg_caption_id = Column(types.Integer, ForeignKey('sdg_caption.rid', use_alter=True))
    sdg_caption = relationship('SdgCaption', foreign_keys=[sdg_caption_id], uselist=False, cascade="all")
    sd_id = Column(types.Integer, ForeignKey('sd.rid', use_alter=True))
    sd = relationship('Sd', foreign_keys=[sd_id], uselist=True, cascade="all")
    sdg_id = Column(types.Integer, ForeignKey('sdg.rid', use_alter=True))
    sdg = relationship('Sdg', foreign_keys=[sdg_id], uselist=True, cascade="all")
    ncoi_1_id = Column(types.Integer, ForeignKey('ncoi_1.rid', use_alter=True))
    ncoi_1 = relationship('Ncoi1', foreign_keys=[ncoi_1_id], uselist=True, cascade="all")
    xref_id = Column(types.Integer, ForeignKey('xref.rid', use_alter=True))
    xref = relationship('Xref', foreign_keys=[xref_id], uselist=True, cascade="all")

class DataFile(Base):

    __tablename__ = "data_file"
    ATTRIBUTES = {
        "Value": "value",
        "C": "c",
        "S": "s",
        "LC": "lc",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    value = StdString()
    c = StdString()
    s = StdString()
    lc = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()

class SwInstanceTreeOrigin(Base):

    __tablename__ = "sw_instance_tree_origin"
    ATTRIBUTES = {
        "C": "c",
        "LC": "lc",
        "S": "s",
        "SI": "si",
        "T": "t",
        "TI": "ti",
        "VIEW": "_view",
    }
    ELEMENTS = {
        "SymbolicFile": "symbolic_file",
        "DataFile": "data_file",
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    symbolic_file_id = Column(types.Integer, ForeignKey('symbolic_file.rid', use_alter=True))
    symbolic_file = relationship('SymbolicFile', foreign_keys=[symbolic_file_id], uselist=False, cascade="all")
    data_file_id = Column(types.Integer, ForeignKey('data_file.rid', use_alter=True))
    data_file = relationship('DataFile', foreign_keys=[data_file_id], uselist=False, cascade="all")

class SwInstanceTree(Base):

    __tablename__ = "sw_instance_tree"
    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "F-NAMESPACE": "f_namespace",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Desc": "_desc",
        "Category": "category",
        "SwInstanceTreeOrigin": "sw_instance_tree_origin",
        "SwCsCollections": "sw_cs_collections",
        "AdminData": "admin_data",
        "SwCsHistory": "sw_cs_history",
        "SwVcdCriterionValues": "sw_vcd_criterion_values",
        "SwFeatureRef": "sw_feature_ref",
        "SwInstance": "sw_instance",
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    desc_id = Column(types.Integer, ForeignKey('desc.rid', use_alter=True))
    _desc = relationship('Desc', foreign_keys=[desc_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    sw_instance_tree_origin_id = Column(types.Integer, ForeignKey('sw_instance_tree_origin.rid', use_alter=True))
    sw_instance_tree_origin = relationship('SwInstanceTreeOrigin', foreign_keys=[sw_instance_tree_origin_id], uselist=False, cascade="all")
    sw_cs_collections_id = Column(types.Integer, ForeignKey('sw_cs_collections.rid', use_alter=True))
    sw_cs_collections = relationship('SwCsCollections', foreign_keys=[sw_cs_collections_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    sw_cs_history_id = Column(types.Integer, ForeignKey('sw_cs_history.rid', use_alter=True))
    sw_cs_history = relationship('SwCsHistory', foreign_keys=[sw_cs_history_id], uselist=False, cascade="all")
    sw_vcd_criterion_values_id = Column(types.Integer, ForeignKey('sw_vcd_criterion_values.rid', use_alter=True))
    sw_vcd_criterion_values = relationship('SwVcdCriterionValues', foreign_keys=[sw_vcd_criterion_values_id], uselist=False, cascade="all")
    sw_feature_ref_id = Column(types.Integer, ForeignKey('sw_feature_ref.rid', use_alter=True))
    sw_feature_ref = relationship('SwFeatureRef', foreign_keys=[sw_feature_ref_id], uselist=False, cascade="all")
    sw_instance_id = Column(types.Integer, ForeignKey('sw_instance.rid', use_alter=True))
    sw_instance = relationship('SwInstance', foreign_keys=[sw_instance_id], uselist=True, cascade="all")

class Sd(Base):

    __tablename__ = "sd"
    ATTRIBUTES = {
        "GID": "gid",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    TERMINAL = True
    gid = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class MatchingDcis(Base):

    __tablename__ = "matching_dcis"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MatchingDci": "matching_dci",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    matching_dci_id = Column(types.Integer, ForeignKey('matching_dci.rid', use_alter=True))
    matching_dci = relationship('MatchingDci', foreign_keys=[matching_dci_id], uselist=True, cascade="all")

class Locs(Base):

    __tablename__ = "locs"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Nameloc": "nameloc",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    nameloc_id = Column(types.Integer, ForeignKey('nameloc.rid', use_alter=True))
    nameloc = relationship('Nameloc', foreign_keys=[nameloc_id], uselist=True, cascade="all")

class MatchingDci(Base):

    __tablename__ = "matching_dci"
    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": "label",
        "ShortLabel": "short_label",
        "Url": "url",
        "Remark": "remark",
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    label_id = Column(types.Integer, ForeignKey('label.rid', use_alter=True))
    label = relationship('Label', foreign_keys=[label_id], uselist=False, cascade="all")
    short_label_id = Column(types.Integer, ForeignKey('short_label.rid', use_alter=True))
    short_label = relationship('ShortLabel', foreign_keys=[short_label_id], uselist=False, cascade="all")
    url_id = Column(types.Integer, ForeignKey('url.rid', use_alter=True))
    url = relationship('Url', foreign_keys=[url_id], uselist=False, cascade="all")
    remark_id = Column(types.Integer, ForeignKey('remark.rid', use_alter=True))
    remark = relationship('Remark', foreign_keys=[remark_id], uselist=False, cascade="all")

class Msrsw(Base):

    __tablename__ = "msrsw"
    ATTRIBUTES = {
        "PUBID": "pubid",
        "F-PUBID": "f_pubid",
        "F-NAMESPACE": "f_namespace",
        "HYTIME": "hytime",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "ShortName": "short_name",
        "Category": "category",
        "ProjectData": "project_data",
        "AdminData": "admin_data",
        "Introduction": "introduction",
        "GeneralRequirements": "general_requirements",
        "SwSystems": "sw_systems",
        "SwMcCommunicationSpec": "sw_mc_communication_spec",
        "SwGlossary": "sw_glossary",
        "SpecialData": "special_data",
        "MsrProcessingLog": "msr_processing_log",
        "MatchingDcis": "matching_dcis",
        "Locs": "locs",
    }
    pubid = StdString()
    f_pubid = StdString()
    f_namespace = StdString()
    hytime = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    category_id = Column(types.Integer, ForeignKey('category.rid', use_alter=True))
    category = relationship('Category', foreign_keys=[category_id], uselist=False, cascade="all")
    project_data_id = Column(types.Integer, ForeignKey('project_data.rid', use_alter=True))
    project_data = relationship('ProjectData', foreign_keys=[project_data_id], uselist=False, cascade="all")
    admin_data_id = Column(types.Integer, ForeignKey('admin_data.rid', use_alter=True))
    admin_data = relationship('AdminData', foreign_keys=[admin_data_id], uselist=False, cascade="all")
    introduction_id = Column(types.Integer, ForeignKey('introduction.rid', use_alter=True))
    introduction = relationship('Introduction', foreign_keys=[introduction_id], uselist=False, cascade="all")
    general_requirements_id = Column(types.Integer, ForeignKey('general_requirements.rid', use_alter=True))
    general_requirements = relationship('GeneralRequirements', foreign_keys=[general_requirements_id], uselist=False, cascade="all")
    sw_systems_id = Column(types.Integer, ForeignKey('sw_systems.rid', use_alter=True))
    sw_systems = relationship('SwSystems', foreign_keys=[sw_systems_id], uselist=False, cascade="all")
    sw_mc_communication_spec_id = Column(types.Integer, ForeignKey('sw_mc_communication_spec.rid', use_alter=True))
    sw_mc_communication_spec = relationship('SwMcCommunicationSpec', foreign_keys=[sw_mc_communication_spec_id], uselist=False, cascade="all")
    sw_glossary_id = Column(types.Integer, ForeignKey('sw_glossary.rid', use_alter=True))
    sw_glossary = relationship('SwGlossary', foreign_keys=[sw_glossary_id], uselist=False, cascade="all")
    special_data_id = Column(types.Integer, ForeignKey('special_data.rid', use_alter=True))
    special_data = relationship('SpecialData', foreign_keys=[special_data_id], uselist=False, cascade="all")
    msr_processing_log_id = Column(types.Integer, ForeignKey('msr_processing_log.rid', use_alter=True))
    msr_processing_log = relationship('MsrProcessingLog', foreign_keys=[msr_processing_log_id], uselist=False, cascade="all")
    matching_dcis_id = Column(types.Integer, ForeignKey('matching_dcis.rid', use_alter=True))
    matching_dcis = relationship('MatchingDcis', foreign_keys=[matching_dcis_id], uselist=False, cascade="all")
    locs_id = Column(types.Integer, ForeignKey('locs.rid', use_alter=True))
    locs = relationship('Locs', foreign_keys=[locs_id], uselist=False, cascade="all")

class Nmlist(Base):

    __tablename__ = "nmlist"
    ATTRIBUTES = {
        "NAMETYPE": "nametype",
        "DOCORSUB": "docorsub",
        "HYTIME": "hytime",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
    }
    ENUMS = {
        "nametype": ['ENTITY', 'ELEMENT'],
    }
    TERMINAL = True
    nametype = StdString()
    docorsub = StdString()
    hytime = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

class Nameloc(Base):

    __tablename__ = "nameloc"
    ATTRIBUTES = {
        "ID": "_id",
        "EXT-ID-CLASS": "ext_id_class",
        "F-ID-CLASS": "f_id_class",
        "HYTIME": "hytime",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": "long_name",
        "ShortName": "short_name",
        "Nmlist": "nmlist",
    }
    _id = StdString()
    ext_id_class = StdString()
    f_id_class = StdString()
    hytime = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    long_name_id = Column(types.Integer, ForeignKey('long_name.rid', use_alter=True))
    long_name = relationship('LongName', foreign_keys=[long_name_id], uselist=False, cascade="all")
    short_name_id = Column(types.Integer, ForeignKey('short_name.rid', use_alter=True))
    short_name = relationship('ShortName', foreign_keys=[short_name_id], uselist=False, cascade="all")
    nmlist_id = Column(types.Integer, ForeignKey('nmlist.rid', use_alter=True))
    nmlist = relationship('Nmlist', foreign_keys=[nmlist_id], uselist=False, cascade="all")


#
# Properties
#

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
    "SHORT-NAME": ShortName,
    "CATEGORY": Category,
    "LABEL": Label,
    "LANGUAGE": Language,
    "DESC": Desc,
    "OVERALL-PROJECT": OverallProject,
    "TT": Tt,
    "E": E,
    "SUP": Sup,
    "SUB": Sub,
    "IE": Ie,
    "COMPANIES": Companies,
    "XREF": Xref,
    "LONG-NAME-1": LongName1,
    "XREF-TARGET": XrefTarget,
    "FT": Ft,
    "MSR-QUERY-NAME": MsrQueryName,
    "MSR-QUERY-RESULT-TEXT": MsrQueryResultText,
    "COMMENT": Comment,
    "MSR-QUERY-ARG": MsrQueryArg,
    "MSR-QUERY-PROPS": MsrQueryProps,
    "MSR-QUERY-TEXT": MsrQueryText,
    "NA": Na,
    "TEAM-MEMBER-REFS": TeamMemberRefs,
    "LONG-NAME": LongName,
    "ROLES": Roles,
    "TEAM-MEMBERS": TeamMembers,
    "ROLE": Role,
    "COMPANY": Company,
    "DEPARTMENT": Department,
    "ADDRESS": Address,
    "ZIP": Zip,
    "CITY": City,
    "PHONE": Phone,
    "FAX": Fax,
    "EMAIL": Email,
    "HOMEPAGE": Homepage,
    "TEAM-MEMBER": TeamMember,
    "SAMPLE-REF": SampleRef,
    "DATE": Date,
    "TBR": Tbr,
    "SCHEDULE": Schedule,
    "TEAM-MEMBER-REF": TeamMemberRef,
    "TBD": Tbd,
    "USED-LANGUAGES": UsedLanguages,
    "COMPANY-DOC-INFOS": CompanyDocInfos,
    "FORMATTER-CTRLS": FormatterCtrls,
    "SUBTITLE": Subtitle,
    "STATE-1": State1,
    "DATE-1": Date1,
    "URL": Url,
    "POSITION": Position,
    "STD": Std,
    "NUMBER": Number,
    "PUBLISHER": Publisher,
    "XDOC": Xdoc,
    "NOTATION": Notation,
    "TOOL": Tool,
    "TOOL-VERSION": ToolVersion,
    "XFILE": Xfile,
    "INTRODUCTION": Introduction,
    "DOC-REVISIONS": DocRevisions,
    "ADMIN-DATA": AdminData,
    "NCOI-1": Ncoi1,
    "COMPANY-REF": CompanyRef,
    "DOC-LABEL": DocLabel,
    "PRIVATE-CODES": PrivateCodes,
    "ENTITY-NAME": EntityName,
    "PRIVATE-CODE": PrivateCode,
    "COMPANY-DOC-INFO": CompanyDocInfo,
    "SYSTEM-OVERVIEW": SystemOverview,
    "FORMATTER-CTRL": FormatterCtrl,
    "REASON-ORDER": ReasonOrder,
    "COMPANY-REVISION-INFOS": CompanyRevisionInfos,
    "REVISION-LABEL": RevisionLabel,
    "STATE": State,
    "REMARK": Remark,
    "ISSUED-BY": IssuedBy,
    "COMPANY-REVISION-INFO": CompanyRevisionInfo,
    "P": P,
    "VERBATIM": Verbatim,
    "FIGURE-CAPTION": FigureCaption,
    "GRAPHIC": Graphic,
    "MAP": Map,
    "FIGURE": Figure,
    "AREA": Area,
    "FORMULA-CAPTION": FormulaCaption,
    "TEX-MATH": TexMath,
    "C-CODE": CCode,
    "GENERIC-MATH": GenericMath,
    "FORMULA": Formula,
    "LIST": List,
    "ITEM": Item,
    "DEF-LIST": DefList,
    "DEF": Def,
    "DEF-ITEM": DefItem,
    "INDENT-SAMPLE": IndentSample,
    "LABELED-LIST": LabeledList,
    "ITEM-LABEL": ItemLabel,
    "LABELED-ITEM": LabeledItem,
    "NOTE": Note,
    "MODIFICATIONS": Modifications,
    "DOC-REVISION": DocRevision,
    "CHANGE": Change,
    "REASON": Reason,
    "MODIFICATION": Modification,
    "PRODUCT-DESC": ProductDesc,
    "TABLE-CAPTION": TableCaption,
    "TABLE": Table,
    "THEAD": Thead,
    "COLSPEC": Colspec,
    "SPANSPEC": Spanspec,
    "TFOOT": Tfoot,
    "ROW": Row,
    "ENTRY": Entry,
    "TBODY": Tbody,
    "TGROUP": Tgroup,
    "MSR-QUERY-RESULT-P-2": MsrQueryResultP2,
    "MSR-QUERY-P-2": MsrQueryP2,
    "TOPIC-2": Topic2,
    "MSR-QUERY-RESULT-TOPIC-2": MsrQueryResultTopic2,
    "MSR-QUERY-TOPIC-2": MsrQueryTopic2,
    "OBJECTIVES": Objectives,
    "RIGHTS": Rights,
    "PRMS": Prms,
    "PRM": Prm,
    "COND": Cond,
    "ABS": Abs,
    "TOL": Tol,
    "MIN": Min,
    "TYP": Typ,
    "MAX": Max,
    "UNIT": Unit,
    "TEXT": Text,
    "PRM-CHAR": PrmChar,
    "MSR-QUERY-RESULT-P-1": MsrQueryResultP1,
    "MSR-QUERY-P-1": MsrQueryP1,
    "TOPIC-1": Topic1,
    "MSR-QUERY-RESULT-TOPIC-1": MsrQueryResultTopic1,
    "MSR-QUERY-TOPIC-1": MsrQueryTopic1,
    "CHAPTER": Chapter,
    "MSR-QUERY-RESULT-CHAPTER": MsrQueryResultChapter,
    "MSR-QUERY-CHAPTER": MsrQueryChapter,
    "GUARANTEE": Guarantee,
    "MAINTENANCE": Maintenance,
    "SAMPLES": Samples,
    "ADD-SPEC": AddSpec,
    "CONTRACT-ASPECTS": ContractAspects,
    "SAMPLE-SPEC": SampleSpec,
    "VARIANT-CHARS": VariantChars,
    "VARIANT-DEFS": VariantDefs,
    "VARIANT-SPEC": VariantSpec,
    "SAMPLE": Sample,
    "DEMARCATION-OTHER-PROJECTS": DemarcationOtherProjects,
    "PARALLEL-DESIGNS": ParallelDesigns,
    "CODE": Code,
    "VARIANT-CHAR": VariantChar,
    "INTEGRATION-CAPABILITY": IntegrationCapability,
    "VARIANT-CHAR-ASSIGNS": VariantCharAssigns,
    "VARIANT-DEF": VariantDef,
    "VARIANT-CHAR-REF": VariantCharRef,
    "VALUE": Value,
    "VARIANT-CHAR-VALUE": VariantCharValue,
    "VARIANT-CHAR-ASSIGN": VariantCharAssign,
    "ACCEPTANCE-COND": AcceptanceCond,
    "PROJECT-SCHEDULE": ProjectSchedule,
    "PURCHASING-COND": PurchasingCond,
    "PROTOCOLS": Protocols,
    "DIR-HAND-OVER-DOC-DATA": DirHandOverDocData,
    "GENERAL-PROJECT-DATA": GeneralProjectData,
    "PROJECT": Project,
    "PROJECT-DATA": ProjectData,
    "SW-SYSTEMS": SwSystems,
    "REQUIREMENTS": Requirements,
    "FUNCTION-OVERVIEW": FunctionOverview,
    "FREE-INFO": FreeInfo,
    "PRM-REFS": PrmRefs,
    "KEY-DATA": KeyData,
    "PRODUCT-DEMARCATION": ProductDemarcation,
    "PRM-REF": PrmRef,
    "SIMILAR-PRODUCTS": SimilarProducts,
    "OPERATING-ENV": OperatingEnv,
    "USEFUL-LIFE-PRMS": UsefulLifePrms,
    "NCOI-3": Ncoi3,
    "RELIABILITY-PRMS": ReliabilityPrms,
    "USEFUL-LIFE": UsefulLife,
    "AVAILABILITY": Availability,
    "LIFE-TIME": LifeTime,
    "OPERATING-TIME": OperatingTime,
    "RELIABILITY": Reliability,
    "GENERAL-HARDWARE": GeneralHardware,
    "NORMATIVE-REFERENCE": NormativeReference,
    "MTBF": Mtbf,
    "PPM": Ppm,
    "DATA-STRUCTURES": DataStructures,
    "DATA-DESC": DataDesc,
    "RESTRICTIONS-BY-HARDWARE": RestrictionsByHardware,
    "STANDARD-SW-MODULES": StandardSwModules,
    "DESIGN-REQUIREMENTS": DesignRequirements,
    "BINARY-COMPATIBILITY": BinaryCompatibility,
    "DATA-REQUIREMENTS": DataRequirements,
    "EXTENSIBILITY": Extensibility,
    "COMPATIBILITY": Compatibility,
    "GENERAL-SOFTWARE": GeneralSoftware,
    "USER-INTERFACE": UserInterface,
    "HARDWARE-INTERFACE": HardwareInterface,
    "INTERNAL-INTERFACES": InternalInterfaces,
    "COMMUNICATION-INTERFACE": CommunicationInterface,
    "FLASH-PROGRAMMING": FlashProgramming,
    "GENERAL-INTERFACES": GeneralInterfaces,
    "FMEA": Fmea,
    "FAIL-SAVE-CONCEPT": FailSaveConcept,
    "REPLACEMENT-VALUES": ReplacementValues,
    "FAILURE-MEM": FailureMem,
    "SELF-DIAGNOSIS": SelfDiagnosis,
    "FAILURE-MANAGEMENT": FailureManagement,
    "RESOURCE-ALLOCATION": ResourceAllocation,
    "CALIBRATION": Calibration,
    "SAFETY": Safety,
    "QUALITY": Quality,
    "GENERAL-COND": GeneralCond,
    "ADD-DESIGN-DOC": AddDesignDoc,
    "DEVELOPMENT-PROCESS-SPEC": DevelopmentProcessSpec,
    "GENERAL-PRODUCT-DATA-1": GeneralProductData1,
    "REQUIREMENT-SPEC": RequirementSpec,
    "MONITORING": Monitoring,
    "DIAGNOSIS": Diagnosis,
    "REQUIREMENT-BODY": RequirementBody,
    "CRITICAL-ASPECTS": CriticalAspects,
    "TECHNICAL-ASPECTS": TechnicalAspects,
    "REALTIME-REQUIREMENTS": RealtimeRequirements,
    "RISKS": Risks,
    "REQUIREMENTS-DEPENDENCY": RequirementsDependency,
    "ADD-INFO": AddInfo,
    "REQUIREMENT": Requirement,
    "COMMUNICATION": Communication,
    "OPERATIONAL-REQUIREMENTS": OperationalRequirements,
    "FUNCTIONAL-REQUIREMENTS": FunctionalRequirements,
    "GENERAL-REQUIREMENTS": GeneralRequirements,
    "SW-MC-INTERFACE-SPEC": SwMcInterfaceSpec,
    "OVERVIEW": Overview,
    "SW-TEST-SPEC": SwTestSpec,
    "SW-TASKS": SwTasks,
    "SW-TASK-SPEC": SwTaskSpec,
    "INTERRUPT-SPEC": InterruptSpec,
    "SW-CSE-CODE": SwCseCode,
    "SW-CSE-CODE-FACTOR": SwCseCodeFactor,
    "SW-REFRESH-TIMING": SwRefreshTiming,
    "SW-TASK": SwTask,
    "TIME-DEPENDENCY": TimeDependency,
    "SW-ARCHITECTURE": SwArchitecture,
    "SW-UNITS": SwUnits,
    "SW-COMPONENTS": SwComponents,
    "SW-TEMPLATES": SwTemplates,
    "SW-UNIT-DISPLAY": SwUnitDisplay,
    "SW-UNIT-GRADIENT": SwUnitGradient,
    "SI-UNIT": SiUnit,
    "SW-UNIT-OFFSET": SwUnitOffset,
    "SW-UNIT-CONVERSION-METHOD": SwUnitConversionMethod,
    "SW-UNIT-REF": SwUnitRef,
    "SW-UNIT": SwUnit,
    "SW-VARIABLES": SwVariables,
    "ANNOTATIONS": Annotations,
    "SW-ADDR-METHOD-REF": SwAddrMethodRef,
    "SW-ALIAS-NAME": SwAliasName,
    "ANNOTATION-ORIGIN": AnnotationOrigin,
    "ANNOTATION-TEXT": AnnotationText,
    "ANNOTATION": Annotation,
    "SW-BASE-TYPE-REF": SwBaseTypeRef,
    "BIT-POSITION": BitPosition,
    "NUMBER-OF-BITS": NumberOfBits,
    "SW-BIT-REPRESENTATION": SwBitRepresentation,
    "SW-CALIBRATION-ACCESS": SwCalibrationAccess,
    "SW-CALPRM-AXIS-SET": SwCalprmAxisSet,
    "SW-CALPRM-NO-EFFECT-VALUE": SwCalprmNoEffectValue,
    "SW-TEMPLATE-REF": SwTemplateRef,
    "SW-AXIS-INDEX": SwAxisIndex,
    "SW-VARIABLE-REFS": SwVariableRefs,
    "SW-CALPRM-REF": SwCalprmRef,
    "SW-COMPU-METHOD-REF": SwCompuMethodRef,
    "SW-VARIABLE-REF": SwVariableRef,
    "SW-MAX-AXIS-POINTS": SwMaxAxisPoints,
    "SW-MIN-AXIS-POINTS": SwMinAxisPoints,
    "SW-SYSTEMCONST-CODED-REF": SwSystemconstCodedRef,
    "SW-SYSTEMCONST-PHYS-REF": SwSystemconstPhysRef,
    "SW-DATA-CONSTR-REF": SwDataConstrRef,
    "SW-AXIS-TYPE-REF": SwAxisTypeRef,
    "SW-NUMBER-OF-AXIS-POINTS": SwNumberOfAxisPoints,
    "SW-GENERIC-AXIS-PARAMS": SwGenericAxisParams,
    "SW-VALUES-PHYS": SwValuesPhys,
    "SW-VALUES-CODED": SwValuesCoded,
    "SW-GENERIC-AXIS-PARAM-TYPE-REF": SwGenericAxisParamTypeRef,
    "SW-GENERIC-AXIS-PARAM": SwGenericAxisParam,
    "VF": Vf,
    "SW-AXIS-GENERIC": SwAxisGeneric,
    "VT": Vt,
    "VH": Vh,
    "V": V,
    "VG": Vg,
    "SW-INSTANCE-REF": SwInstanceRef,
    "SW-AXIS-INDIVIDUAL": SwAxisIndividual,
    "SW-DISPLAY-FORMAT": SwDisplayFormat,
    "SW-AXIS-GROUPED": SwAxisGrouped,
    "SW-CALPRM-AXIS": SwCalprmAxis,
    "SW-CLASS-ATTR-IMPL-REF": SwClassAttrImplRef,
    "SW-CALPRM-POINTER": SwCalprmPointer,
    "SW-CALPRM-TARGET": SwCalprmTarget,
    "SW-CALPRM-MAX-TEXT-SIZE": SwCalprmMaxTextSize,
    "SW-FILL-CHARACTER": SwFillCharacter,
    "SW-CALPRM-TEXT": SwCalprmText,
    "SW-CALPRM-VALUE-AXIS-LABELS": SwCalprmValueAxisLabels,
    "SW-CODE-SYNTAX-REF": SwCodeSyntaxRef,
    "SW-COMPARISON-VARIABLES": SwComparisonVariables,
    "SW-DATA-DEPENDENCY-FORMULA": SwDataDependencyFormula,
    "SW-DATA-DEPENDENCY-ARGS": SwDataDependencyArgs,
    "SW-DATA-DEPENDENCY": SwDataDependency,
    "SW-HOST-VARIABLE": SwHostVariable,
    "SW-IMPL-POLICY": SwImplPolicy,
    "SW-INTENDED-RESOLUTION": SwIntendedResolution,
    "SW-INTERPOLATION-METHOD": SwInterpolationMethod,
    "SW-IS-VIRTUAL": SwIsVirtual,
    "SW-MC-BASE-TYPE-REF": SwMcBaseTypeRef,
    "SW-RECORD-LAYOUT-REF": SwRecordLayoutRef,
    "SW-TASK-REF": SwTaskRef,
    "SW-VARIABLE-KIND": SwVariableKind,
    "SW-VAR-INIT-VALUE": SwVarInitValue,
    "SW-VAR-NOT-AVL-VALUE": SwVarNotAvlValue,
    "SW-VCD-CRITERION-REFS": SwVcdCriterionRefs,
    "SW-DATA-DEF-PROPS": SwDataDefProps,
    "SW-TEMPLATE": SwTemplate,
    "SW-VCD-CRITERION-REF": SwVcdCriterionRef,
    "SW-CALPRMS": SwCalprms,
    "SW-ARRAYSIZE": SwArraysize,
    "SW-VARIABLE": SwVariable,
    "SW-SYSTEMCONSTS": SwSystemconsts,
    "SW-CALPRM": SwCalprm,
    "SW-CLASS-INSTANCES": SwClassInstances,
    "SW-SYSTEMCONST": SwSystemconst,
    "SW-COMPU-METHODS": SwCompuMethods,
    "SW-CLASS-REF": SwClassRef,
    "SW-CLASS-INSTANCE": SwClassInstance,
    "SW-ADDR-METHODS": SwAddrMethods,
    "SW-PHYS-CONSTRS-1": SwPhysConstrs1,
    "SW-INTERNAL-CONSTRS-1": SwInternalConstrs1,
    "LOWER-LIMIT": LowerLimit,
    "UPPER-LIMIT": UpperLimit,
    "SW-SCALE-CONSTR": SwScaleConstr,
    "SW-COMPU-IDENTITY": SwCompuIdentity,
    "SW-COMPU-SCALES": SwCompuScales,
    "SW-COMPU-DEFAULT-VALUE": SwCompuDefaultValue,
    "SW-COMPU-INTERNAL-TO-PHYS": SwCompuInternalToPhys,
    "C-IDENTIFIER": CIdentifier,
    "SW-COMPU-INVERSE-VALUE": SwCompuInverseValue,
    "SW-COMPU-CONST": SwCompuConst,
    "SW-COMPU-NUMERATOR": SwCompuNumerator,
    "SW-COMPU-PROGRAM-CODE": SwCompuProgramCode,
    "SW-COMPU-DENOMINATOR": SwCompuDenominator,
    "SW-COMPU-RATIONAL-COEFFS": SwCompuRationalCoeffs,
    "SW-COMPU-GENERIC-MATH": SwCompuGenericMath,
    "SW-COMPU-SCALE": SwCompuScale,
    "SW-COMPU-PHYS-TO-INTERNAL": SwCompuPhysToInternal,
    "SW-COMPU-METHOD": SwCompuMethod,
    "SW-RECORD-LAYOUTS": SwRecordLayouts,
    "SW-CPU-MEM-SEG-REF": SwCpuMemSegRef,
    "SW-ADDR-METHOD-DESC": SwAddrMethodDesc,
    "SW-ADDR-METHOD": SwAddrMethod,
    "SW-CODE-SYNTAXES": SwCodeSyntaxes,
    "SW-RECORD-LAYOUT": SwRecordLayout,
    "SW-RECORD-LAYOUT-GROUP-AXIS": SwRecordLayoutGroupAxis,
    "SW-RECORD-LAYOUT-GROUP-INDEX": SwRecordLayoutGroupIndex,
    "SW-RECORD-LAYOUT-GROUP-FROM": SwRecordLayoutGroupFrom,
    "SW-RECORD-LAYOUT-GROUP-TO": SwRecordLayoutGroupTo,
    "SW-RECORD-LAYOUT-GROUP-STEP": SwRecordLayoutGroupStep,
    "SW-RECORD-LAYOUT-COMPONENT": SwRecordLayoutComponent,
    "SW-RECORD-LAYOUT-GROUP": SwRecordLayoutGroup,
    "SW-RECORD-LAYOUT-V-AXIS": SwRecordLayoutVAxis,
    "SW-RECORD-LAYOUT-V-PROP": SwRecordLayoutVProp,
    "SW-RECORD-LAYOUT-V-INDEX": SwRecordLayoutVIndex,
    "SW-RECORD-LAYOUT-V-FIX-VALUE": SwRecordLayoutVFixValue,
    "SW-RECORD-LAYOUT-V": SwRecordLayoutV,
    "SW-BASE-TYPES": SwBaseTypes,
    "SW-CODE-SYNTAX-DESC": SwCodeSyntaxDesc,
    "SW-CODE-SYNTAX": SwCodeSyntax,
    "SW-DATA-CONSTRS": SwDataConstrs,
    "SW-BASE-TYPE-SIZE": SwBaseTypeSize,
    "SW-CODED-TYPE": SwCodedType,
    "SW-MEM-ALIGNMENT": SwMemAlignment,
    "BYTE-ORDER": ByteOrder,
    "SW-BASE-TYPE": SwBaseType,
    "SW-AXIS-TYPES": SwAxisTypes,
    "SW-CONSTR-OBJECTS": SwConstrObjects,
    "SW-DATA-CONSTR": SwDataConstr,
    "SW-CONSTR-LEVEL": SwConstrLevel,
    "SW-MAX-GRADIENT": SwMaxGradient,
    "SW-SCALE-CONSTRS": SwScaleConstrs,
    "SW-MAX-DIFF": SwMaxDiff,
    "SW-MONOTONY": SwMonotony,
    "SW-RELATED-CONSTRS": SwRelatedConstrs,
    "SW-INTERNAL-CONSTRS": SwInternalConstrs,
    "SW-PHYS-CONSTRS": SwPhysConstrs,
    "SW-DATA-CONSTR-RULE": SwDataConstrRule,
    "SW-DATA-DICTIONARY-SPEC": SwDataDictionarySpec,
    "SW-GENERIC-AXIS-DESC": SwGenericAxisDesc,
    "SW-GENERIC-AXIS-PARAM-TYPES": SwGenericAxisParamTypes,
    "SW-AXIS-TYPE": SwAxisType,
    "SW-GENERIC-AXIS-PARAM-TYPE": SwGenericAxisParamType,
    "SW-INSTANCE-SPEC": SwInstanceSpec,
    "SW-ROOT-FEATURES": SwRootFeatures,
    "SW-FEATURE-DEF": SwFeatureDef,
    "SW-FEATURE-DESC": SwFeatureDesc,
    "SW-FULFILS": SwFulfils,
    "SW-CLASS-METHODS": SwClassMethods,
    "FUNCTION-REF": FunctionRef,
    "REQUIREMENT-REF": RequirementRef,
    "SW-VARIABLE-PROTOTYPES": SwVariablePrototypes,
    "SHORT-LABEL": ShortLabel,
    "SW-CLASS-METHOD-RETURN": SwClassMethodReturn,
    "SW-CLASS-METHOD": SwClassMethod,
    "SW-CLASS-METHOD-ARG": SwClassMethodArg,
    "SW-CLASS-ATTR-IMPLS": SwClassAttrImpls,
    "SW-CALPRM-PROTOTYPES": SwCalprmPrototypes,
    "SW-SYSCOND": SwSyscond,
    "SW-VARIABLE-PROTOTYPE": SwVariablePrototype,
    "SW-CLASS-PROTOTYPES": SwClassPrototypes,
    "SW-CALPRM-PROTOTYPE": SwCalprmPrototype,
    "SW-CLASS-ATTR": SwClassAttr,
    "SW-CLASS-PROTOTYPE": SwClassPrototype,
    "SW-VARIABLES-READ": SwVariablesRead,
    "SW-VARIABLE-IMPLS": SwVariableImpls,
    "SW-CALPRM-IMPLS": SwCalprmImpls,
    "SW-VARIABLE-PROTOTYPE-REF": SwVariablePrototypeRef,
    "SW-VARIABLE-IMPL": SwVariableImpl,
    "SW-CLASS-IMPLS": SwClassImpls,
    "SW-CALPRM-PROTOTYPE-REF": SwCalprmPrototypeRef,
    "SW-CALPRM-IMPL": SwCalprmImpl,
    "SW-CLASS-ATTR-IMPL": SwClassAttrImpl,
    "SW-CLASS-PROTOTYPE-REF": SwClassPrototypeRef,
    "SW-CLASS-IMPL": SwClassImpl,
    "SW-FEATURE-EXPORT-CALPRMS": SwFeatureExportCalprms,
    "SW-VARIABLES-WRITE": SwVariablesWrite,
    "SW-VARIABLES-READ-WRITE": SwVariablesReadWrite,
    "SW-VARIABLE-REF-SYSCOND": SwVariableRefSyscond,
    "SW-FEATURE-EXPORT-VARIABLES": SwFeatureExportVariables,
    "SW-FEATURE-IMPORT-VARIABLES": SwFeatureImportVariables,
    "SW-FEATURE-LOCAL-VARIABLES": SwFeatureLocalVariables,
    "SW-FEATURE-MODEL-ONLY-VARIABLES": SwFeatureModelOnlyVariables,
    "SW-FEATURE-VARIABLES": SwFeatureVariables,
    "SW-FEATURE-EXPORT-CLASS-INSTANCES": SwFeatureExportClassInstances,
    "SW-FEATURE-IMPORT-CALPRMS": SwFeatureImportCalprms,
    "SW-CALPRM-REF-SYSCOND": SwCalprmRefSyscond,
    "SW-FEATURE-LOCAL-PARAMS": SwFeatureLocalParams,
    "SW-FEATURE-PARAMS": SwFeatureParams,
    "SW-TEST-DESC": SwTestDesc,
    "SW-FEATURE-IMPORT-CLASS-INSTANCES": SwFeatureImportClassInstances,
    "SW-CLASS-INSTANCE-REF": SwClassInstanceRef,
    "SW-INSTANCE-REF-SYSCOND": SwInstanceRefSyscond,
    "SW-FEATURE-LOCAL-CLASS-INSTANCES": SwFeatureLocalClassInstances,
    "SW-FEATURE-CLASS-INSTANCES": SwFeatureClassInstances,
    "SW-APPLICATION-NOTES": SwApplicationNotes,
    "SW-MAINTENANCE-NOTES": SwMaintenanceNotes,
    "SW-CARB-DOC": SwCarbDoc,
    "SW-CLASS": SwClass,
    "SW-FEATURE-DESIGN-DATA": SwFeatureDesignData,
    "SW-EFFECT-FLOWS": SwEffectFlows,
    "SW-SYSTEMCONST-REFS": SwSystemconstRefs,
    "SW-EFFECT-FLOW": SwEffectFlow,
    "SW-EFFECTING-VARIABLE": SwEffectingVariable,
    "SW-EFFECT": SwEffect,
    "SW-FEATURE-DECOMPOSITION": SwFeatureDecomposition,
    "SW-SYSTEMCONST-REF": SwSystemconstRef,
    "SW-FEATURE": SwFeature,
    "SW-FEATURE-REF": SwFeatureRef,
    "SW-PROCESSES": SwProcesses,
    "SW-SUBCOMPONENT": SwSubcomponent,
    "SW-PROCESS": SwProcess,
    "SW-COMPONENT-SPEC": SwComponentSpec,
    "SW-COLLECTIONS": SwCollections,
    "DISPLAY-NAME": DisplayName,
    "FLAG": Flag,
    "REVISION": Revision,
    "SW-COLLECTION-REF": SwCollectionRef,
    "SW-CS-COLLECTIONS": SwCsCollections,
    "SYMBOLIC-FILE": SymbolicFile,
    "SW-CS-HISTORY": SwCsHistory,
    "CSUS": Csus,
    "SW-CS-STATE": SwCsState,
    "SW-CS-CONTEXT": SwCsContext,
    "SW-CS-PROJECT-INFO": SwCsProjectInfo,
    "SW-CS-TARGET-VARIANT": SwCsTargetVariant,
    "SW-CS-TEST-OBJECT": SwCsTestObject,
    "SW-CS-PROGRAM-IDENTIFIER": SwCsProgramIdentifier,
    "SW-CS-DATA-IDENTIFIER": SwCsDataIdentifier,
    "SW-CS-PERFORMED-BY": SwCsPerformedBy,
    "CSPR": Cspr,
    "SW-CS-FIELD": SwCsField,
    "SW-VCD-CRITERION-VALUES": SwVcdCriterionValues,
    "SW-VCD-CRITERION-VALUE": SwVcdCriterionValue,
    "UNIT-DISPLAY-NAME": UnitDisplayName,
    "SW-VALUE-CONT": SwValueCont,
    "SW-MODEL-LINK": SwModelLink,
    "SW-ARRAY-INDEX": SwArrayIndex,
    "SW-AXIS-CONTS": SwAxisConts,
    "SW-INSTANCE-PROPS-VARIANTS": SwInstancePropsVariants,
    "SW-CS-FLAGS": SwCsFlags,
    "SW-ADDR-INFOS": SwAddrInfos,
    "SW-BASE-ADDR": SwBaseAddr,
    "SW-ADDR-OFFSET": SwAddrOffset,
    "CSDI": Csdi,
    "CSPI": Cspi,
    "CSWP": Cswp,
    "CSTO": Csto,
    "CSTV": Cstv,
    "SW-CS-ENTRY": SwCsEntry,
    "CS-ENTRY": CsEntry,
    "SW-CS-FLAG": SwCsFlag,
    "SW-MC-INSTANCE-INTERFACES": SwMcInstanceInterfaces,
    "SW-SIZEOF-INSTANCE": SwSizeofInstance,
    "SW-ADDR-INFO": SwAddrInfo,
    "SW-INSTANCE": SwInstance,
    "SW-VALUES-CODED-HEX": SwValuesCodedHex,
    "SW-AXIS-CONT": SwAxisCont,
    "SW-VALUES-GENERIC": SwValuesGeneric,
    "SW-INSTANCE-PROPS-VARIANT": SwInstancePropsVariant,
    "SW-MC-INTERFACE-REF": SwMcInterfaceRef,
    "SW-MC-INTERFACE-SOURCE-REF": SwMcInterfaceSourceRef,
    "SW-MC-INTERFACE-AVL-SOURCES": SwMcInterfaceAvlSources,
    "SW-MC-INTERFACE-DEFAULT-SOURCE": SwMcInterfaceDefaultSource,
    "SW-MC-KP-BLOB-CONTS": SwMcKpBlobConts,
    "SW-MC-DP-BLOB-CONTS": SwMcDpBlobConts,
    "SW-MC-PA-BLOB-CONTS": SwMcPaBlobConts,
    "SW-MC-ADDR-MAPPINGS": SwMcAddrMappings,
    "SW-MC-INSTANCE-INTERFACE": SwMcInstanceInterface,
    "SW-MC-ORIGINAL-ADDR": SwMcOriginalAddr,
    "SW-MC-MAPPED-ADDR": SwMcMappedAddr,
    "SW-MC-ADDR-MAPPED-SIZE": SwMcAddrMappedSize,
    "SW-MC-ADDR-MAPPING": SwMcAddrMapping,
    "SW-USER-GROUPS": SwUserGroups,
    "SW-COLLECTION-SPEC": SwCollectionSpec,
    "SW-COLLECTION-RULES": SwCollectionRules,
    "SW-COLLECTION-REFS": SwCollectionRefs,
    "SW-COLLECTION-REGEXPS": SwCollectionRegexps,
    "SW-COLLECTION-WILDCARDS": SwCollectionWildcards,
    "SW-COLLECTION-REGEXP": SwCollectionRegexp,
    "SW-COLLECTION-SCRIPTS": SwCollectionScripts,
    "SW-COLLECTION-WILDCARD": SwCollectionWildcard,
    "SW-COLLECTION-RULE": SwCollectionRule,
    "SW-COLLECTION-SCRIPT": SwCollectionScript,
    "SW-FEATURE-REFS": SwFeatureRefs,
    "SW-CS-COLLECTION": SwCsCollection,
    "SW-UNIT-REFS": SwUnitRefs,
    "SW-CALPRM-REFS": SwCalprmRefs,
    "SW-INSTANCE-REFS": SwInstanceRefs,
    "SW-CLASS-INSTANCE-REFS": SwClassInstanceRefs,
    "SW-COMPU-METHOD-REFS": SwCompuMethodRefs,
    "SW-ADDR-METHOD-REFS": SwAddrMethodRefs,
    "SW-RECORD-LAYOUT-REFS": SwRecordLayoutRefs,
    "SW-CODE-SYNTAX-REFS": SwCodeSyntaxRefs,
    "SW-BASE-TYPE-REFS": SwBaseTypeRefs,
    "SW-DATA-CONSTR-REFS": SwDataConstrRefs,
    "SW-AXIS-TYPE-REFS": SwAxisTypeRefs,
    "SW-COLLECTION-CONT": SwCollectionCont,
    "SW-COLLECTION": SwCollection,
    "SW-CPU-STANDARD-RECORD-LAYOUT": SwCpuStandardRecordLayout,
    "SW-USER-ACCESS-CASES": SwUserAccessCases,
    "SYSTEM-USERS": SystemUsers,
    "SW-USER-GROUP-REFS": SwUserGroupRefs,
    "SYSTEM-USER": SystemUser,
    "SW-USER-GROUP": SwUserGroup,
    "SW-USER-GROUP-REF": SwUserGroupRef,
    "SW-USER-ACCESS-DEFINTIONS": SwUserAccessDefintions,
    "SW-USER-ACCESS-CASE-REFS": SwUserAccessCaseRefs,
    "SW-USER-ACCESS-CASE": SwUserAccessCase,
    "SW-USER-ACCESS-CASE-REF": SwUserAccessCaseRef,
    "SW-USER-RIGHT-SPEC": SwUserRightSpec,
    "SW-ACCESS-DEF": SwAccessDef,
    "SW-CALIBRATION-METHODS": SwCalibrationMethods,
    "SW-CPU-MEM-SEGS": SwCpuMemSegs,
    "SW-CPU-EPK": SwCpuEpk,
    "SW-MEM-PROGRAM-TYPE": SwMemProgramType,
    "SW-MEM-TYPE": SwMemType,
    "SW-MEM-ATTR": SwMemAttr,
    "SW-MEM-BASE-ADDR": SwMemBaseAddr,
    "SW-MEM-SIZE": SwMemSize,
    "SW-MEM-OFFSETS": SwMemOffsets,
    "SW-CPU-MEM-SEG": SwCpuMemSeg,
    "SW-MEM-OFFSET": SwMemOffset,
    "SW-CPU-ADDR-EPK": SwCpuAddrEpk,
    "SW-CPU-TYPE": SwCpuType,
    "SW-CPU-CALIBRATION-OFFSET": SwCpuCalibrationOffset,
    "SW-CPU-NUMBER-OF-INTERFACES": SwCpuNumberOfInterfaces,
    "SW-CPU-SPEC": SwCpuSpec,
    "SW-VCD-CRITERIA": SwVcdCriteria,
    "SW-CALIBRATION-METHOD-SPEC": SwCalibrationMethodSpec,
    "SW-CALIBRATION-METHOD-VERSIONS": SwCalibrationMethodVersions,
    "SW-CALIBRATION-METHOD": SwCalibrationMethod,
    "SW-CALIBRATION-HANDLE": SwCalibrationHandle,
    "SW-CALIBRATION-METHOD-VERSION": SwCalibrationMethodVersion,
    "SW-VCD-SPEC": SwVcdSpec,
    "SW-SYSTEM": SwSystem,
    "SW-VCD-CRITERION-POSSIBLE-VALUES": SwVcdCriterionPossibleValues,
    "SW-VCD-CRITERION": SwVcdCriterion,
    "SW-GLOSSARY": SwGlossary,
    "SW-MC-BASE-TYPES": SwMcBaseTypes,
    "SW-MC-TP-BLOB-LAYOUT": SwMcTpBlobLayout,
    "SW-MC-QP-BLOB-LAYOUT": SwMcQpBlobLayout,
    "SW-MC-KP-BLOB-LAYOUT": SwMcKpBlobLayout,
    "SW-MC-DP-BLOB-LAYOUT": SwMcDpBlobLayout,
    "SW-MC-PA-BLOB-LAYOUT": SwMcPaBlobLayout,
    "SW-MC-BLOB-LAYOUTS": SwMcBlobLayouts,
    "SW-MC-INTERFACE": SwMcInterface,
    "SW-MC-INTERFACE-IMPLS": SwMcInterfaceImpls,
    "SW-MC-BASE-TYPE": SwMcBaseType,
    "SW-MC-COMMUNICATION-SPEC": SwMcCommunicationSpec,
    "SW-MC-BLOB-VALUE": SwMcBlobValue,
    "SW-MC-GENERIC-INTERFACES": SwMcGenericInterfaces,
    "SW-MC-BLOB-ECU-DEPOSIT": SwMcBlobEcuDeposit,
    "SW-MC-TP-BLOB-CONTS": SwMcTpBlobConts,
    "SW-MC-INTERFACE-SOURCES": SwMcInterfaceSources,
    "SW-MC-GENERIC-INTERFACE": SwMcGenericInterface,
    "SW-MC-FRAMES": SwMcFrames,
    "SW-MC-QP-BLOB-CONTS": SwMcQpBlobConts,
    "SW-MC-INTERFACE-SOURCE": SwMcInterfaceSource,
    "SW-MC-INTERFACE-IMPL": SwMcInterfaceImpl,
    "SW-MC-FRAME": SwMcFrame,
    "SPECIAL-DATA": SpecialData,
    "MSR-PROCESSING-LOG": MsrProcessingLog,
    "SDG-CAPTION": SdgCaption,
    "SDG": Sdg,
    "DATA-FILE": DataFile,
    "SW-INSTANCE-TREE-ORIGIN": SwInstanceTreeOrigin,
    "SW-INSTANCE-TREE": SwInstanceTree,
    "SD": Sd,
    "MATCHING-DCIS": MatchingDcis,
    "LOCS": Locs,
    "MATCHING-DCI": MatchingDci,
    "MSRSW": Msrsw,
    "NMLIST": Nmlist,
    "NAMELOC": Nameloc,
}

ROOT_ELEMENT = "MSRSW"

class MSRSWDatabase:
    def __init__(self, filename, debug = False, logLevel = "INFO"):
        if filename == ":memory:":
            self.dbname = ""
        else:
            if not filename.lower().endswith(DB_EXTENSION):
               self.dbname = f"{filename}.{DB_EXTENSION}"
            else:
               self.dbname = filename
        self._engine = create_engine(
            f"sqlite:///{self.dbname}",
            echo = debug,
            connect_args={
                "detect_types": sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES
            },
            native_datetime = True
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

    ATTR = re.compile(r"(\{.*?\})?(.*)", re.DOTALL)

    def __init__(self, file_name: str, db: MSRSWDatabase, root_elem: str = ROOT_ELEMENT):
        self.schema_version = 0
        self.variant = "MSRSW"
        self.file_name = file_name
        self.db = db
        self.msrsw = etree.parse(file_name) # nosec
        self.root = self.msrsw.getroot()
        self.parse(self.root)
        self.db.commit_transaction()
        self.update_metadata()
        self.db.commit_transaction()
        self.db.close()

    def parse(self, tree):
        print(tree, tree.text)
        res = []
        element = ELEMENTS.get(tree.tag)
        obj = element()
        for name, value in tree.attrib.items():
            name = self.get_attr(name)
            # MSRSW noNamespaceSchemaLocation
            if name in obj.ATTRIBUTES:
                name = obj.ATTRIBUTES[name]
                setattr(obj, name, value)
            print("		Attrib:", tree.tag, name, value)
        if element.TERMINAL:
            obj.content = tree.text
        for child in tree.getchildren():
            res.append(self.parse(child))
        if res:
            res = sorted(res, key = lambda c: c.__class__.__name__)
            for key, items in itertools.groupby(res, key = lambda c: c.__class__.__name__):
                items = list(items)
                axx = getattr(obj, obj.ELEMENTS[key])
                if isinstance(axx, InstrumentedList):
                    axx.extend(items)
                else:
                    setattr(obj, obj.ELEMENTS[key], items[0])
        self.db.session.add(obj)
        return obj

    def get_attr(self, name: str) -> str:
        match = self.ATTR.match(name)
        if match:
            return match.group(2)
        return ""

    def update_metadata(self):
        msrsw = self.db.session.query(Msrsw).first()
        print("MSRSW!!!", msrsw)
        meta = self.db.session.query(MetaData).first()
        if msrsw:
            category = msrsw.category.content
            meta.variant = category
        for attr, value in self.root.attrib.items():
            attr = self.get_attr(attr)
            if attr == "noNamespaceSchemaLocation":
                meta.xml_schema = value
