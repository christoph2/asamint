import binascii
import datetime
import itertools
import mmap
import re
import sqlite3
import typing
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sqa
from lxml import etree  # nosec
from sqlalchemy import (
    Column,
    ForeignKey,
    UniqueConstraint,
    create_engine,
    event,
    orm,
    types,
)
from sqlalchemy.engine import Engine
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.orderinglist import ordering_list
from sqlalchemy.orm import (
    Mapped,
    as_declarative,
    backref,
    column_property,
    mapped_column,
    relationship,
)
from sqlalchemy.orm.collections import InstrumentedList

from asamint.utils.xml import create_validator


DB_EXTENSION = ".msrswdb"

CURRENT_SCHEMA_VERSION = 10

CACHE_SIZE = 4  # MB
PAGE_SIZE = mmap.PAGESIZE


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
    # cursor.execute("PRAGMA jornal_mode=WAL")
    cursor.execute("PRAGMA FOREIGN_KEYS=ON")
    cursor.execute(f"PRAGMA PAGE_SIZE={PAGE_SIZE}")
    cursor.execute(f"PRAGMA CACHE_SIZE={calculateCacheSize(CACHE_SIZE * 1024 * 1024)}")
    cursor.execute("PRAGMA SYNCHRONOUS=OFF")  # FULL
    cursor.execute("PRAGMA LOCKING_MODE=EXCLUSIVE")  # NORMAL
    cursor.execute("PRAGMA TEMP_STORE=MEMORY")  # FILE
    cursor.close()


@as_declarative()
class Base:

    rid = Column("rid", types.Integer, primary_key=True)
    content = Column("content", types.Text, nullable=True, unique=False)

    TERMINAL = False
    SELF_REF = False

    def __repr__(self):
        columns = [c.name for c in self.__class__.__table__.c]
        result = []
        for name, value in [(n, getattr(self, n)) for n in columns if not n.startswith("_")]:
            if isinstance(value, str):
                result.append(f"{name} = '{value}'")
            else:
                result.append(f"{name} = {value}")
        return "{}({})".format(self.__class__.__name__, ", ".join(result))


class DatetimeType(types.TypeDecorator):

    FMT = "%Y-%m-%dT%H:%M:%S"
    impl = types.Float
    cache_ok = True

    def process_bind_param(self, value, dialect):  # IN
        return str(Decimal(datetime.datetime.strptime(value, DatetimeType.FMT).timestamp()))

    def process_result_value(self, value, dialect):  # OUT
        return datetime.datetime.fromtimestamp(value).strftime(DatetimeType.FMT)


class DecimalType(types.TypeDecorator):

    impl = types.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # IN
        return str(value)

    def process_result_value(self, value, dialect):  # OUT
        return Decimal(value)


class BlobType(types.TypeDecorator):

    impl = types.BLOB
    cache_ok = True

    def process_bind_param(self, value, dialect):  # IN
        return binascii.a2b_hex(value)

    def process_result_value(self, value, dialect):  # OUT
        return binascii.b2a_hex(value)


def StdFloat(default=0.0):
    return Column(types.Float, default=default, nullable=True)


def StdDecimal(default=0.0):
    return Column(DecimalType, default=default, nullable=True)


def StdDate(default=None):
    # if not default:
    #     default = datetime.datetime.now().strftime(DatetimeType.FMT)
    # return Column(DatetimeType, nullable=True, default=default)
    return Column(types.Text)


def StdBlob():
    return Column(BlobType, nullable=True)


def StdShort(default=0, primary_key=False, unique=False):
    return Column(
        types.Integer,
        default=default,
        nullable=True,
        primary_key=primary_key,
        unique=unique,
        # CheckClause('BETWEEN (-32768, 32767)')
    )


def StdUShort(default=0, primary_key=False, unique=False):
    return Column(
        types.Integer,
        default=default,
        nullable=False,
        primary_key=primary_key,
        unique=unique,
        # CheckClause('BETWEEN (0, 65535)')
    )


def StdLong(default=0, primary_key=False, unique=False):
    return Column(
        types.Integer,
        default=default,
        nullable=False,
        primary_key=primary_key,
        unique=unique,
        # CheckClause('BETWEEN (-2147483648, 2147483647)')
    )


def StdULong(default=0, primary_key=False, unique=False):
    return Column(
        types.Integer,
        default=default,
        nullable=False,
        primary_key=primary_key,
        unique=unique,
        # CheckClause('BETWEEN (0, 4294967295)')
    )


def StdString(default=None, primary_key=False, unique=False, index=False):
    return Column(
        types.Text,
        default=default,
        nullable=True,
        primary_key=primary_key,
        unique=unique,
        index=index,
    )


class MetaData(Base):

    __tablename__ = "metadata"

    """
    """
    schema_version = StdShort()
    variant = StdString()
    xml_schema = StdString()
    created = StdDate()


#
# Assocs.
#


class TtAssociation(Base):

    __tablename__ = "tt_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    tts: Mapped[list["Tt"]] = relationship(back_populates="association")


class HasTts:

    @declared_attr
    def tt_association_id(self):
        return Column(types.Integer, ForeignKey("tt_association.rid"))

    @declared_attr
    def tt_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sTtAssociation" % name,
            (TtAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.tts = association_proxy(
            "tt_association",
            "tts",
            creator=lambda tts: assoc_cls(tts=tts),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Tt(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "tt"  # TTType   --  tt

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tt_association.rid"))
    association = relationship("TtAssociation", back_populates="tts")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("tt.rid"))
    children = relationship("Tt")

    ATTRIBUTES = {
        "TYPE": "_type",
        "USER-DEFINED-TYPE": "user_defined_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    ENUMS = {
        "_type": [
            "SGMLTAG",
            "SGML-ATTRIBUTE",
            "TOOL",
            "PRODUCT",
            "VARIABLE",
            "STATE",
            "PRM",
            "MATERIAL",
            "CONTROL-ELEMENT",
            "CODE",
            "ORGANISATION",
            "OTHER",
        ],
    }
    TERMINAL = True

    _type = StdString()
    user_defined_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class EAssociation(Base):

    __tablename__ = "e_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    es: Mapped[list["E"]] = relationship(back_populates="association")


class HasEs:

    @declared_attr
    def e_association_id(self):
        return Column(types.Integer, ForeignKey("e_association.rid"))

    @declared_attr
    def e_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sEAssociation" % name,
            (EAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.es = association_proxy(
            "e_association",
            "es",
            creator=lambda es: assoc_cls(es=es),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class E(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "e"  # EType   --  e

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("e_association.rid"))
    association = relationship("EAssociation", back_populates="es")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("e.rid"))
    children = relationship("E")

    ATTRIBUTES = {
        "TYPE": "_type",
        "COLOR": "color",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    ENUMS = {
        "_type": ["BOLD", "ITALIC", "BOLDITALIC", "PLAIN"],
    }
    TERMINAL = True

    _type = StdString()
    color = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SupAssociation(Base):

    __tablename__ = "sup_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sups: Mapped[list["Sup"]] = relationship(back_populates="association")


class HasSups:

    @declared_attr
    def sup_association_id(self):
        return Column(types.Integer, ForeignKey("sup_association.rid"))

    @declared_attr
    def sup_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSupAssociation" % name,
            (SupAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sups = association_proxy(
            "sup_association",
            "sups",
            creator=lambda sups: assoc_cls(sups=sups),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Sup(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sup"  # SUPType   --  sup

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sup_association.rid"))
    association = relationship("SupAssociation", back_populates="sups")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sup.rid"))
    children = relationship("Sup")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SubAssociation(Base):

    __tablename__ = "sub_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    subs: Mapped[list["Sub"]] = relationship(back_populates="association")


class HasSubs:

    @declared_attr
    def sub_association_id(self):
        return Column(types.Integer, ForeignKey("sub_association.rid"))

    @declared_attr
    def sub_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSubAssociation" % name,
            (SubAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.subs = association_proxy(
            "sub_association",
            "subs",
            creator=lambda subs: assoc_cls(subs=subs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Sub(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sub"  # SUBType   --  sub

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sub_association.rid"))
    association = relationship("SubAssociation", back_populates="subs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sub.rid"))
    children = relationship("Sub")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class IeAssociation(Base):

    __tablename__ = "ie_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    ies: Mapped[list["Ie"]] = relationship(back_populates="association")


class HasIes:

    @declared_attr
    def ie_association_id(self):
        return Column(types.Integer, ForeignKey("ie_association.rid"))

    @declared_attr
    def ie_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sIeAssociation" % name,
            (IeAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.ies = association_proxy(
            "ie_association",
            "ies",
            creator=lambda ies: assoc_cls(ies=ies),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Ie(Base, HasSups, HasSubs):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "ie"  # IEType   --  ie

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ie_association.rid"))
    association = relationship("IeAssociation", back_populates="ies")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("ie.rid"))
    children = relationship("Ie")

    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }

    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-A
    # NO_PA         sup
    # SHIT-A
    # NO_PA         sub


class XrefAssociation(Base):

    __tablename__ = "xref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    xrefs: Mapped[list["Xref"]] = relationship(back_populates="association")


class HasXrefs:

    @declared_attr
    def xref_association_id(self):
        return Column(types.Integer, ForeignKey("xref_association.rid"))

    @declared_attr
    def xref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sXrefAssociation" % name,
            (XrefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.xrefs = association_proxy(
            "xref_association",
            "xrefs",
            creator=lambda xrefs: assoc_cls(xrefs=xrefs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Xref(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "xref"  # XREFType   --  xref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("xref_association.rid"))
    association = relationship("XrefAssociation", back_populates="xrefs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("xref.rid"))
    children = relationship("Xref")

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
    ELEMENTS = {}
    ENUMS = {
        "id_class": [
            "CHAPTER",
            "COMPANY",
            "DEF-ITEM",
            "EXTERNAL",
            "FIGURE",
            "FORMULA",
            "PRM",
            "REQUIREMENT",
            "SAMPLE",
            "SDG",
            "STD",
            "SW-ADDR-METHOD",
            "SW-AXIS-TYPE",
            "SW-BASE-TYPE",
            "SW-CALPRM",
            "SW-CALPRM-PROTOTYPE",
            "SW-CLASS-PROTOTYPE",
            "SW-CLASS-ATTR-IMPL",
            "SW-CLASS-INSTANCE",
            "SW-CLASS",
            "SW-CODE-SYNTAX",
            "SW-COLLECTION",
            "SW-COMPU-METHOD",
            "SW-CPU-MEM-SEG",
            "SW-DATA-CONSTR",
            "SW-FEATURE",
            "SW-GENERIC-AXIS-PARAM-TYPE",
            "SW-INSTANCE-TREE",
            "SW-INSTANCE",
            "SW-MC-BASE-TYPE",
            "SW-MC-INTERFACE-SOURCE",
            "SW-MC-INTERFACE",
            "SW-RECORD-LAYOUT",
            "SW-SYSTEMCONST",
            "SW-SYSTEM",
            "SW-TASK",
            "SW-TEMPLATE",
            "SW-UNIT",
            "SW-USER-ACCESS-CASE",
            "SW-USER-GROUP",
            "SW-VARIABLE-PROTOTYPE",
            "SW-VARIABLE",
            "SW-VCD-CRITERION",
            "TABLE",
            "TEAM-MEMBER",
            "TOPIC",
            "VARIANT-DEF",
            "VARIANT-CHAR",
            "XDOC",
            "XFILE",
            "XREF-TARGET",
        ],
        "show_see": ["SHOW-SEE", "NO-SHOW-SEE"],
        "show_content": ["SHOW-CONTENT", "NO-SHOW-CONTENT"],
        "show_resource_type": ["SHOW-TYPE", "NO-SHOW-TYPE"],
        "show_resource_number": ["SHOW-NUMBER", "NO-SHOW-NUMBER"],
        "show_resource_long_name": ["SHOW-LONG-NAME", "NO-SHOW-LONG-NAME"],
        "show_resource_short_name": ["SHOW-SHORT-NAME", "NO-SHOW-SHORT-NAME"],
        "show_resource_page": ["SHOW-PAGE", "NO-SHOW-PAGE"],
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


class StdAssociation(Base):

    __tablename__ = "std_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    stds: Mapped[list["Std"]] = relationship(back_populates="association")


class HasStds:

    @declared_attr
    def std_association_id(self):
        return Column(types.Integer, ForeignKey("std_association.rid"))

    @declared_attr
    def std_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sStdAssociation" % name,
            (StdAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.stds = association_proxy(
            "std_association",
            "stds",
            creator=lambda stds: assoc_cls(stds=stds),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Std(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "std"  # STDType   --  std

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("std_association.rid"))
    association = relationship("StdAssociation", back_populates="stds")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("std.rid"))
    children = relationship("Std")

    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": ("long_name_1", "R"),
        "ShortName": ("short_name", "R"),
        "Subtitle": ("subtitle", "R"),
        "State1": ("state_1", "R"),
        "Date1": ("date_1", "R"),
        "Url": ("url", "R"),
        "Position": ("position", "R"),
    }

    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name_1.rid"))
    long_name_1: Mapped["LongName1"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    subtitle_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("subtitle.rid"))
    subtitle: Mapped["Subtitle"] = relationship(single_parent=True)
    # SHIT-R
    state_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("state_1.rid"))
    state_1: Mapped["State1"] = relationship(single_parent=True)
    # SHIT-R
    date_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date_1.rid"))
    date_1: Mapped["Date1"] = relationship(single_parent=True)
    # SHIT-R
    url_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("url.rid"))
    url: Mapped["Url"] = relationship(single_parent=True)
    # SHIT-R
    position_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("position.rid"))
    position: Mapped["Position"] = relationship(single_parent=True)


class FtAssociation(Base):

    __tablename__ = "ft_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    fts: Mapped[list["Ft"]] = relationship(back_populates="association")


class HasFts:

    @declared_attr
    def ft_association_id(self):
        return Column(types.Integer, ForeignKey("ft_association.rid"))

    @declared_attr
    def ft_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sFtAssociation" % name,
            (FtAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.fts = association_proxy(
            "ft_association",
            "fts",
            creator=lambda fts: assoc_cls(fts=fts),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Ft(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "ft"  # FTType   --  ft

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ft_association.rid"))
    association = relationship("FtAssociation", back_populates="fts")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("ft.rid"))
    children = relationship("Ft")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class MsrQueryTextAssociation(Base):

    __tablename__ = "msr_query_text_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    msr_query_texts: Mapped[list["MsrQueryText"]] = relationship(back_populates="association")


class HasMsrQueryTexts:

    @declared_attr
    def msr_query_text_association_id(self):
        return Column(types.Integer, ForeignKey("msr_query_text_association.rid"))

    @declared_attr
    def msr_query_text_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sMsrQueryTextAssociation" % name,
            (MsrQueryTextAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.msr_query_texts = association_proxy(
            "msr_query_text_association",
            "msr_query_texts",
            creator=lambda msr_query_texts: assoc_cls(msr_query_texts=msr_query_texts),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class MsrQueryText(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_text"  # MSR-QUERY-TEXTType   --  msr_query_text

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_text_association.rid"))
    association = relationship("MsrQueryTextAssociation", back_populates="msr_query_texts")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("msr_query_text.rid"))
    children = relationship("MsrQueryText")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": ("msr_query_props", "R"),
        "MsrQueryResultText": ("msr_query_result_text", "R"),
    }

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(single_parent=True)
    # SHIT-R
    msr_query_result_text_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_result_text.rid"))
    msr_query_result_text: Mapped["MsrQueryResultText"] = relationship(single_parent=True)


class XfileAssociation(Base):

    __tablename__ = "xfile_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    xfiles: Mapped[list["Xfile"]] = relationship(back_populates="association")


class HasXfiles:

    @declared_attr
    def xfile_association_id(self):
        return Column(types.Integer, ForeignKey("xfile_association.rid"))

    @declared_attr
    def xfile_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sXfileAssociation" % name,
            (XfileAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.xfiles = association_proxy(
            "xfile_association",
            "xfiles",
            creator=lambda xfiles: assoc_cls(xfiles=xfiles),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Xfile(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "xfile"  # XFILEType   --  xfile

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("xfile_association.rid"))
    association = relationship("XfileAssociation", back_populates="xfiles")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("xfile.rid"))
    children = relationship("Xfile")

    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": ("long_name_1", "R"),
        "ShortName": ("short_name", "R"),
        "Url": ("url", "R"),
        "Notation": ("notation", "R"),
        "Tool": ("tool", "R"),
        "ToolVersion": ("tool_version", "R"),
    }

    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name_1.rid"))
    long_name_1: Mapped["LongName1"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    url_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("url.rid"))
    url: Mapped["Url"] = relationship(single_parent=True)
    # SHIT-R
    notation_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("notation.rid"))
    notation: Mapped["Notation"] = relationship(single_parent=True)
    # SHIT-R
    tool_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tool.rid"))
    tool: Mapped["Tool"] = relationship(single_parent=True)
    # SHIT-R
    tool_version_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tool_version.rid"))
    tool_version: Mapped["ToolVersion"] = relationship(single_parent=True)


class XdocAssociation(Base):

    __tablename__ = "xdoc_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    xdocs: Mapped[list["Xdoc"]] = relationship(back_populates="association")


class HasXdocs:

    @declared_attr
    def xdoc_association_id(self):
        return Column(types.Integer, ForeignKey("xdoc_association.rid"))

    @declared_attr
    def xdoc_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sXdocAssociation" % name,
            (XdocAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.xdocs = association_proxy(
            "xdoc_association",
            "xdocs",
            creator=lambda xdocs: assoc_cls(xdocs=xdocs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Xdoc(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "xdoc"  # XDOCType   --  xdoc

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("xdoc_association.rid"))
    association = relationship("XdocAssociation", back_populates="xdocs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("xdoc.rid"))
    children = relationship("Xdoc")

    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": ("long_name_1", "R"),
        "ShortName": ("short_name", "R"),
        "Number": ("number", "R"),
        "State1": ("state_1", "R"),
        "Date1": ("date_1", "R"),
        "Publisher": ("publisher", "R"),
        "Url": ("url", "R"),
        "Position": ("position", "R"),
    }

    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name_1.rid"))
    long_name_1: Mapped["LongName1"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    number_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("number.rid"))
    number: Mapped["Number"] = relationship(single_parent=True)
    # SHIT-R
    state_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("state_1.rid"))
    state_1: Mapped["State1"] = relationship(single_parent=True)
    # SHIT-R
    date_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date_1.rid"))
    date_1: Mapped["Date1"] = relationship(single_parent=True)
    # SHIT-R
    publisher_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("publisher.rid"))
    publisher: Mapped["Publisher"] = relationship(single_parent=True)
    # SHIT-R
    url_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("url.rid"))
    url: Mapped["Url"] = relationship(single_parent=True)
    # SHIT-R
    position_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("position.rid"))
    position: Mapped["Position"] = relationship(single_parent=True)


class XrefTargetAssociation(Base):

    __tablename__ = "xref_target_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    xref_targets: Mapped[list["XrefTarget"]] = relationship(back_populates="association")


class HasXrefTargets:

    @declared_attr
    def xref_target_association_id(self):
        return Column(types.Integer, ForeignKey("xref_target_association.rid"))

    @declared_attr
    def xref_target_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sXrefTargetAssociation" % name,
            (XrefTargetAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.xref_targets = association_proxy(
            "xref_target_association",
            "xref_targets",
            creator=lambda xref_targets: assoc_cls(xref_targets=xref_targets),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class XrefTarget(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "xref_target"  # XREF-TARGETType   --  xref_target

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("xref_target_association.rid"))
    association = relationship("XrefTargetAssociation", back_populates="xref_targets")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("xref_target.rid"))
    children = relationship("XrefTarget")

    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName1": ("long_name_1", "R"),
        "ShortName": ("short_name", "R"),
    }

    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name_1.rid"))
    long_name_1: Mapped["LongName1"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)


class PAssociation(Base):

    __tablename__ = "p_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    ps: Mapped[list["P"]] = relationship(back_populates="association")


class HasPs:

    @declared_attr
    def p_association_id(self):
        return Column(types.Integer, ForeignKey("p_association.rid"))

    @declared_attr
    def p_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sPAssociation" % name,
            (PAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.ps = association_proxy(
            "p_association",
            "ps",
            creator=lambda ps: assoc_cls(ps=ps),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class P(
    Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts, HasStds, HasXdocs, HasXfiles
):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "p"  # PType   --  p

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("p_association.rid"))
    association = relationship("PAssociation", back_populates="ps")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("p.rid"))
    children = relationship("P")

    ATTRIBUTES = {
        "HELP-ENTRY": "help_entry",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "Std": ("stds", "A"),
        "Xdoc": ("xdocs", "A"),
        "Xfile": ("xfiles", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }
    TERMINAL = True

    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-A
    # NO_PA         tt
    # SHIT-A
    # NO_PA         xref
    # SHIT-A
    # NO_PA         xref_target
    # SHIT-A
    # NO_PA         e
    # SHIT-A
    # NO_PA         ft
    # SHIT-A
    # NO_PA         sup
    # SHIT-A
    # NO_PA         sub
    # SHIT-A
    # NO_PA         ie
    # SHIT-A
    # NO_PA         std
    # SHIT-A
    # NO_PA         xdoc
    # SHIT-A
    # NO_PA         xfile
    # SHIT-A
    # NO_PA         msr_query_text


class VerbatimAssociation(Base):

    __tablename__ = "verbatim_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    verbatims: Mapped[list["Verbatim"]] = relationship(back_populates="association")


class HasVerbatims:

    @declared_attr
    def verbatim_association_id(self):
        return Column(types.Integer, ForeignKey("verbatim_association.rid"))

    @declared_attr
    def verbatim_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sVerbatimAssociation" % name,
            (VerbatimAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.verbatims = association_proxy(
            "verbatim_association",
            "verbatims",
            creator=lambda verbatims: assoc_cls(verbatims=verbatims),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Verbatim(Base, HasEs):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "verbatim"  # VERBATIMType   --  verbatim

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("verbatim_association.rid"))
    association = relationship("VerbatimAssociation", back_populates="verbatims")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("verbatim.rid"))
    children = relationship("Verbatim")

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
        "E": ("es", "A"),
    }
    ENUMS = {
        "_float": ["FLOAT", "NO-FLOAT"],
        "pgwide": ["PGWIDE", "NO-PGWIDE"],
        "keep_with_previous": ["KEEP", "NO-KEEP"],
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
    # SHIT-A
    # NO_PA         e


class FigureAssociation(Base):

    __tablename__ = "figure_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    figures: Mapped[list["Figure"]] = relationship(back_populates="association")


class HasFigures:

    @declared_attr
    def figure_association_id(self):
        return Column(types.Integer, ForeignKey("figure_association.rid"))

    @declared_attr
    def figure_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sFigureAssociation" % name,
            (FigureAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.figures = association_proxy(
            "figure_association",
            "figures",
            creator=lambda figures: assoc_cls(figures=figures),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Figure(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "figure"  # FIGUREType   --  figure

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("figure_association.rid"))
    association = relationship("FigureAssociation", back_populates="figures")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("figure.rid"))
    children = relationship("Figure")

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
        "FigureCaption": ("figure_caption", "R"),
        "Graphic": ("graphic", "R"),
        "Map": ("_map", "R"),
        "Verbatim": ("verbatim", "R"),
        "Desc": ("_desc", "R"),
    }
    ENUMS = {
        "_float": ["FLOAT", "NO-FLOAT"],
        "pgwide": ["PGWIDE", "NO-PGWIDE"],
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    _float = StdString()
    help_entry = StdString()
    pgwide = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    figure_caption_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("figure_caption.rid"))
    figure_caption: Mapped["FigureCaption"] = relationship(single_parent=True)
    # SHIT-R
    graphic_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("graphic.rid"))
    graphic: Mapped["Graphic"] = relationship(single_parent=True)
    # SHIT-R
    map_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_map.rid"))
    _map: Mapped["Map"] = relationship(single_parent=True)
    # SHIT-R
    verbatim_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("verbatim.rid"))
    verbatim: Mapped["Verbatim"] = relationship(single_parent=True)
    # SHIT-R
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)


class NoteAssociation(Base):

    __tablename__ = "note_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    notes: Mapped[list["Note"]] = relationship(back_populates="association")


class HasNotes:

    @declared_attr
    def note_association_id(self):
        return Column(types.Integer, ForeignKey("note_association.rid"))

    @declared_attr
    def note_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sNoteAssociation" % name,
            (NoteAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.notes = association_proxy(
            "note_association",
            "notes",
            creator=lambda notes: assoc_cls(notes=notes),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Note(Base, HasPs):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "note"  # NOTEType   --  note

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("note_association.rid"))
    association = relationship("NoteAssociation", back_populates="notes")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("note.rid"))
    children = relationship("Note")

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
        "Label": ("label", "R"),
        "P": ("ps", "A"),
    }
    ENUMS = {
        "note_type": ["CAUTION", "HINT", "TIP", "INSTRUCTION", "EXERCISE", "OTHER"],
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    note_type = StdString()
    user_defined_type = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         p


class ListAssociation(Base):

    __tablename__ = "_list_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    _lists: Mapped[list["List"]] = relationship(back_populates="association")


class HasLists:

    @declared_attr
    def list_association_id(self):
        return Column(types.Integer, ForeignKey("_list_association.rid"))

    @declared_attr
    def _list_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sListAssociation" % name,
            (ListAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls._lists = association_proxy(
            "_list_association",
            "_lists",
            creator=lambda _lists: assoc_cls(_lists=_lists),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class List(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: ['Item']
    __tablename__ = "_list"  # LISTType   --  _list

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_list_association.rid"))
    association = relationship("ListAssociation", back_populates="_lists")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("_list.rid"))
    children = relationship("List")

    ATTRIBUTES = {
        "TYPE": "_type",
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Item": ("item", "A"),
    }
    ENUMS = {
        "_type": ["UNNUMBER", "NUMBER"],
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    _type = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-A
    # PARENT-OBJ
    item: Mapped[list["Item"]] = relationship(back_populates="_list")


class DefListAssociation(Base):

    __tablename__ = "def_list_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    def_lists: Mapped[list["DefList"]] = relationship(back_populates="association")


class HasDefLists:

    @declared_attr
    def def_list_association_id(self):
        return Column(types.Integer, ForeignKey("def_list_association.rid"))

    @declared_attr
    def def_list_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sDefListAssociation" % name,
            (DefListAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.def_lists = association_proxy(
            "def_list_association",
            "def_lists",
            creator=lambda def_lists: assoc_cls(def_lists=def_lists),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class DefList(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: ['DefItem']
    __tablename__ = "def_list"  # DEF-LISTType   --  def_list

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("def_list_association.rid"))
    association = relationship("DefListAssociation", back_populates="def_lists")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("def_list.rid"))
    children = relationship("DefList")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "DefItem": ("def_item", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-A
    # PARENT-OBJ
    def_item: Mapped[list["DefItem"]] = relationship(back_populates="def_list")


class LabeledListAssociation(Base):

    __tablename__ = "labeled_list_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    labeled_lists: Mapped[list["LabeledList"]] = relationship(back_populates="association")


class HasLabeledLists:

    @declared_attr
    def labeled_list_association_id(self):
        return Column(types.Integer, ForeignKey("labeled_list_association.rid"))

    @declared_attr
    def labeled_list_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sLabeledListAssociation" % name,
            (LabeledListAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.labeled_lists = association_proxy(
            "labeled_list_association",
            "labeled_lists",
            creator=lambda labeled_lists: assoc_cls(labeled_lists=labeled_lists),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class LabeledList(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: ['LabeledItem']
    __tablename__ = "labeled_list"  # LABELED-LISTType   --  labeled_list

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("labeled_list_association.rid"))
    association = relationship("LabeledListAssociation", back_populates="labeled_lists")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("labeled_list.rid"))
    children = relationship("LabeledList")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "IndentSample": ("indent_sample", "R"),
        "LabeledItem": ("labeled_item", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    indent_sample_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("indent_sample.rid"))
    indent_sample: Mapped["IndentSample"] = relationship(single_parent=True)
    # SHIT-A
    # PARENT-OBJ
    labeled_item: Mapped[list["LabeledItem"]] = relationship(back_populates="labeled_list")


class MsrQueryChapterAssociation(Base):

    __tablename__ = "msr_query_chapter_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    msr_query_chapters: Mapped[list["MsrQueryChapter"]] = relationship(back_populates="association")


class HasMsrQueryChapters:

    @declared_attr
    def msr_query_chapter_association_id(self):
        return Column(types.Integer, ForeignKey("msr_query_chapter_association.rid"))

    @declared_attr
    def msr_query_chapter_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sMsrQueryChapterAssociation" % name,
            (MsrQueryChapterAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.msr_query_chapters = association_proxy(
            "msr_query_chapter_association",
            "msr_query_chapters",
            creator=lambda msr_query_chapters: assoc_cls(msr_query_chapters=msr_query_chapters),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class MsrQueryChapter(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_chapter"  # MSR-QUERY-CHAPTERType   --  msr_query_chapter

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_chapter_association.rid"))
    association = relationship("MsrQueryChapterAssociation", back_populates="msr_query_chapters")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("msr_query_chapter.rid"))
    children = relationship("MsrQueryChapter")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": ("msr_query_props", "R"),
        "MsrQueryResultChapter": ("msr_query_result_chapter", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(single_parent=True)
    # SHIT-R
    msr_query_result_chapter_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_result_chapter.rid"))
    msr_query_result_chapter: Mapped["MsrQueryResultChapter"] = relationship(single_parent=True)


class FormulaAssociation(Base):

    __tablename__ = "formula_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    formulas: Mapped[list["Formula"]] = relationship(back_populates="association")


class HasFormulas:

    @declared_attr
    def formula_association_id(self):
        return Column(types.Integer, ForeignKey("formula_association.rid"))

    @declared_attr
    def formula_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sFormulaAssociation" % name,
            (FormulaAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.formulas = association_proxy(
            "formula_association",
            "formulas",
            creator=lambda formulas: assoc_cls(formulas=formulas),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Formula(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "formula"  # FORMULAType   --  formula

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("formula_association.rid"))
    association = relationship("FormulaAssociation", back_populates="formulas")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("formula.rid"))
    children = relationship("Formula")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FormulaCaption": ("formula_caption", "R"),
        "Graphic": ("graphic", "R"),
        "Map": ("_map", "R"),
        "Verbatim": ("verbatim", "R"),
        "TexMath": ("tex_math", "R"),
        "CCode": ("c_code", "R"),
        "GenericMath": ("generic_math", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    formula_caption_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("formula_caption.rid"))
    formula_caption: Mapped["FormulaCaption"] = relationship(single_parent=True)
    # SHIT-R
    graphic_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("graphic.rid"))
    graphic: Mapped["Graphic"] = relationship(single_parent=True)
    # SHIT-R
    map_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_map.rid"))
    _map: Mapped["Map"] = relationship(single_parent=True)
    # SHIT-R
    verbatim_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("verbatim.rid"))
    verbatim: Mapped["Verbatim"] = relationship(single_parent=True)
    # SHIT-R
    tex_math_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tex_math.rid"))
    tex_math: Mapped["TexMath"] = relationship(single_parent=True)
    # SHIT-R
    c_code_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("c_code.rid"))
    c_code: Mapped["CCode"] = relationship(single_parent=True)
    # SHIT-R
    generic_math_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("generic_math.rid"))
    generic_math: Mapped["GenericMath"] = relationship(single_parent=True)


class MsrQueryP2Association(Base):

    __tablename__ = "msr_query_p_2_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    msr_query_p_2s: Mapped[list["MsrQueryP2"]] = relationship(back_populates="association")


class HasMsrQueryP2s:

    @declared_attr
    def msr_query_p_2_association_id(self):
        return Column(types.Integer, ForeignKey("msr_query_p_2_association.rid"))

    @declared_attr
    def msr_query_p_2_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sMsrQueryP2Association" % name,
            (MsrQueryP2Association,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.msr_query_p_2s = association_proxy(
            "msr_query_p_2_association",
            "msr_query_p_2s",
            creator=lambda msr_query_p_2s: assoc_cls(msr_query_p_2s=msr_query_p_2s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class MsrQueryP2(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_p_2"  # MSR-QUERY-P-2Type   --  msr_query_p_2

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_p_2_association.rid"))
    association = relationship("MsrQueryP2Association", back_populates="msr_query_p_2s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("msr_query_p_2.rid"))
    children = relationship("MsrQueryP2")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": ("msr_query_props", "R"),
        "MsrQueryResultP2": ("msr_query_result_p_2", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(single_parent=True)
    # SHIT-R
    msr_query_result_p_2_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_result_p_2.rid"))
    msr_query_result_p_2: Mapped["MsrQueryResultP2"] = relationship(single_parent=True)


class TableAssociation(Base):

    __tablename__ = "table_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    tables: Mapped[list["Table"]] = relationship(back_populates="association")


class HasTables:

    @declared_attr
    def table_association_id(self):
        return Column(types.Integer, ForeignKey("table_association.rid"))

    @declared_attr
    def table_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sTableAssociation" % name,
            (TableAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.tables = association_proxy(
            "table_association",
            "tables",
            creator=lambda tables: assoc_cls(tables=tables),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Table(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: ['Tgroup']
    __tablename__ = "table"  # TABLEType   --  table

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("table_association.rid"))
    association = relationship("TableAssociation", back_populates="tables")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("table.rid"))
    children = relationship("Table")

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
        "TableCaption": ("table_caption", "R"),
        "Tgroup": ("tgroup", "A"),
    }
    ENUMS = {
        "frame": ["TOP", "BOTTOM", "TOPBOT", "ALL", "SIDES", "NONE"],
        "orient": ["PORT", "LAND"],
        "_float": ["FLOAT", "NO-FLOAT"],
        "keep_with_previous": ["KEEP", "NO-KEEP"],
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
    # SHIT-R
    table_caption_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("table_caption.rid"))
    table_caption: Mapped["TableCaption"] = relationship(single_parent=True)
    # SHIT-A
    # PARENT-OBJ
    tgroup: Mapped[list["Tgroup"]] = relationship(back_populates="table")


class MsrQueryTopic2Association(Base):

    __tablename__ = "msr_query_topic_2_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    msr_query_topic_2s: Mapped[list["MsrQueryTopic2"]] = relationship(back_populates="association")


class HasMsrQueryTopic2s:

    @declared_attr
    def msr_query_topic_2_association_id(self):
        return Column(types.Integer, ForeignKey("msr_query_topic_2_association.rid"))

    @declared_attr
    def msr_query_topic_2_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sMsrQueryTopic2Association" % name,
            (MsrQueryTopic2Association,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.msr_query_topic_2s = association_proxy(
            "msr_query_topic_2_association",
            "msr_query_topic_2s",
            creator=lambda msr_query_topic_2s: assoc_cls(msr_query_topic_2s=msr_query_topic_2s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class MsrQueryTopic2(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_topic_2"  # MSR-QUERY-TOPIC-2Type   --  msr_query_topic_2

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_topic_2_association.rid"))
    association = relationship("MsrQueryTopic2Association", back_populates="msr_query_topic_2s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("msr_query_topic_2.rid"))
    children = relationship("MsrQueryTopic2")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": ("msr_query_props", "R"),
        "MsrQueryResultTopic2": ("msr_query_result_topic_2", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(single_parent=True)
    # SHIT-R
    msr_query_result_topic_2_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_result_topic_2.rid"))
    msr_query_result_topic_2: Mapped["MsrQueryResultTopic2"] = relationship(single_parent=True)


class PrmCharAssociation(Base):

    __tablename__ = "prm_char_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    prm_chars: Mapped[list["PrmChar"]] = relationship(back_populates="association")


class HasPrmChars:

    @declared_attr
    def prm_char_association_id(self):
        return Column(types.Integer, ForeignKey("prm_char_association.rid"))

    @declared_attr
    def prm_char_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sPrmCharAssociation" % name,
            (PrmCharAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.prm_chars = association_proxy(
            "prm_char_association",
            "prm_chars",
            creator=lambda prm_chars: assoc_cls(prm_chars=prm_chars),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class PrmChar(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "prm_char"  # PRM-CHARType   --  prm_char

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("prm_char_association.rid"))
    association = relationship("PrmCharAssociation", back_populates="prm_chars")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("prm_char.rid"))
    children = relationship("PrmChar")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Cond": ("cond", "R"),
        "Abs": ("_abs", "R"),
        "Tol": ("tol", "R"),
        "Min": ("_min", "R"),
        "Typ": ("typ", "R"),
        "Max": ("_max", "R"),
        "Unit": ("unit", "R"),
        "Text": ("text", "R"),
        "Remark": ("remark", "R"),
    }

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    cond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cond.rid"))
    cond: Mapped["Cond"] = relationship(single_parent=True)
    # SHIT-R
    abs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_abs.rid"))
    _abs: Mapped["Abs"] = relationship(single_parent=True)
    # SHIT-R
    tol_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tol.rid"))
    tol: Mapped["Tol"] = relationship(single_parent=True)
    # SHIT-R
    min_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_min.rid"))
    _min: Mapped["Min"] = relationship(single_parent=True)
    # SHIT-R
    typ_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("typ.rid"))
    typ: Mapped["Typ"] = relationship(single_parent=True)
    # SHIT-R
    max_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_max.rid"))
    _max: Mapped["Max"] = relationship(single_parent=True)
    # SHIT-R
    unit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("unit.rid"))
    unit: Mapped["Unit"] = relationship(single_parent=True)
    # SHIT-R
    text_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("text.rid"))
    text: Mapped["Text"] = relationship(single_parent=True)
    # SHIT-R
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)


class PrmAssociation(Base):

    __tablename__ = "prm_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    prms: Mapped[list["Prm"]] = relationship(back_populates="association")


class HasPrms:

    @declared_attr
    def prm_association_id(self):
        return Column(types.Integer, ForeignKey("prm_association.rid"))

    @declared_attr
    def prm_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sPrmAssociation" % name,
            (PrmAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.prms = association_proxy(
            "prm_association",
            "prms",
            creator=lambda prms: assoc_cls(prms=prms),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Prm(Base, HasPrmChars):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "prm"  # PRMType   --  prm

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("prm_association.rid"))
    association = relationship("PrmAssociation", back_populates="prms")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("prm.rid"))
    children = relationship("Prm")

    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "PrmChar": ("prm_chars", "A"),
    }

    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         prm_char


class PrmsAssociation(Base):

    __tablename__ = "prms_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    prmss: Mapped[list["Prms"]] = relationship(back_populates="association")


class HasPrmss:

    @declared_attr
    def prms_association_id(self):
        return Column(types.Integer, ForeignKey("prms_association.rid"))

    @declared_attr
    def prms_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sPrmsAssociation" % name,
            (PrmsAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.prmss = association_proxy(
            "prms_association",
            "prmss",
            creator=lambda prmss: assoc_cls(prmss=prmss),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Prms(Base, HasPrms):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "prms"  # PRMSType   --  prms

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("prms_association.rid"))
    association = relationship("PrmsAssociation", back_populates="prmss")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("prms.rid"))
    children = relationship("Prms")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "Prm": ("prms", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         prm


class MsrQueryP1Association(Base):

    __tablename__ = "msr_query_p_1_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    msr_query_p_1s: Mapped[list["MsrQueryP1"]] = relationship(back_populates="association")


class HasMsrQueryP1s:

    @declared_attr
    def msr_query_p_1_association_id(self):
        return Column(types.Integer, ForeignKey("msr_query_p_1_association.rid"))

    @declared_attr
    def msr_query_p_1_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sMsrQueryP1Association" % name,
            (MsrQueryP1Association,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.msr_query_p_1s = association_proxy(
            "msr_query_p_1_association",
            "msr_query_p_1s",
            creator=lambda msr_query_p_1s: assoc_cls(msr_query_p_1s=msr_query_p_1s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class MsrQueryP1(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_p_1"  # MSR-QUERY-P-1Type   --  msr_query_p_1

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_p_1_association.rid"))
    association = relationship("MsrQueryP1Association", back_populates="msr_query_p_1s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("msr_query_p_1.rid"))
    children = relationship("MsrQueryP1")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": ("msr_query_props", "R"),
        "MsrQueryResultP1": ("msr_query_result_p_1", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(single_parent=True)
    # SHIT-R
    msr_query_result_p_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_result_p_1.rid"))
    msr_query_result_p_1: Mapped["MsrQueryResultP1"] = relationship(single_parent=True)


class Topic1Association(Base):

    __tablename__ = "topic_1_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    topic_1s: Mapped[list["Topic1"]] = relationship(back_populates="association")


class HasTopic1s:

    @declared_attr
    def topic_1_association_id(self):
        return Column(types.Integer, ForeignKey("topic_1_association.rid"))

    @declared_attr
    def topic_1_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sTopic1Association" % name,
            (Topic1Association,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.topic_1s = association_proxy(
            "topic_1_association",
            "topic_1s",
            creator=lambda topic_1s: assoc_cls(topic_1s=topic_1s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Topic1(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "topic_1"  # TOPIC-1Type   --  topic_1

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("topic_1_association.rid"))
    association = relationship("Topic1Association", back_populates="topic_1s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("topic_1.rid"))
    children = relationship("Topic1")

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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         p
    # SHIT-A
    # NO_PA         verbatim
    # SHIT-A
    # NO_PA         figure
    # SHIT-A
    # NO_PA         formula
    # SHIT-A
    # NO_PA         _list
    # SHIT-A
    # NO_PA         def_list
    # SHIT-A
    # NO_PA         labeled_list
    # SHIT-A
    # NO_PA         note
    # SHIT-A
    # NO_PA         table
    # SHIT-A
    # NO_PA         prms
    # SHIT-A
    # NO_PA         msr_query_p_1


class MsrQueryTopic1Association(Base):

    __tablename__ = "msr_query_topic_1_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    msr_query_topic_1s: Mapped[list["MsrQueryTopic1"]] = relationship(back_populates="association")


class HasMsrQueryTopic1s:

    @declared_attr
    def msr_query_topic_1_association_id(self):
        return Column(types.Integer, ForeignKey("msr_query_topic_1_association.rid"))

    @declared_attr
    def msr_query_topic_1_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sMsrQueryTopic1Association" % name,
            (MsrQueryTopic1Association,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.msr_query_topic_1s = association_proxy(
            "msr_query_topic_1_association",
            "msr_query_topic_1s",
            creator=lambda msr_query_topic_1s: assoc_cls(msr_query_topic_1s=msr_query_topic_1s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class MsrQueryTopic1(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_topic_1"  # MSR-QUERY-TOPIC-1Type   --  msr_query_topic_1

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_topic_1_association.rid"))
    association = relationship("MsrQueryTopic1Association", back_populates="msr_query_topic_1s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("msr_query_topic_1.rid"))
    children = relationship("MsrQueryTopic1")

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryProps": ("msr_query_props", "R"),
        "MsrQueryResultTopic1": ("msr_query_result_topic_1", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(single_parent=True)
    # SHIT-R
    msr_query_result_topic_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_result_topic_1.rid"))
    msr_query_result_topic_1: Mapped["MsrQueryResultTopic1"] = relationship(single_parent=True)


class ChapterAssociation(Base):

    __tablename__ = "chapter_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="association")


class HasChapters:

    @declared_attr
    def chapter_association_id(self):
        return Column(types.Integer, ForeignKey("chapter_association.rid"))

    @declared_attr
    def chapter_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sChapterAssociation" % name,
            (ChapterAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.chapters = association_proxy(
            "chapter_association",
            "chapters",
            creator=lambda chapters: assoc_cls(chapters=chapters),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Chapter(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasMsrQueryChapters,
):
    # SIMPLE: [] -- SR: True
    # P: []  --  C: []
    __tablename__ = "chapter"  # CHAPTERType   --  chapter

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("chapter_association.rid"))
    association = relationship("ChapterAssociation", back_populates="chapters")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("chapter.rid"))
    children = relationship("Chapter")

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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    ENUMS = {
        "_break": ["BREAK", "NO-BREAK"],
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }
    SELF_REF = True

    _break = StdString()
    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # SHIT-R
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         p
    # SHIT-A
    # NO_PA         verbatim
    # SHIT-A
    # NO_PA         figure
    # SHIT-A
    # NO_PA         formula
    # SHIT-A
    # NO_PA         _list
    # SHIT-A
    # NO_PA         def_list
    # SHIT-A
    # NO_PA         labeled_list
    # SHIT-A
    # NO_PA         note
    # SHIT-A
    # NO_PA         table
    # SHIT-A
    # NO_PA         prms
    # SHIT-A
    # NO_PA         msr_query_p_1
    # SHIT-A
    # NO_PA         topic_1
    # SHIT-A
    # NO_PA         msr_query_topic_1
    # SHIT-A
    # NO_PA         chapter
    # SHIT-A
    # NO_PA         msr_query_chapter


class Topic2Association(Base):

    __tablename__ = "topic_2_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    topic_2s: Mapped[list["Topic2"]] = relationship(back_populates="association")


class HasTopic2s:

    @declared_attr
    def topic_2_association_id(self):
        return Column(types.Integer, ForeignKey("topic_2_association.rid"))

    @declared_attr
    def topic_2_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sTopic2Association" % name,
            (Topic2Association,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.topic_2s = association_proxy(
            "topic_2_association",
            "topic_2s",
            creator=lambda topic_2s: assoc_cls(topic_2s=topic_2s),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Topic2(
    Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes, HasTables, HasMsrQueryP2s
):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "topic_2"  # TOPIC-2Type   --  topic_2

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("topic_2_association.rid"))
    association = relationship("Topic2Association", back_populates="topic_2s")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("topic_2.rid"))
    children = relationship("Topic2")

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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "MsrQueryP2": ("msr_query_p_2s", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }

    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         p
    # SHIT-A
    # NO_PA         verbatim
    # SHIT-A
    # NO_PA         figure
    # SHIT-A
    # NO_PA         formula
    # SHIT-A
    # NO_PA         _list
    # SHIT-A
    # NO_PA         def_list
    # SHIT-A
    # NO_PA         labeled_list
    # SHIT-A
    # NO_PA         note
    # SHIT-A
    # NO_PA         table
    # SHIT-A
    # NO_PA         msr_query_p_2


class RowAssociation(Base):

    __tablename__ = "_row_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    _rows: Mapped[list["Row"]] = relationship(back_populates="association")


class HasRows:

    @declared_attr
    def row_association_id(self):
        return Column(types.Integer, ForeignKey("_row_association.rid"))

    @declared_attr
    def _row_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sRowAssociation" % name,
            (RowAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls._rows = association_proxy(
            "_row_association",
            "_rows",
            creator=lambda _rows: assoc_cls(_rows=_rows),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Row(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: ['Entry']
    __tablename__ = "_row"  # ROWType   --  _row

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_row_association.rid"))
    association = relationship("RowAssociation", back_populates="_rows")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("_row.rid"))
    children = relationship("Row")

    ATTRIBUTES = {
        "ROWSEP": "rowsep",
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Entry": ("entry", "A"),
    }
    ENUMS = {
        "valign": ["TOP", "BOTTOM", "MIDDLE"],
    }

    rowsep = StdString()
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-A
    # PARENT-OBJ
    entry: Mapped[list["Entry"]] = relationship(back_populates="_row")


class ColspecAssociation(Base):

    __tablename__ = "colspec_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    colspecs: Mapped[list["Colspec"]] = relationship(back_populates="association")


class HasColspecs:

    @declared_attr
    def colspec_association_id(self):
        return Column(types.Integer, ForeignKey("colspec_association.rid"))

    @declared_attr
    def colspec_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sColspecAssociation" % name,
            (ColspecAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.colspecs = association_proxy(
            "colspec_association",
            "colspecs",
            creator=lambda colspecs: assoc_cls(colspecs=colspecs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Colspec(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "colspec"  # COLSPECType   --  colspec

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("colspec_association.rid"))
    association = relationship("ColspecAssociation", back_populates="colspecs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("colspec.rid"))
    children = relationship("Colspec")

    ATTRIBUTES = {}
    ELEMENTS = {}
    TERMINAL = True


class RequirementAssociation(Base):

    __tablename__ = "requirement_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    requirements: Mapped[list["Requirement"]] = relationship(back_populates="association")


class HasRequirements:

    @declared_attr
    def requirement_association_id(self):
        return Column(types.Integer, ForeignKey("requirement_association.rid"))

    @declared_attr
    def requirement_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sRequirementAssociation" % name,
            (RequirementAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.requirements = association_proxy(
            "requirement_association",
            "requirements",
            creator=lambda requirements: assoc_cls(requirements=requirements),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Requirement(Base):
    # SIMPLE: [] -- SR: True
    # P: []  --  C: []
    __tablename__ = "requirement"  # REQUIREMENTType   --  requirement

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("requirement_association.rid"))
    association = relationship("RequirementAssociation", back_populates="requirements")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("requirement.rid"))
    children = relationship("Requirement")

    ATTRIBUTES = {
        "ID": "_id",
        "F-ID-CLASS": "f_id_class",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "RequirementBody": ("requirement_body", "R"),
        "CriticalAspects": ("critical_aspects", "R"),
        "TechnicalAspects": ("technical_aspects", "R"),
        "RealtimeRequirements": ("realtime_requirements", "R"),
        "Risks": ("risks", "R"),
        "RequirementsDependency": ("requirements_dependency", "R"),
        "AddInfo": ("add_info", "R"),
        "Requirement": ("requirements", "A"),
    }
    SELF_REF = True

    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # SHIT-R
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # SHIT-R
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # SHIT-R
    requirement_body_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("requirement_body.rid"))
    requirement_body: Mapped["RequirementBody"] = relationship(single_parent=True)
    # SHIT-R
    critical_aspects_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("critical_aspects.rid"))
    critical_aspects: Mapped["CriticalAspects"] = relationship(single_parent=True)
    # SHIT-R
    technical_aspects_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("technical_aspects.rid"))
    technical_aspects: Mapped["TechnicalAspects"] = relationship(single_parent=True)
    # SHIT-R
    realtime_requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("realtime_requirements.rid"))
    realtime_requirements: Mapped["RealtimeRequirements"] = relationship(single_parent=True)
    # SHIT-R
    risks_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("risks.rid"))
    risks: Mapped["Risks"] = relationship(single_parent=True)
    # SHIT-R
    requirements_dependency_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("requirements_dependency.rid"))
    requirements_dependency: Mapped["RequirementsDependency"] = relationship(single_parent=True)
    # SHIT-R
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         requirement


class SwVariableRefAssociation(Base):

    __tablename__ = "sw_variable_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_variable_refs: Mapped[list["SwVariableRef"]] = relationship(back_populates="association")


class HasSwVariableRefs:

    @declared_attr
    def sw_variable_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_variable_ref_association.rid"))

    @declared_attr
    def sw_variable_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwVariableRefAssociation" % name,
            (SwVariableRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_variable_refs = association_proxy(
            "sw_variable_ref_association",
            "sw_variable_refs",
            creator=lambda sw_variable_refs: assoc_cls(sw_variable_refs=sw_variable_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwVariableRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variable_ref"  # SW-VARIABLE-REFType   --  sw_variable_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref_association.rid"))
    association = relationship("SwVariableRefAssociation", back_populates="sw_variable_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_variable_ref.rid"))
    children = relationship("SwVariableRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwSystemconstCodedRefAssociation(Base):

    __tablename__ = "sw_systemconst_coded_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_systemconst_coded_refs: Mapped[list["SwSystemconstCodedRef"]] = relationship(back_populates="association")


class HasSwSystemconstCodedRefs:

    @declared_attr
    def sw_systemconst_coded_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_systemconst_coded_ref_association.rid"))

    @declared_attr
    def sw_systemconst_coded_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwSystemconstCodedRefAssociation" % name,
            (SwSystemconstCodedRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_systemconst_coded_refs = association_proxy(
            "sw_systemconst_coded_ref_association",
            "sw_systemconst_coded_refs",
            creator=lambda sw_systemconst_coded_refs: assoc_cls(sw_systemconst_coded_refs=sw_systemconst_coded_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwSystemconstCodedRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_systemconst_coded_ref"  # SW-SYSTEMCONST-CODED-REFType   --  sw_systemconst_coded_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconst_coded_ref_association.rid"))
    association = relationship("SwSystemconstCodedRefAssociation", back_populates="sw_systemconst_coded_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_systemconst_coded_ref.rid"))
    children = relationship("SwSystemconstCodedRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwSystemconstPhysRefAssociation(Base):

    __tablename__ = "sw_systemconst_phys_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_systemconst_phys_refs: Mapped[list["SwSystemconstPhysRef"]] = relationship(back_populates="association")


class HasSwSystemconstPhysRefs:

    @declared_attr
    def sw_systemconst_phys_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_systemconst_phys_ref_association.rid"))

    @declared_attr
    def sw_systemconst_phys_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwSystemconstPhysRefAssociation" % name,
            (SwSystemconstPhysRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_systemconst_phys_refs = association_proxy(
            "sw_systemconst_phys_ref_association",
            "sw_systemconst_phys_refs",
            creator=lambda sw_systemconst_phys_refs: assoc_cls(sw_systemconst_phys_refs=sw_systemconst_phys_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwSystemconstPhysRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_systemconst_phys_ref"  # SW-SYSTEMCONST-PHYS-REFType   --  sw_systemconst_phys_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconst_phys_ref_association.rid"))
    association = relationship("SwSystemconstPhysRefAssociation", back_populates="sw_systemconst_phys_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_systemconst_phys_ref.rid"))
    children = relationship("SwSystemconstPhysRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class VfAssociation(Base):

    __tablename__ = "vf_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    vfs: Mapped[list["Vf"]] = relationship(back_populates="association")


class HasVfs:

    @declared_attr
    def vf_association_id(self):
        return Column(types.Integer, ForeignKey("vf_association.rid"))

    @declared_attr
    def vf_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sVfAssociation" % name,
            (VfAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.vfs = association_proxy(
            "vf_association",
            "vfs",
            creator=lambda vfs: assoc_cls(vfs=vfs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Vf(Base, HasSwSystemconstCodedRefs, HasSwSystemconstPhysRefs):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "vf"  # VFType   --  vf

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vf_association.rid"))
    association = relationship("VfAssociation", back_populates="vfs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("vf.rid"))
    children = relationship("Vf")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwSystemconstPhysRef": ("sw_systemconst_phys_refs", "A"),
    }
    TERMINAL = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-A
    # NO_PA         sw_systemconst_coded_ref
    # SHIT-A
    # NO_PA         sw_systemconst_phys_ref


class VtAssociation(Base):

    __tablename__ = "vt_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    vts: Mapped[list["Vt"]] = relationship(back_populates="association")


class HasVts:

    @declared_attr
    def vt_association_id(self):
        return Column(types.Integer, ForeignKey("vt_association.rid"))

    @declared_attr
    def vt_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sVtAssociation" % name,
            (VtAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.vts = association_proxy(
            "vt_association",
            "vts",
            creator=lambda vts: assoc_cls(vts=vts),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Vt(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "vt"  # VTType   --  vt

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vt_association.rid"))
    association = relationship("VtAssociation", back_populates="vts")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("vt.rid"))
    children = relationship("Vt")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class VhAssociation(Base):

    __tablename__ = "vh_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    vhs: Mapped[list["Vh"]] = relationship(back_populates="association")


class HasVhs:

    @declared_attr
    def vh_association_id(self):
        return Column(types.Integer, ForeignKey("vh_association.rid"))

    @declared_attr
    def vh_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sVhAssociation" % name,
            (VhAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.vhs = association_proxy(
            "vh_association",
            "vhs",
            creator=lambda vhs: assoc_cls(vhs=vhs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Vh(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "vh"  # VHType   --  vh

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vh_association.rid"))
    association = relationship("VhAssociation", back_populates="vhs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("vh.rid"))
    children = relationship("Vh")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class VAssociation(Base):

    __tablename__ = "v_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    vs: Mapped[list["V"]] = relationship(back_populates="association")


class HasVs:

    @declared_attr
    def v_association_id(self):
        return Column(types.Integer, ForeignKey("v_association.rid"))

    @declared_attr
    def v_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sVAssociation" % name,
            (VAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.vs = association_proxy(
            "v_association",
            "vs",
            creator=lambda vs: assoc_cls(vs=vs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class V(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "v"  # VType   --  v

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("v_association.rid"))
    association = relationship("VAssociation", back_populates="vs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("v.rid"))
    children = relationship("V")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    content = StdDecimal()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwInstanceRefAssociation(Base):

    __tablename__ = "sw_instance_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_instance_refs: Mapped[list["SwInstanceRef"]] = relationship(back_populates="association")


class HasSwInstanceRefs:

    @declared_attr
    def sw_instance_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_instance_ref_association.rid"))

    @declared_attr
    def sw_instance_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwInstanceRefAssociation" % name,
            (SwInstanceRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_instance_refs = association_proxy(
            "sw_instance_ref_association",
            "sw_instance_refs",
            creator=lambda sw_instance_refs: assoc_cls(sw_instance_refs=sw_instance_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwInstanceRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_instance_ref"  # SW-INSTANCE-REFType   --  sw_instance_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_ref_association.rid"))
    association = relationship("SwInstanceRefAssociation", back_populates="sw_instance_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_instance_ref.rid"))
    children = relationship("SwInstanceRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class VgAssociation(Base):

    __tablename__ = "vg_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    vgs: Mapped[list["Vg"]] = relationship(back_populates="association")


class HasVgs:

    @declared_attr
    def vg_association_id(self):
        return Column(types.Integer, ForeignKey("vg_association.rid"))

    @declared_attr
    def vg_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sVgAssociation" % name,
            (VgAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.vgs = association_proxy(
            "vg_association",
            "vgs",
            creator=lambda vgs: assoc_cls(vgs=vgs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Vg(Base, HasVfs, HasVts, HasVhs, HasVs, HasSwInstanceRefs):
    # SIMPLE: [] -- SR: True
    # P: []  --  C: []
    __tablename__ = "vg"  # VGType   --  vg

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vg_association.rid"))
    association = relationship("VgAssociation", back_populates="vgs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("vg.rid"))
    children = relationship("Vg")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "Vf": ("vfs", "A"),
        "Vt": ("vts", "A"),
        "Vh": ("vhs", "A"),
        "V": ("vs", "A"),
        "Vg": ("vgs", "A"),
        "SwInstanceRef": ("sw_instance_refs", "A"),
    }
    SELF_REF = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         vf
    # SHIT-A
    # NO_PA         vt
    # SHIT-A
    # NO_PA         vh
    # SHIT-A
    # NO_PA         v
    # SHIT-A
    # NO_PA         vg
    # SHIT-A
    # NO_PA         sw_instance_ref


class SwCalprmRefAssociation(Base):

    __tablename__ = "sw_calprm_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_calprm_refs: Mapped[list["SwCalprmRef"]] = relationship(back_populates="association")


class HasSwCalprmRefs:

    @declared_attr
    def sw_calprm_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_calprm_ref_association.rid"))

    @declared_attr
    def sw_calprm_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwCalprmRefAssociation" % name,
            (SwCalprmRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_calprm_refs = association_proxy(
            "sw_calprm_ref_association",
            "sw_calprm_refs",
            creator=lambda sw_calprm_refs: assoc_cls(sw_calprm_refs=sw_calprm_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwCalprmRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_ref"  # SW-CALPRM-REFType   --  sw_calprm_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_ref_association.rid"))
    association = relationship("SwCalprmRefAssociation", back_populates="sw_calprm_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_calprm_ref.rid"))
    children = relationship("SwCalprmRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwScaleConstrAssociation(Base):

    __tablename__ = "sw_scale_constr_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_scale_constrs: Mapped[list["SwScaleConstr"]] = relationship(back_populates="association")


class HasSwScaleConstrs:

    @declared_attr
    def sw_scale_constr_association_id(self):
        return Column(types.Integer, ForeignKey("sw_scale_constr_association.rid"))

    @declared_attr
    def sw_scale_constr_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwScaleConstrAssociation" % name,
            (SwScaleConstrAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_scale_constrs = association_proxy(
            "sw_scale_constr_association",
            "sw_scale_constrs",
            creator=lambda sw_scale_constrs: assoc_cls(sw_scale_constrs=sw_scale_constrs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwScaleConstr(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_scale_constr"  # SW-SCALE-CONSTRType   --  sw_scale_constr

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_scale_constr_association.rid"))
    association = relationship("SwScaleConstrAssociation", back_populates="sw_scale_constrs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_scale_constr.rid"))
    children = relationship("SwScaleConstr")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LowerLimit": ("lower_limit", "R"),
        "UpperLimit": ("upper_limit", "R"),
    }

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    lower_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("lower_limit.rid"))
    lower_limit: Mapped["LowerLimit"] = relationship(single_parent=True)
    # SHIT-R
    upper_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("upper_limit.rid"))
    upper_limit: Mapped["UpperLimit"] = relationship(single_parent=True)


class SwRecordLayoutRefAssociation(Base):

    __tablename__ = "sw_record_layout_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_record_layout_refs: Mapped[list["SwRecordLayoutRef"]] = relationship(back_populates="association")


class HasSwRecordLayoutRefs:

    @declared_attr
    def sw_record_layout_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_record_layout_ref_association.rid"))

    @declared_attr
    def sw_record_layout_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwRecordLayoutRefAssociation" % name,
            (SwRecordLayoutRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_record_layout_refs = association_proxy(
            "sw_record_layout_ref_association",
            "sw_record_layout_refs",
            creator=lambda sw_record_layout_refs: assoc_cls(sw_record_layout_refs=sw_record_layout_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwRecordLayoutRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_ref"  # SW-RECORD-LAYOUT-REFType   --  sw_record_layout_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_ref_association.rid"))
    association = relationship("SwRecordLayoutRefAssociation", back_populates="sw_record_layout_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_record_layout_ref.rid"))
    children = relationship("SwRecordLayoutRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutGroupAssociation(Base):

    __tablename__ = "sw_record_layout_group_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_record_layout_groups: Mapped[list["SwRecordLayoutGroup"]] = relationship(back_populates="association")


class HasSwRecordLayoutGroups:

    @declared_attr
    def sw_record_layout_group_association_id(self):
        return Column(types.Integer, ForeignKey("sw_record_layout_group_association.rid"))

    @declared_attr
    def sw_record_layout_group_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwRecordLayoutGroupAssociation" % name,
            (SwRecordLayoutGroupAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_record_layout_groups = association_proxy(
            "sw_record_layout_group_association",
            "sw_record_layout_groups",
            creator=lambda sw_record_layout_groups: assoc_cls(sw_record_layout_groups=sw_record_layout_groups),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwRecordLayoutGroup(Base, HasSwRecordLayoutRefs):
    # SIMPLE: [] -- SR: True
    # P: []  --  C: ['SwRecordLayoutV']
    __tablename__ = "sw_record_layout_group"  # SW-RECORD-LAYOUT-GROUPType   --  sw_record_layout_group

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group_association.rid"))
    association = relationship("SwRecordLayoutGroupAssociation", back_populates="sw_record_layout_groups")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_record_layout_group.rid"))
    children = relationship("SwRecordLayoutGroup")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Desc": ("_desc", "R"),
        "SwRecordLayoutGroupAxis": ("sw_record_layout_group_axis", "R"),
        "SwRecordLayoutGroupIndex": ("sw_record_layout_group_index", "R"),
        "SwGenericAxisParamTypeRef": ("sw_generic_axis_param_type_ref", "R"),
        "SwRecordLayoutGroupFrom": ("sw_record_layout_group_from", "R"),
        "SwRecordLayoutGroupTo": ("sw_record_layout_group_to", "R"),
        "SwRecordLayoutGroupStep": ("sw_record_layout_group_step", "R"),
        "SwRecordLayoutComponent": ("sw_record_layout_component", "R"),
        "SwRecordLayoutRef": ("sw_record_layout_refs", "A"),
        "SwRecordLayoutV": ("sw_record_layout_v", "A"),
        "SwRecordLayoutGroup": ("sw_record_layout_groups", "A"),
    }
    SELF_REF = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # SHIT-R
    sw_record_layout_group_axis_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group_axis.rid"))
    sw_record_layout_group_axis: Mapped["SwRecordLayoutGroupAxis"] = relationship(single_parent=True)
    # SHIT-R
    sw_record_layout_group_index_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group_index.rid"))
    sw_record_layout_group_index: Mapped["SwRecordLayoutGroupIndex"] = relationship(single_parent=True)
    # SHIT-R
    sw_generic_axis_param_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_generic_axis_param_type_ref.rid")
    )
    sw_generic_axis_param_type_ref: Mapped["SwGenericAxisParamTypeRef"] = relationship(single_parent=True)
    # SHIT-R
    sw_record_layout_group_from_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group_from.rid"))
    sw_record_layout_group_from: Mapped["SwRecordLayoutGroupFrom"] = relationship(single_parent=True)
    # SHIT-R
    sw_record_layout_group_to_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group_to.rid"))
    sw_record_layout_group_to: Mapped["SwRecordLayoutGroupTo"] = relationship(single_parent=True)
    # SHIT-R
    sw_record_layout_group_step_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group_step.rid"))
    sw_record_layout_group_step: Mapped["SwRecordLayoutGroupStep"] = relationship(single_parent=True)
    # SHIT-R
    sw_record_layout_component_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_component.rid"))
    sw_record_layout_component: Mapped["SwRecordLayoutComponent"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         sw_record_layout_ref
    # SHIT-A
    # PARENT-OBJ
    sw_record_layout_v: Mapped[list["SwRecordLayoutV"]] = relationship(back_populates="sw_record_layout_group")
    # SHIT-A
    # NO_PA         sw_record_layout_group


class SwCompuMethodRefAssociation(Base):

    __tablename__ = "sw_compu_method_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_compu_method_refs: Mapped[list["SwCompuMethodRef"]] = relationship(back_populates="association")


class HasSwCompuMethodRefs:

    @declared_attr
    def sw_compu_method_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_compu_method_ref_association.rid"))

    @declared_attr
    def sw_compu_method_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwCompuMethodRefAssociation" % name,
            (SwCompuMethodRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_compu_method_refs = association_proxy(
            "sw_compu_method_ref_association",
            "sw_compu_method_refs",
            creator=lambda sw_compu_method_refs: assoc_cls(sw_compu_method_refs=sw_compu_method_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwCompuMethodRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_method_ref"  # SW-COMPU-METHOD-REFType   --  sw_compu_method_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_method_ref_association.rid"))
    association = relationship("SwCompuMethodRefAssociation", back_populates="sw_compu_method_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_compu_method_ref.rid"))
    children = relationship("SwCompuMethodRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwGenericAxisParamAssociation(Base):

    __tablename__ = "sw_generic_axis_param_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_generic_axis_params: Mapped[list["SwGenericAxisParam"]] = relationship(back_populates="association")


class HasSwGenericAxisParams:

    @declared_attr
    def sw_generic_axis_param_association_id(self):
        return Column(types.Integer, ForeignKey("sw_generic_axis_param_association.rid"))

    @declared_attr
    def sw_generic_axis_param_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwGenericAxisParamAssociation" % name,
            (SwGenericAxisParamAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_generic_axis_params = association_proxy(
            "sw_generic_axis_param_association",
            "sw_generic_axis_params",
            creator=lambda sw_generic_axis_params: assoc_cls(sw_generic_axis_params=sw_generic_axis_params),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwGenericAxisParam(Base, HasVfs):
    # SIMPLE: [] -- SR: True
    # P: ('SwGenericAxisParams', 'sw_generic_axis_params')  --  C: []
    __tablename__ = "sw_generic_axis_param"  # SW-GENERIC-AXIS-PARAMType   --  sw_generic_axis_param

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_param_association.rid"))
    association = relationship("SwGenericAxisParamAssociation", back_populates="sw_generic_axis_params")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_generic_axis_param.rid"))
    children = relationship("SwGenericAxisParam")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwGenericAxisParamTypeRef": ("sw_generic_axis_param_type_ref", "R"),
        "Vf": ("vfs", "A"),
    }
    SELF_REF = True

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    sw_generic_axis_param_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_generic_axis_param_type_ref.rid")
    )
    sw_generic_axis_param_type_ref: Mapped["SwGenericAxisParamTypeRef"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         vf
    # PARENT-ASSO
    sw_generic_axis_params_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_params.rid"))
    sw_generic_axis_params: Mapped["SwGenericAxisParams"] = relationship(back_populates="sw_generic_axis_param")


class SwVariableRefSyscondAssociation(Base):

    __tablename__ = "sw_variable_ref_syscond_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_variable_ref_sysconds: Mapped[list["SwVariableRefSyscond"]] = relationship(back_populates="association")


class HasSwVariableRefSysconds:

    @declared_attr
    def sw_variable_ref_syscond_association_id(self):
        return Column(types.Integer, ForeignKey("sw_variable_ref_syscond_association.rid"))

    @declared_attr
    def sw_variable_ref_syscond_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwVariableRefSyscondAssociation" % name,
            (SwVariableRefSyscondAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_variable_ref_sysconds = association_proxy(
            "sw_variable_ref_syscond_association",
            "sw_variable_ref_sysconds",
            creator=lambda sw_variable_ref_sysconds: assoc_cls(sw_variable_ref_sysconds=sw_variable_ref_sysconds),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwVariableRefSyscond(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variable_ref_syscond"  # SW-VARIABLE-REF-SYSCONDType   --  sw_variable_ref_syscond

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref_syscond_association.rid"))
    association = relationship("SwVariableRefSyscondAssociation", back_populates="sw_variable_ref_sysconds")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_variable_ref_syscond.rid"))
    children = relationship("SwVariableRefSyscond")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_ref", "R"),
        "SwSyscond": ("sw_syscond", "R"),
    }

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    sw_variable_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref.rid"))
    sw_variable_ref: Mapped["SwVariableRef"] = relationship(single_parent=True)
    # SHIT-R
    sw_syscond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_syscond.rid"))
    sw_syscond: Mapped["SwSyscond"] = relationship(single_parent=True)


class SwCalprmRefSyscondAssociation(Base):

    __tablename__ = "sw_calprm_ref_syscond_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_calprm_ref_sysconds: Mapped[list["SwCalprmRefSyscond"]] = relationship(back_populates="association")


class HasSwCalprmRefSysconds:

    @declared_attr
    def sw_calprm_ref_syscond_association_id(self):
        return Column(types.Integer, ForeignKey("sw_calprm_ref_syscond_association.rid"))

    @declared_attr
    def sw_calprm_ref_syscond_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwCalprmRefSyscondAssociation" % name,
            (SwCalprmRefSyscondAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_calprm_ref_sysconds = association_proxy(
            "sw_calprm_ref_syscond_association",
            "sw_calprm_ref_sysconds",
            creator=lambda sw_calprm_ref_sysconds: assoc_cls(sw_calprm_ref_sysconds=sw_calprm_ref_sysconds),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwCalprmRefSyscond(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_ref_syscond"  # SW-CALPRM-REF-SYSCONDType   --  sw_calprm_ref_syscond

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_ref_syscond_association.rid"))
    association = relationship("SwCalprmRefSyscondAssociation", back_populates="sw_calprm_ref_sysconds")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_calprm_ref_syscond.rid"))
    children = relationship("SwCalprmRefSyscond")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": ("sw_calprm_ref", "R"),
        "SwSyscond": ("sw_syscond", "R"),
    }

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    sw_calprm_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_ref.rid"))
    sw_calprm_ref: Mapped["SwCalprmRef"] = relationship(single_parent=True)
    # SHIT-R
    sw_syscond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_syscond.rid"))
    sw_syscond: Mapped["SwSyscond"] = relationship(single_parent=True)


class SwClassInstanceRefAssociation(Base):

    __tablename__ = "sw_class_instance_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_class_instance_refs: Mapped[list["SwClassInstanceRef"]] = relationship(back_populates="association")


class HasSwClassInstanceRefs:

    @declared_attr
    def sw_class_instance_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_class_instance_ref_association.rid"))

    @declared_attr
    def sw_class_instance_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwClassInstanceRefAssociation" % name,
            (SwClassInstanceRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_class_instance_refs = association_proxy(
            "sw_class_instance_ref_association",
            "sw_class_instance_refs",
            creator=lambda sw_class_instance_refs: assoc_cls(sw_class_instance_refs=sw_class_instance_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwClassInstanceRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_class_instance_ref"  # SW-CLASS-INSTANCE-REFType   --  sw_class_instance_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_instance_ref_association.rid"))
    association = relationship("SwClassInstanceRefAssociation", back_populates="sw_class_instance_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_class_instance_ref.rid"))
    children = relationship("SwClassInstanceRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwInstanceRefSyscondAssociation(Base):

    __tablename__ = "sw_instance_ref_syscond_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_instance_ref_sysconds: Mapped[list["SwInstanceRefSyscond"]] = relationship(back_populates="association")


class HasSwInstanceRefSysconds:

    @declared_attr
    def sw_instance_ref_syscond_association_id(self):
        return Column(types.Integer, ForeignKey("sw_instance_ref_syscond_association.rid"))

    @declared_attr
    def sw_instance_ref_syscond_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwInstanceRefSyscondAssociation" % name,
            (SwInstanceRefSyscondAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_instance_ref_sysconds = association_proxy(
            "sw_instance_ref_syscond_association",
            "sw_instance_ref_sysconds",
            creator=lambda sw_instance_ref_sysconds: assoc_cls(sw_instance_ref_sysconds=sw_instance_ref_sysconds),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwInstanceRefSyscond(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_instance_ref_syscond"  # SW-INSTANCE-REF-SYSCONDType   --  sw_instance_ref_syscond

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_ref_syscond_association.rid"))
    association = relationship("SwInstanceRefSyscondAssociation", back_populates="sw_instance_ref_sysconds")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_instance_ref_syscond.rid"))
    children = relationship("SwInstanceRefSyscond")

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": ("sw_class_instance_ref", "R"),
        "SwSyscond": ("sw_syscond", "R"),
    }

    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    sw_class_instance_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_instance_ref.rid"))
    sw_class_instance_ref: Mapped["SwClassInstanceRef"] = relationship(single_parent=True)
    # SHIT-R
    sw_syscond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_syscond.rid"))
    sw_syscond: Mapped["SwSyscond"] = relationship(single_parent=True)


class SwFeatureRefAssociation(Base):

    __tablename__ = "sw_feature_ref_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_feature_refs: Mapped[list["SwFeatureRef"]] = relationship(back_populates="association")


class HasSwFeatureRefs:

    @declared_attr
    def sw_feature_ref_association_id(self):
        return Column(types.Integer, ForeignKey("sw_feature_ref_association.rid"))

    @declared_attr
    def sw_feature_ref_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwFeatureRefAssociation" % name,
            (SwFeatureRefAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_feature_refs = association_proxy(
            "sw_feature_ref_association",
            "sw_feature_refs",
            creator=lambda sw_feature_refs: assoc_cls(sw_feature_refs=sw_feature_refs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwFeatureRef(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_ref"  # SW-FEATURE-REFType   --  sw_feature_ref

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_ref_association.rid"))
    association = relationship("SwFeatureRefAssociation", back_populates="sw_feature_refs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_feature_ref.rid"))
    children = relationship("SwFeatureRef")

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
    ELEMENTS = {}
    TERMINAL = True

    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwInstanceAssociation(Base):

    __tablename__ = "sw_instance_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sw_instances: Mapped[list["SwInstance"]] = relationship(back_populates="association")


class HasSwInstances:

    @declared_attr
    def sw_instance_association_id(self):
        return Column(types.Integer, ForeignKey("sw_instance_association.rid"))

    @declared_attr
    def sw_instance_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSwInstanceAssociation" % name,
            (SwInstanceAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sw_instances = association_proxy(
            "sw_instance_association",
            "sw_instances",
            creator=lambda sw_instances: assoc_cls(sw_instances=sw_instances),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class SwInstance(Base):
    # SIMPLE: [] -- SR: True
    # P: []  --  C: []
    __tablename__ = "sw_instance"  # SW-INSTANCEType   --  sw_instance

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_association.rid"))
    association = relationship("SwInstanceAssociation", back_populates="sw_instances")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sw_instance.rid"))
    children = relationship("SwInstance")

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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "SwArrayIndex": ("sw_array_index", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "DisplayName": ("display_name", "R"),
        "SwValueCont": ("sw_value_cont", "R"),
        "SwAxisConts": ("sw_axis_conts", "R"),
        "SwModelLink": ("sw_model_link", "R"),
        "SwCsFlags": ("sw_cs_flags", "R"),
        "SwCsHistory": ("sw_cs_history", "R"),
        "AdminData": ("admin_data", "R"),
        "SwFeatureRef": ("sw_feature_ref", "R"),
        "SwInstancePropsVariants": ("sw_instance_props_variants", "R"),
        "SwInstance": ("sw_instances", "A"),
    }
    SELF_REF = True

    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # SHIT-R
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # SHIT-R
    sw_array_index_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_array_index.rid"))
    sw_array_index: Mapped["SwArrayIndex"] = relationship(single_parent=True)
    # SHIT-R
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # SHIT-R
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # SHIT-R
    display_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("display_name.rid"))
    display_name: Mapped["DisplayName"] = relationship(single_parent=True)
    # SHIT-R
    sw_value_cont_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_value_cont.rid"))
    sw_value_cont: Mapped["SwValueCont"] = relationship(single_parent=True)
    # SHIT-R
    sw_axis_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_conts.rid"))
    sw_axis_conts: Mapped["SwAxisConts"] = relationship(single_parent=True)
    # SHIT-R
    sw_model_link_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_model_link.rid"))
    sw_model_link: Mapped["SwModelLink"] = relationship(single_parent=True)
    # SHIT-R
    sw_cs_flags_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_flags.rid"))
    sw_cs_flags: Mapped["SwCsFlags"] = relationship(single_parent=True)
    # SHIT-R
    sw_cs_history_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_history.rid"))
    sw_cs_history: Mapped["SwCsHistory"] = relationship(single_parent=True)
    # SHIT-R
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # SHIT-R
    sw_feature_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_ref.rid"))
    sw_feature_ref: Mapped["SwFeatureRef"] = relationship(single_parent=True)
    # SHIT-R
    sw_instance_props_variants_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_props_variants.rid"))
    sw_instance_props_variants: Mapped["SwInstancePropsVariants"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         sw_instance


class SdAssociation(Base):

    __tablename__ = "sd_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sds: Mapped[list["Sd"]] = relationship(back_populates="association")


class HasSds:

    @declared_attr
    def sd_association_id(self):
        return Column(types.Integer, ForeignKey("sd_association.rid"))

    @declared_attr
    def sd_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSdAssociation" % name,
            (SdAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sds = association_proxy(
            "sd_association",
            "sds",
            creator=lambda sds: assoc_cls(sds=sds),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Sd(Base):
    # SIMPLE: [] -- SR: False
    # P: []  --  C: []
    __tablename__ = "sd"  # SDType   --  sd

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sd_association.rid"))
    association = relationship("SdAssociation", back_populates="sds")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sd.rid"))
    children = relationship("Sd")

    ATTRIBUTES = {
        "GID": "gid",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True

    gid = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SdgAssociation(Base):

    __tablename__ = "sdg_association"

    discriminator = Column(sqa.String)
    __mapper_args__ = {"polymorphic_on": discriminator}
    sdgs: Mapped[list["Sdg"]] = relationship(back_populates="association")


class HasSdgs:

    @declared_attr
    def sdg_association_id(self):
        return Column(types.Integer, ForeignKey("sdg_association.rid"))

    @declared_attr
    def sdg_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sSdgAssociation" % name,
            (SdgAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.sdgs = association_proxy(
            "sdg_association",
            "sdgs",
            creator=lambda sdgs: assoc_cls(sdgs=sdgs),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


class Sdg(Base, HasXrefs, HasSds):
    # SIMPLE: [] -- SR: True
    # P: []  --  C: ['Ncoi1']
    __tablename__ = "sdg"  # SDGType   --  sdg

    association_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sdg_association.rid"))
    association = relationship("SdgAssociation", back_populates="sdgs")
    parent = association_proxy("association", "parent")
    _p_id = mapped_column(sqa.Integer, ForeignKey("sdg.rid"))
    children = relationship("Sdg")

    ATTRIBUTES = {
        "GID": "gid",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SdgCaption": ("sdg_caption", "R"),
        "Sd": ("sds", "A"),
        "Sdg": ("sdgs", "A"),
        "Ncoi1": ("ncoi_1", "A"),
        "Xref": ("xrefs", "A"),
    }
    SELF_REF = True

    gid = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # SHIT-R
    sdg_caption_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sdg_caption.rid"))
    sdg_caption: Mapped["SdgCaption"] = relationship(single_parent=True)
    # SHIT-A
    # NO_PA         sd
    # SHIT-A
    # NO_PA         sdg
    # SHIT-A
    # PARENT-OBJ
    ncoi_1: Mapped[list["Ncoi1"]] = relationship(back_populates="sdg")
    # SHIT-A
    # NO_PA         xref


#
#   Definitions
#


class ShortName(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "short_name"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Category(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "category"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Label(Base, HasTts, HasEs, HasSups, HasSubs, HasIes):
    # SIMPLE: SwCalprmValueAxisLabels == SR: False
    # P: ('SwCalprmValueAxisLabels', 'sw_calprm_value_axis_labels')  --  C: []
    __tablename__ = "label"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "E": ("es", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # PARENT
    sw_calprm_value_axis_labels_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_value_axis_labels.rid"))
    sw_calprm_value_axis_labels: Mapped["SwCalprmValueAxisLabels"] = relationship(back_populates="label")


class Language(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "language"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Desc(Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         msr_query_text


class OverallProject(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "overall_project"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "Desc": ("_desc", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)

    # N-I: Tt

    # N-I: E

    # N-I: Sup

    # N-I: Sub

    # N-I: Ie


class Companies(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Company']
    __tablename__ = "companies"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Company": ("company", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    company: Mapped[list["Company"]] = relationship(back_populates="companies")

    # N-I: Xref


class LongName1(Base, HasTts, HasEs, HasSups, HasSubs, HasIes):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "long_name_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "E": ("es", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie

    # N-I: XrefTarget

    # N-I: Ft


class MsrQueryName(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_name"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class MsrQueryResultText(Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_result_text"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         msr_query_text


class Comment(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "comment"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class MsrQueryArg(Base, HasXrefs):
    # SIMPLE: MsrQueryProps == SR: False
    # P: ('MsrQueryProps', 'msr_query_props')  --  C: []
    __tablename__ = "msr_query_arg"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Xref": ("xrefs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         xref
    # PARENT
    msr_query_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_props.rid"))
    msr_query_props: Mapped["MsrQueryProps"] = relationship(back_populates="msr_query_arg")


class MsrQueryProps(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['MsrQueryArg']
    __tablename__ = "msr_query_props"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MsrQueryName": ("msr_query_name", "R"),
        "MsrQueryArg": ("msr_query_arg", "A"),
        "Comment": ("comment", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    msr_query_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_query_name.rid"))
    msr_query_name: Mapped["MsrQueryName"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    msr_query_arg: Mapped[list["MsrQueryArg"]] = relationship(back_populates="msr_query_props")
    # REF
    comment_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("comment.rid"))
    comment: Mapped["Comment"] = relationship(single_parent=True)

    # N-I: MsrQueryText


class Na(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "na"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class TeamMemberRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['TeamMemberRef']
    __tablename__ = "team_member_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TeamMemberRef": ("team_member_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    team_member_ref: Mapped[list["TeamMemberRef"]] = relationship(back_populates="team_member_refs")


class LongName(Base, HasTts, HasEs, HasSups, HasSubs, HasIes):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "long_name"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "E": ("es", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
    }
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie


class Roles(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Role']
    __tablename__ = "roles"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
        "F-CHILD-TYPE": "f_child_type",
    }
    ELEMENTS = {
        "Role": ("role", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    f_child_type = StdString()
    # ARR
    # PARENT-OBJ
    role: Mapped[list["Role"]] = relationship(back_populates="roles")


class TeamMembers(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['TeamMember']
    __tablename__ = "team_members"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TeamMember": ("team_member", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    team_member: Mapped[list["TeamMember"]] = relationship(back_populates="team_members")


class Role(Base):
    # SIMPLE: Roles == SR: False
    # P: ('Roles', 'roles')  --  C: []
    __tablename__ = "role"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    roles_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("roles.rid"))
    roles: Mapped["Roles"] = relationship(back_populates="role")


class Company(Base):
    # SIMPLE: Companies == SR: False
    # P: ('Companies', 'companies')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Roles": ("roles", "R"),
        "TeamMembers": ("team_members", "R"),
    }
    ENUMS = {
        "role": ["MANUFACTURER", "SUPPLIER"],
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
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    roles_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("roles.rid"))
    roles: Mapped["Roles"] = relationship(single_parent=True)
    # REF
    team_members_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_members.rid"))
    team_members: Mapped["TeamMembers"] = relationship(single_parent=True)
    # PARENT
    companies_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("companies.rid"))
    companies: Mapped["Companies"] = relationship(back_populates="company")


class Department(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "department"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Address(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "address"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Zip(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "_zip"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class City(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "city"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Phone(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "phone"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Fax(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "fax"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Email(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "email"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Homepage(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "homepage"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class TeamMember(Base):
    # SIMPLE: TeamMembers == SR: False
    # P: ('TeamMembers', 'team_members')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Roles": ("roles", "R"),
        "Department": ("department", "R"),
        "Address": ("address", "R"),
        "Zip": ("_zip", "R"),
        "City": ("city", "R"),
        "Phone": ("phone", "R"),
        "Fax": ("fax", "R"),
        "Email": ("email", "R"),
        "Homepage": ("homepage", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    roles_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("roles.rid"))
    roles: Mapped["Roles"] = relationship(single_parent=True)
    # REF
    department_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("department.rid"))
    department: Mapped["Department"] = relationship(single_parent=True)
    # REF
    address_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("address.rid"))
    address: Mapped["Address"] = relationship(single_parent=True)
    # REF
    zip_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_zip.rid"))
    _zip: Mapped["Zip"] = relationship(single_parent=True)
    # REF
    city_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("city.rid"))
    city: Mapped["City"] = relationship(single_parent=True)
    # REF
    phone_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("phone.rid"))
    phone: Mapped["Phone"] = relationship(single_parent=True)
    # REF
    fax_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("fax.rid"))
    fax: Mapped["Fax"] = relationship(single_parent=True)
    # REF
    email_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("email.rid"))
    email: Mapped["Email"] = relationship(single_parent=True)
    # REF
    homepage_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("homepage.rid"))
    homepage: Mapped["Homepage"] = relationship(single_parent=True)
    # PARENT
    team_members_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_members.rid"))
    team_members: Mapped["TeamMembers"] = relationship(back_populates="team_member")


class SampleRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "date"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    content = StdDate()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Tbr(
    Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts, HasStds, HasXdocs, HasXfiles
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tbr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "Std": ("stds", "A"),
        "Xdoc": ("xdocs", "A"),
        "Xfile": ("xfiles", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         std
    # ARR
    # NO_PA         xdoc
    # ARR
    # NO_PA         xfile
    # ARR
    # NO_PA         msr_query_text


class Schedule(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "schedule"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SampleRef": ("sample_ref", "R"),
        "Date": ("date", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sample_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sample_ref.rid"))
    sample_ref: Mapped["SampleRef"] = relationship(single_parent=True)
    # REF
    date_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date.rid"))
    date: Mapped["Date"] = relationship(single_parent=True)


class TeamMemberRef(Base):
    # SIMPLE: TeamMemberRefs == SR: False
    # P: ('TeamMemberRefs', 'team_member_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    team_member_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_member_refs.rid"))
    team_member_refs: Mapped["TeamMemberRefs"] = relationship(back_populates="team_member_ref")


class Tbd(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tbd"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "TeamMemberRefs": ("team_member_refs", "R"),
        "Schedule": ("schedule", "R"),
        "Desc": ("_desc", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    team_member_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_member_refs.rid"))
    team_member_refs: Mapped["TeamMemberRefs"] = relationship(single_parent=True)
    # REF
    schedule_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("schedule.rid"))
    schedule: Mapped["Schedule"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)


class UsedLanguages(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "used_languages"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class CompanyDocInfos(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['CompanyDocInfo']
    __tablename__ = "company_doc_infos"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyDocInfo": ("company_doc_info", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    company_doc_info: Mapped[list["CompanyDocInfo"]] = relationship(back_populates="company_doc_infos")


class FormatterCtrls(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['FormatterCtrl']
    __tablename__ = "formatter_ctrls"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FormatterCtrl": ("formatter_ctrl", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    formatter_ctrl: Mapped[list["FormatterCtrl"]] = relationship(back_populates="formatter_ctrls")


class Subtitle(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "subtitle"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class State1(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "state_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Date1(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "date_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Url(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "url"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Position(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "position"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: Std


class Number(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "number"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Publisher(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "publisher"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: Xdoc


class Notation(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "notation"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Tool(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tool"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class ToolVersion(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tool_version"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: Xfile


class Introduction(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasMsrQueryP2s,
    HasTopic2s,
    HasMsrQueryTopic2s,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "introduction"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "MsrQueryP2": ("msr_query_p_2s", "A"),
        "Topic2": ("topic_2s", "A"),
        "MsrQueryTopic2": ("msr_query_topic_2s", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         msr_query_p_2
    # ARR
    # NO_PA         topic_2
    # ARR
    # NO_PA         msr_query_topic_2


class DocRevisions(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['DocRevision']
    __tablename__ = "doc_revisions"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "DocRevision": ("doc_revision", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    doc_revision: Mapped[list["DocRevision"]] = relationship(back_populates="doc_revisions")


class AdminData(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "admin_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Language": ("language", "R"),
        "UsedLanguages": ("used_languages", "R"),
        "CompanyDocInfos": ("company_doc_infos", "R"),
        "FormatterCtrls": ("formatter_ctrls", "R"),
        "DocRevisions": ("doc_revisions", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    language_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("language.rid"))
    language: Mapped["Language"] = relationship(single_parent=True)
    # REF
    used_languages_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("used_languages.rid"))
    used_languages: Mapped["UsedLanguages"] = relationship(single_parent=True)
    # REF
    company_doc_infos_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("company_doc_infos.rid"))
    company_doc_infos: Mapped["CompanyDocInfos"] = relationship(single_parent=True)
    # REF
    formatter_ctrls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("formatter_ctrls.rid"))
    formatter_ctrls: Mapped["FormatterCtrls"] = relationship(single_parent=True)
    # REF
    doc_revisions_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("doc_revisions.rid"))
    doc_revisions: Mapped["DocRevisions"] = relationship(single_parent=True)


class Ncoi1(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: Sdg == SR: False
    # P: ('Sdg', 'sdg')  --  C: []
    __tablename__ = "ncoi_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter
    # PARENT
    sdg_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sdg.rid"))
    sdg: Mapped["Sdg"] = relationship(back_populates="ncoi_1")


class CompanyRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "doc_label"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class PrivateCodes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['PrivateCode']
    __tablename__ = "private_codes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "PrivateCode": ("private_code", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    private_code: Mapped[list["PrivateCode"]] = relationship(back_populates="private_codes")


class EntityName(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "entity_name"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class PrivateCode(Base):
    # SIMPLE: PrivateCodes == SR: False
    # P: ('PrivateCodes', 'private_codes')  --  C: []
    __tablename__ = "private_code"

    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    private_codes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("private_codes.rid"))
    private_codes: Mapped["PrivateCodes"] = relationship(back_populates="private_code")


class CompanyDocInfo(Base):
    # SIMPLE: CompanyDocInfos == SR: False
    # P: ('CompanyDocInfos', 'company_doc_infos')  --  C: []
    __tablename__ = "company_doc_info"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRef": ("company_ref", "R"),
        "DocLabel": ("doc_label", "R"),
        "TeamMemberRef": ("team_member_ref", "R"),
        "PrivateCodes": ("private_codes", "R"),
        "EntityName": ("entity_name", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    company_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("company_ref.rid"))
    company_ref: Mapped["CompanyRef"] = relationship(single_parent=True)
    # REF
    doc_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("doc_label.rid"))
    doc_label: Mapped["DocLabel"] = relationship(single_parent=True)
    # REF
    team_member_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_member_ref.rid"))
    team_member_ref: Mapped["TeamMemberRef"] = relationship(single_parent=True)
    # REF
    private_codes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("private_codes.rid"))
    private_codes: Mapped["PrivateCodes"] = relationship(single_parent=True)
    # REF
    entity_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("entity_name.rid"))
    entity_name: Mapped["EntityName"] = relationship(single_parent=True)
    # PARENT
    company_doc_infos_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("company_doc_infos.rid"))
    company_doc_infos: Mapped["CompanyDocInfos"] = relationship(back_populates="company_doc_info")


class SystemOverview(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "system_overview"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FormatterCtrl(Base):
    # SIMPLE: FormatterCtrls == SR: False
    # P: ('FormatterCtrls', 'formatter_ctrls')  --  C: []
    __tablename__ = "formatter_ctrl"

    ATTRIBUTES = {
        "TARGET-SYSTEM": "target_system",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    target_system = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    formatter_ctrls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("formatter_ctrls.rid"))
    formatter_ctrls: Mapped["FormatterCtrls"] = relationship(back_populates="formatter_ctrl")


class ReasonOrder(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "reason_order"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class CompanyRevisionInfos(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['CompanyRevisionInfo']
    __tablename__ = "company_revision_infos"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRevisionInfo": ("company_revision_info", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    company_revision_info: Mapped[list["CompanyRevisionInfo"]] = relationship(back_populates="company_revision_infos")


class RevisionLabel(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "revision_label"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class State(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "state"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Remark(Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "remark"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note


class IssuedBy(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "issued_by"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class CompanyRevisionInfo(Base):
    # SIMPLE: CompanyRevisionInfos == SR: False
    # P: ('CompanyRevisionInfos', 'company_revision_infos')  --  C: []
    __tablename__ = "company_revision_info"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRef": ("company_ref", "R"),
        "RevisionLabel": ("revision_label", "R"),
        "State": ("state", "R"),
        "Remark": ("remark", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    company_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("company_ref.rid"))
    company_ref: Mapped["CompanyRef"] = relationship(single_parent=True)
    # REF
    revision_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("revision_label.rid"))
    revision_label: Mapped["RevisionLabel"] = relationship(single_parent=True)
    # REF
    state_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("state.rid"))
    state: Mapped["State"] = relationship(single_parent=True)
    # REF
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)
    # PARENT
    company_revision_infos_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("company_revision_infos.rid"))
    company_revision_infos: Mapped["CompanyRevisionInfos"] = relationship(back_populates="company_revision_info")

    # N-I: P

    # N-I: Verbatim


class FigureCaption(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)


class Graphic(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    ENUMS = {
        "category": ["BARCODE", "CONCEPTUAL", "ENGINEERING", "FLOWCHART", "GRAPH", "LOGO", "SCHEMATIC", "WAVEFORM"],
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Area']
    __tablename__ = "_map"

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
        "Area": ("area", "A"),
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
    # ARR
    # PARENT-OBJ
    area: Mapped[list["Area"]] = relationship(back_populates="_map")

    # N-I: Figure


class Area(Base):
    # SIMPLE: Map == SR: False
    # P: ('Map', '_map')  --  C: []
    __tablename__ = "area"

    ATTRIBUTES = {}
    ELEMENTS = {}
    TERMINAL = True
    # PARENT
    _map_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_map.rid"))
    _map: Mapped["Map"] = relationship(back_populates="area")


class FormulaCaption(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)


class TexMath(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tex_math"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class CCode(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "c_code"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class GenericMath(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "generic_math"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: Formula

    # N-I: List


class Item(Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes):
    # SIMPLE: List == SR: False
    # P: ('List', '_list')  --  C: []
    __tablename__ = "item"

    ATTRIBUTES = {
        "KEEP-WITH-PREVIOUS": "keep_with_previous",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # PARENT
    _list_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_list.rid"))
    _list: Mapped["List"] = relationship(back_populates="item")

    # N-I: DefList


class Def(Base, HasPs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "_def"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p


class DefItem(Base):
    # SIMPLE: DefList == SR: False
    # P: ('DefList', 'def_list')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Def": ("_def", "R"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }
    _id = StdString()
    f_id_class = StdString()
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    def_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_def.rid"))
    _def: Mapped["Def"] = relationship(single_parent=True)
    # PARENT
    def_list_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("def_list.rid"))
    def_list: Mapped["DefList"] = relationship(back_populates="def_item")


class IndentSample(Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "indent_sample"

    ATTRIBUTES = {
        "ITEM-LABEL-POS": "item_label_pos",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    ENUMS = {
        "item_label_pos": ["NO-NEWLINE", "NEWLINE", "NEWLINE-IF-NECESSARY"],
    }
    item_label_pos = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         msr_query_text

    # N-I: LabeledList


class ItemLabel(Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "item_label"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         msr_query_text


class LabeledItem(Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes):
    # SIMPLE: LabeledList == SR: False
    # P: ('LabeledList', 'labeled_list')  --  C: []
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
        "ItemLabel": ("item_label", "R"),
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
    }
    ENUMS = {
        "keep_with_previous": ["KEEP", "NO-KEEP"],
    }
    help_entry = StdString()
    keep_with_previous = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    item_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("item_label.rid"))
    item_label: Mapped["ItemLabel"] = relationship(single_parent=True)
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # PARENT
    labeled_list_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("labeled_list.rid"))
    labeled_list: Mapped["LabeledList"] = relationship(back_populates="labeled_item")

    # N-I: Note


class Modifications(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Modification']
    __tablename__ = "modifications"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Modification": ("modification", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    modification: Mapped[list["Modification"]] = relationship(back_populates="modifications")


class DocRevision(Base):
    # SIMPLE: DocRevisions == SR: False
    # P: ('DocRevisions', 'doc_revisions')  --  C: []
    __tablename__ = "doc_revision"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CompanyRevisionInfos": ("company_revision_infos", "R"),
        "RevisionLabel": ("revision_label", "R"),
        "State": ("state", "R"),
        "IssuedBy": ("issued_by", "R"),
        "TeamMemberRef": ("team_member_ref", "R"),
        "Date": ("date", "R"),
        "Modifications": ("modifications", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    company_revision_infos_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("company_revision_infos.rid"))
    company_revision_infos: Mapped["CompanyRevisionInfos"] = relationship(single_parent=True)
    # REF
    revision_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("revision_label.rid"))
    revision_label: Mapped["RevisionLabel"] = relationship(single_parent=True)
    # REF
    state_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("state.rid"))
    state: Mapped["State"] = relationship(single_parent=True)
    # REF
    issued_by_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("issued_by.rid"))
    issued_by: Mapped["IssuedBy"] = relationship(single_parent=True)
    # REF
    team_member_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_member_ref.rid"))
    team_member_ref: Mapped["TeamMemberRef"] = relationship(single_parent=True)
    # REF
    date_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date.rid"))
    date: Mapped["Date"] = relationship(single_parent=True)
    # REF
    modifications_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("modifications.rid"))
    modifications: Mapped["Modifications"] = relationship(single_parent=True)
    # PARENT
    doc_revisions_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("doc_revisions.rid"))
    doc_revisions: Mapped["DocRevisions"] = relationship(back_populates="doc_revision")


class Change(Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "change"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         msr_query_text


class Reason(Base, HasTts, HasEs, HasSups, HasSubs, HasIes, HasXrefs, HasXrefTargets, HasFts, HasMsrQueryTexts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "reason"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Tt": ("tts", "A"),
        "Xref": ("xrefs", "A"),
        "XrefTarget": ("xref_targets", "A"),
        "E": ("es", "A"),
        "Ft": ("fts", "A"),
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
        "Ie": ("ies", "A"),
        "MsrQueryText": ("msr_query_texts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         tt
    # ARR
    # NO_PA         xref
    # ARR
    # NO_PA         xref_target
    # ARR
    # NO_PA         e
    # ARR
    # NO_PA         ft
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub
    # ARR
    # NO_PA         ie
    # ARR
    # NO_PA         msr_query_text


class Modification(Base):
    # SIMPLE: Modifications == SR: False
    # P: ('Modifications', 'modifications')  --  C: []
    __tablename__ = "modification"

    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Change": ("change", "R"),
        "Reason": ("reason", "R"),
    }
    ENUMS = {
        "_type": ["CONTENT-RELATED", "DOC-RELATED"],
    }
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    change_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("change.rid"))
    change: Mapped["Change"] = relationship(single_parent=True)
    # REF
    reason_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("reason.rid"))
    reason: Mapped["Reason"] = relationship(single_parent=True)
    # PARENT
    modifications_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("modifications.rid"))
    modifications: Mapped["Modifications"] = relationship(back_populates="modification")


class ProductDesc(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "product_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class TableCaption(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)

    # N-I: Table


class Thead(Base, HasColspecs, HasRows):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "thead"

    ATTRIBUTES = {
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Colspec": ("colspecs", "A"),
        "Row": ("_rows", "A"),
    }
    ENUMS = {
        "valign": ["TOP", "MIDDLE", "BOTTOM"],
    }
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         colspec
    # ARR
    # NO_PA         _row

    # N-I: Colspec


class Spanspec(Base):
    # SIMPLE: Tgroup == SR: False
    # P: ('Tgroup', 'tgroup')  --  C: []
    __tablename__ = "spanspec"

    ATTRIBUTES = {}
    ELEMENTS = {}
    TERMINAL = True
    # PARENT
    tgroup_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tgroup.rid"))
    tgroup: Mapped["Tgroup"] = relationship(back_populates="spanspec")


class Tfoot(Base, HasColspecs, HasRows):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tfoot"

    ATTRIBUTES = {
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Colspec": ("colspecs", "A"),
        "Row": ("_rows", "A"),
    }
    ENUMS = {
        "valign": ["TOP", "MIDDLE", "BOTTOM"],
    }
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         colspec
    # ARR
    # NO_PA         _row

    # N-I: Row


class Entry(Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes):
    # SIMPLE: Row == SR: False
    # P: ('Row', '_row')  --  C: []
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
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
    }
    ENUMS = {
        "valign": ["TOP", "BOTTOM", "MIDDLE"],
        "align": ["LEFT", "RIGHT", "CENTER", "JUSTIFY", "CHAR"],
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
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # PARENT
    _row_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_row.rid"))
    _row: Mapped["Row"] = relationship(back_populates="entry")


class Tbody(Base, HasRows):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tbody"

    ATTRIBUTES = {
        "VALIGN": "valign",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Row": ("_rows", "A"),
    }
    ENUMS = {
        "valign": ["TOP", "MIDDLE", "BOTTOM"],
    }
    valign = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         _row


class Tgroup(Base, HasColspecs):
    # SIMPLE: Table == SR: False
    # P: ('Table', 'table')  --  C: ['Spanspec']
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
        "Colspec": ("colspecs", "A"),
        "Spanspec": ("spanspec", "A"),
        "Thead": ("thead", "R"),
        "Tfoot": ("tfoot", "R"),
        "Tbody": ("tbody", "R"),
    }
    ENUMS = {
        "align": ["LEFT", "RIGHT", "CENTER", "JUSTIFY", "CHAR"],
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
    # ARR
    # NO_PA         colspec
    # ARR
    # PARENT-OBJ
    spanspec: Mapped[list["Spanspec"]] = relationship(back_populates="tgroup")
    # REF
    thead_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("thead.rid"))
    thead: Mapped["Thead"] = relationship(single_parent=True)
    # REF
    tfoot_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tfoot.rid"))
    tfoot: Mapped["Tfoot"] = relationship(single_parent=True)
    # REF
    tbody_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbody.rid"))
    tbody: Mapped["Tbody"] = relationship(single_parent=True)
    # PARENT
    table_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("table.rid"))
    table: Mapped["Table"] = relationship(back_populates="tgroup")


class MsrQueryResultP2(
    Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes, HasTables
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_result_p_2"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table

    # N-I: MsrQueryP2

    # N-I: Topic2


class MsrQueryResultTopic2(Base, HasTopic2s):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_result_topic_2"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Topic2": ("topic_2s", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         topic_2

    # N-I: MsrQueryTopic2


class Objectives(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "objectives"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Rights(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "rights"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)

    # N-I: Prms

    # N-I: Prm


class Cond(Base, HasPs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "cond"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p


class Abs(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "_abs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class Tol(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "tol"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class Min(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "_min"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class Typ(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "typ"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class Max(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "_max"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class Unit(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "unit"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class Text(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "text"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub

    # N-I: PrmChar


class MsrQueryResultP1(
    Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes, HasTables, HasPrmss
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_result_p_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms

    # N-I: MsrQueryP1

    # N-I: Topic1


class MsrQueryResultTopic1(Base, HasTopic1s):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_result_topic_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Topic1": ("topic_1s", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         topic_1

    # N-I: MsrQueryTopic1

    # N-I: Chapter


class MsrQueryResultChapter(Base, HasChapters):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_query_result_chapter"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Chapter": ("chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         chapter

    # N-I: MsrQueryChapter


class Guarantee(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "guarantee"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Maintenance(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "maintenance"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Samples(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Sample']
    __tablename__ = "samples"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sample": ("sample", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sample: Mapped[list["Sample"]] = relationship(back_populates="samples")


class AddSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "add_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class ContractAspects(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "contract_aspects"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Rights": ("rights", "R"),
        "Guarantee": ("guarantee", "R"),
        "Maintenance": ("maintenance", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    rights_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("rights.rid"))
    rights: Mapped["Rights"] = relationship(single_parent=True)
    # REF
    guarantee_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("guarantee.rid"))
    guarantee: Mapped["Guarantee"] = relationship(single_parent=True)
    # REF
    maintenance_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("maintenance.rid"))
    maintenance: Mapped["Maintenance"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class SampleSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sample_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Samples": ("samples", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    samples_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("samples.rid"))
    samples: Mapped["Samples"] = relationship(single_parent=True)


class VariantChars(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['VariantChar']
    __tablename__ = "variant_chars"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantChar": ("variant_char", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    variant_char: Mapped[list["VariantChar"]] = relationship(back_populates="variant_chars")


class VariantDefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['VariantDef']
    __tablename__ = "variant_defs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantDef": ("variant_def", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    variant_def: Mapped[list["VariantDef"]] = relationship(back_populates="variant_defs")


class VariantSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "variant_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "VariantChars": ("variant_chars", "R"),
        "VariantDefs": ("variant_defs", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    variant_chars_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_chars.rid"))
    variant_chars: Mapped["VariantChars"] = relationship(single_parent=True)
    # REF
    variant_defs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_defs.rid"))
    variant_defs: Mapped["VariantDefs"] = relationship(single_parent=True)


class Sample(Base):
    # SIMPLE: Samples == SR: False
    # P: ('Samples', 'samples')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    f_child_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)
    # PARENT
    samples_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("samples.rid"))
    samples: Mapped["Samples"] = relationship(back_populates="sample")


class DemarcationOtherProjects(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "demarcation_other_projects"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class ParallelDesigns(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "parallel_designs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Code(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "code"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class VariantChar(Base):
    # SIMPLE: VariantChars == SR: False
    # P: ('VariantChars', 'variant_chars')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Code": ("code", "R"),
    }
    ENUMS = {
        "_type": ["NEW-PART-NUMBER", "NO-NEW-PART-NUMBER"],
    }
    _type = StdString()
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    code_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("code.rid"))
    code: Mapped["Code"] = relationship(single_parent=True)
    # PARENT
    variant_chars_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_chars.rid"))
    variant_chars: Mapped["VariantChars"] = relationship(back_populates="variant_char")


class IntegrationCapability(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "integration_capability"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class VariantCharAssigns(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['VariantCharAssign']
    __tablename__ = "variant_char_assigns"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantCharAssign": ("variant_char_assign", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    variant_char_assign: Mapped[list["VariantCharAssign"]] = relationship(back_populates="variant_char_assigns")


class VariantDef(Base):
    # SIMPLE: VariantDefs == SR: False
    # P: ('VariantDefs', 'variant_defs')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Code": ("code", "R"),
        "VariantCharAssigns": ("variant_char_assigns", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    code_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("code.rid"))
    code: Mapped["Code"] = relationship(single_parent=True)
    # REF
    variant_char_assigns_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_char_assigns.rid"))
    variant_char_assigns: Mapped["VariantCharAssigns"] = relationship(single_parent=True)
    # PARENT
    variant_defs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_defs.rid"))
    variant_defs: Mapped["VariantDefs"] = relationship(back_populates="variant_def")


class VariantCharRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class VariantCharValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "variant_char_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Value": ("value", "R"),
        "Code": ("code", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("value.rid"))
    value: Mapped["Value"] = relationship(single_parent=True)
    # REF
    code_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("code.rid"))
    code: Mapped["Code"] = relationship(single_parent=True)


class VariantCharAssign(Base):
    # SIMPLE: VariantCharAssigns == SR: False
    # P: ('VariantCharAssigns', 'variant_char_assigns')  --  C: []
    __tablename__ = "variant_char_assign"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "VariantCharRef": ("variant_char_ref", "R"),
        "VariantCharValue": ("variant_char_value", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    variant_char_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_char_ref.rid"))
    variant_char_ref: Mapped["VariantCharRef"] = relationship(single_parent=True)
    # REF
    variant_char_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_char_value.rid"))
    variant_char_value: Mapped["VariantCharValue"] = relationship(single_parent=True)
    # PARENT
    variant_char_assigns_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_char_assigns.rid"))
    variant_char_assigns: Mapped["VariantCharAssigns"] = relationship(back_populates="variant_char_assign")


class AcceptanceCond(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "acceptance_cond"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class ProjectSchedule(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "project_schedule"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class PurchasingCond(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "purchasing_cond"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Protocols(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "protocols"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class DirHandOverDocData(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "dir_hand_over_doc_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class GeneralProjectData(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_project_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SystemOverview": ("system_overview", "R"),
        "ReasonOrder": ("reason_order", "R"),
        "Objectives": ("objectives", "R"),
        "ContractAspects": ("contract_aspects", "R"),
        "SampleSpec": ("sample_spec", "R"),
        "VariantSpec": ("variant_spec", "R"),
        "DemarcationOtherProjects": ("demarcation_other_projects", "R"),
        "ParallelDesigns": ("parallel_designs", "R"),
        "IntegrationCapability": ("integration_capability", "R"),
        "AcceptanceCond": ("acceptance_cond", "R"),
        "ProjectSchedule": ("project_schedule", "R"),
        "PurchasingCond": ("purchasing_cond", "R"),
        "Protocols": ("protocols", "R"),
        "DirHandOverDocData": ("dir_hand_over_doc_data", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    system_overview_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("system_overview.rid"))
    system_overview: Mapped["SystemOverview"] = relationship(single_parent=True)
    # REF
    reason_order_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("reason_order.rid"))
    reason_order: Mapped["ReasonOrder"] = relationship(single_parent=True)
    # REF
    objectives_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("objectives.rid"))
    objectives: Mapped["Objectives"] = relationship(single_parent=True)
    # REF
    contract_aspects_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("contract_aspects.rid"))
    contract_aspects: Mapped["ContractAspects"] = relationship(single_parent=True)
    # REF
    sample_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sample_spec.rid"))
    sample_spec: Mapped["SampleSpec"] = relationship(single_parent=True)
    # REF
    variant_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("variant_spec.rid"))
    variant_spec: Mapped["VariantSpec"] = relationship(single_parent=True)
    # REF
    demarcation_other_projects_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("demarcation_other_projects.rid"))
    demarcation_other_projects: Mapped["DemarcationOtherProjects"] = relationship(single_parent=True)
    # REF
    parallel_designs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("parallel_designs.rid"))
    parallel_designs: Mapped["ParallelDesigns"] = relationship(single_parent=True)
    # REF
    integration_capability_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("integration_capability.rid"))
    integration_capability: Mapped["IntegrationCapability"] = relationship(single_parent=True)
    # REF
    acceptance_cond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("acceptance_cond.rid"))
    acceptance_cond: Mapped["AcceptanceCond"] = relationship(single_parent=True)
    # REF
    project_schedule_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("project_schedule.rid"))
    project_schedule: Mapped["ProjectSchedule"] = relationship(single_parent=True)
    # REF
    purchasing_cond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("purchasing_cond.rid"))
    purchasing_cond: Mapped["PurchasingCond"] = relationship(single_parent=True)
    # REF
    protocols_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("protocols.rid"))
    protocols: Mapped["Protocols"] = relationship(single_parent=True)
    # REF
    dir_hand_over_doc_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("dir_hand_over_doc_data.rid"))
    dir_hand_over_doc_data: Mapped["DirHandOverDocData"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class Project(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "project"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "Desc": ("_desc", "R"),
        "Companies": ("companies", "R"),
        "GeneralProjectData": ("general_project_data", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    companies_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("companies.rid"))
    companies: Mapped["Companies"] = relationship(single_parent=True)
    # REF
    general_project_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_project_data.rid"))
    general_project_data: Mapped["GeneralProjectData"] = relationship(single_parent=True)


class ProjectData(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "project_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "OverallProject": ("overall_project", "R"),
        "Project": ("project", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    overall_project_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("overall_project.rid"))
    overall_project: Mapped["OverallProject"] = relationship(single_parent=True)
    # REF
    project_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("project.rid"))
    project: Mapped["Project"] = relationship(single_parent=True)


class SwSystems(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwSystem']
    __tablename__ = "sw_systems"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystem": ("sw_system", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_system: Mapped[list["SwSystem"]] = relationship(back_populates="sw_systems")


class Requirements(Base, HasRequirements):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Requirement": ("requirements", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         requirement


class FunctionOverview(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "function_overview"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FreeInfo(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "free_info"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class PrmRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['PrmRef']
    __tablename__ = "prm_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "PrmRef": ("prm_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    prm_ref: Mapped[list["PrmRef"]] = relationship(back_populates="prm_refs")


class KeyData(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "key_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "FreeInfo": ("free_info", "R"),
        "PrmRefs": ("prm_refs", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    free_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("free_info.rid"))
    free_info: Mapped["FreeInfo"] = relationship(single_parent=True)
    # REF
    prm_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("prm_refs.rid"))
    prm_refs: Mapped["PrmRefs"] = relationship(single_parent=True)


class ProductDemarcation(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "product_demarcation"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class PrmRef(Base):
    # SIMPLE: PrmRefs == SR: False
    # P: ('PrmRefs', 'prm_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    prm_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("prm_refs.rid"))
    prm_refs: Mapped["PrmRefs"] = relationship(back_populates="prm_ref")


class SimilarProducts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "similar_products"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class OperatingEnv(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "operating_env"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class UsefulLifePrms(Base, HasPrms):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Availability', 'LifeTime', 'OperatingTime']
    __tablename__ = "useful_life_prms"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Availability": ("availability", "A"),
        "LifeTime": ("life_time", "A"),
        "OperatingTime": ("operating_time", "A"),
        "Prm": ("prms", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    availability: Mapped[list["Availability"]] = relationship(back_populates="useful_life_prms")
    # ARR
    # PARENT-OBJ
    life_time: Mapped[list["LifeTime"]] = relationship(back_populates="useful_life_prms")
    # ARR
    # PARENT-OBJ
    operating_time: Mapped[list["OperatingTime"]] = relationship(back_populates="useful_life_prms")
    # ARR
    # NO_PA         prm


class Ncoi3(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasMsrQueryP2s,
    HasTopic2s,
    HasMsrQueryTopic2s,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "ncoi_3"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "MsrQueryP2": ("msr_query_p_2s", "A"),
        "Topic2": ("topic_2s", "A"),
        "MsrQueryTopic2": ("msr_query_topic_2s", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         msr_query_p_2
    # ARR
    # NO_PA         topic_2
    # ARR
    # NO_PA         msr_query_topic_2


class ReliabilityPrms(Base, HasPrms):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Mtbf', 'Ppm']
    __tablename__ = "reliability_prms"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Mtbf": ("mtbf", "A"),
        "Ppm": ("ppm", "A"),
        "Prm": ("prms", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    mtbf: Mapped[list["Mtbf"]] = relationship(back_populates="reliability_prms")
    # ARR
    # PARENT-OBJ
    ppm: Mapped[list["Ppm"]] = relationship(back_populates="reliability_prms")
    # ARR
    # NO_PA         prm


class UsefulLife(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "useful_life"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "UsefulLifePrms": ("useful_life_prms", "R"),
        "Ncoi3": ("ncoi_3", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    useful_life_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("useful_life_prms.rid"))
    useful_life_prms: Mapped["UsefulLifePrms"] = relationship(single_parent=True)
    # REF
    ncoi_3_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_3.rid"))
    ncoi_3: Mapped["Ncoi3"] = relationship(single_parent=True)


class Availability(Base, HasPrmChars):
    # SIMPLE: UsefulLifePrms == SR: False
    # P: ('UsefulLifePrms', 'useful_life_prms')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "PrmChar": ("prm_chars", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # ARR
    # NO_PA         prm_char
    # PARENT
    useful_life_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("useful_life_prms.rid"))
    useful_life_prms: Mapped["UsefulLifePrms"] = relationship(back_populates="availability")


class LifeTime(Base, HasPrmChars):
    # SIMPLE: UsefulLifePrms == SR: False
    # P: ('UsefulLifePrms', 'useful_life_prms')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "PrmChar": ("prm_chars", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # ARR
    # NO_PA         prm_char
    # PARENT
    useful_life_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("useful_life_prms.rid"))
    useful_life_prms: Mapped["UsefulLifePrms"] = relationship(back_populates="life_time")


class OperatingTime(Base, HasPrmChars):
    # SIMPLE: UsefulLifePrms == SR: False
    # P: ('UsefulLifePrms', 'useful_life_prms')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "PrmChar": ("prm_chars", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # ARR
    # NO_PA         prm_char
    # PARENT
    useful_life_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("useful_life_prms.rid"))
    useful_life_prms: Mapped["UsefulLifePrms"] = relationship(back_populates="operating_time")


class Reliability(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "reliability"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "ReliabilityPrms": ("reliability_prms", "R"),
        "Ncoi3": ("ncoi_3", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    reliability_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("reliability_prms.rid"))
    reliability_prms: Mapped["ReliabilityPrms"] = relationship(single_parent=True)
    # REF
    ncoi_3_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_3.rid"))
    ncoi_3: Mapped["Ncoi3"] = relationship(single_parent=True)


class GeneralHardware(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_hardware"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "OperatingEnv": ("operating_env", "R"),
        "UsefulLife": ("useful_life", "R"),
        "Reliability": ("reliability", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    operating_env_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("operating_env.rid"))
    operating_env: Mapped["OperatingEnv"] = relationship(single_parent=True)
    # REF
    useful_life_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("useful_life.rid"))
    useful_life: Mapped["UsefulLife"] = relationship(single_parent=True)
    # REF
    reliability_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("reliability.rid"))
    reliability: Mapped["Reliability"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class NormativeReference(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "normative_reference"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Mtbf(Base, HasPrmChars):
    # SIMPLE: ReliabilityPrms == SR: False
    # P: ('ReliabilityPrms', 'reliability_prms')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "PrmChar": ("prm_chars", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # ARR
    # NO_PA         prm_char
    # PARENT
    reliability_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("reliability_prms.rid"))
    reliability_prms: Mapped["ReliabilityPrms"] = relationship(back_populates="mtbf")


class Ppm(Base, HasPrmChars):
    # SIMPLE: ReliabilityPrms == SR: False
    # P: ('ReliabilityPrms', 'reliability_prms')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "PrmChar": ("prm_chars", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # ARR
    # NO_PA         prm_char
    # PARENT
    reliability_prms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("reliability_prms.rid"))
    reliability_prms: Mapped["ReliabilityPrms"] = relationship(back_populates="ppm")


class DataStructures(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "data_structures"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class DataDesc(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "data_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class RestrictionsByHardware(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "restrictions_by_hardware"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class StandardSwModules(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "standard_sw_modules"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class DesignRequirements(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "design_requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "NormativeReference": ("normative_reference", "R"),
        "RestrictionsByHardware": ("restrictions_by_hardware", "R"),
        "StandardSwModules": ("standard_sw_modules", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    normative_reference_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("normative_reference.rid"))
    normative_reference: Mapped["NormativeReference"] = relationship(single_parent=True)
    # REF
    restrictions_by_hardware_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("restrictions_by_hardware.rid"))
    restrictions_by_hardware: Mapped["RestrictionsByHardware"] = relationship(single_parent=True)
    # REF
    standard_sw_modules_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("standard_sw_modules.rid"))
    standard_sw_modules: Mapped["StandardSwModules"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class BinaryCompatibility(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "binary_compatibility"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class DataRequirements(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "data_requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "DataStructures": ("data_structures", "R"),
        "DataDesc": ("data_desc", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    data_structures_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("data_structures.rid"))
    data_structures: Mapped["DataStructures"] = relationship(single_parent=True)
    # REF
    data_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("data_desc.rid"))
    data_desc: Mapped["DataDesc"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class Extensibility(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "extensibility"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Compatibility(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "compatibility"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class GeneralSoftware(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_software"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "DesignRequirements": ("design_requirements", "R"),
        "DataRequirements": ("data_requirements", "R"),
        "BinaryCompatibility": ("binary_compatibility", "R"),
        "Extensibility": ("extensibility", "R"),
        "Compatibility": ("compatibility", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    design_requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("design_requirements.rid"))
    design_requirements: Mapped["DesignRequirements"] = relationship(single_parent=True)
    # REF
    data_requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("data_requirements.rid"))
    data_requirements: Mapped["DataRequirements"] = relationship(single_parent=True)
    # REF
    binary_compatibility_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("binary_compatibility.rid"))
    binary_compatibility: Mapped["BinaryCompatibility"] = relationship(single_parent=True)
    # REF
    extensibility_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("extensibility.rid"))
    extensibility: Mapped["Extensibility"] = relationship(single_parent=True)
    # REF
    compatibility_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("compatibility.rid"))
    compatibility: Mapped["Compatibility"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class UserInterface(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "user_interface"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class HardwareInterface(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "hardware_interface"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class InternalInterfaces(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "internal_interfaces"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class CommunicationInterface(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "communication_interface"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FlashProgramming(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "flash_programming"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class GeneralInterfaces(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_interfaces"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "UserInterface": ("user_interface", "R"),
        "HardwareInterface": ("hardware_interface", "R"),
        "InternalInterfaces": ("internal_interfaces", "R"),
        "CommunicationInterface": ("communication_interface", "R"),
        "FlashProgramming": ("flash_programming", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    user_interface_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("user_interface.rid"))
    user_interface: Mapped["UserInterface"] = relationship(single_parent=True)
    # REF
    hardware_interface_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("hardware_interface.rid"))
    hardware_interface: Mapped["HardwareInterface"] = relationship(single_parent=True)
    # REF
    internal_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("internal_interfaces.rid"))
    internal_interfaces: Mapped["InternalInterfaces"] = relationship(single_parent=True)
    # REF
    communication_interface_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("communication_interface.rid"))
    communication_interface: Mapped["CommunicationInterface"] = relationship(single_parent=True)
    # REF
    flash_programming_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("flash_programming.rid"))
    flash_programming: Mapped["FlashProgramming"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class Fmea(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "fmea"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FailSaveConcept(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "fail_save_concept"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class ReplacementValues(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "replacement_values"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FailureMem(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "failure_mem"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class SelfDiagnosis(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "self_diagnosis"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FailureManagement(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "failure_management"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Fmea": ("fmea", "R"),
        "FailSaveConcept": ("fail_save_concept", "R"),
        "ReplacementValues": ("replacement_values", "R"),
        "FailureMem": ("failure_mem", "R"),
        "SelfDiagnosis": ("self_diagnosis", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    fmea_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("fmea.rid"))
    fmea: Mapped["Fmea"] = relationship(single_parent=True)
    # REF
    fail_save_concept_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("fail_save_concept.rid"))
    fail_save_concept: Mapped["FailSaveConcept"] = relationship(single_parent=True)
    # REF
    replacement_values_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("replacement_values.rid"))
    replacement_values: Mapped["ReplacementValues"] = relationship(single_parent=True)
    # REF
    failure_mem_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("failure_mem.rid"))
    failure_mem: Mapped["FailureMem"] = relationship(single_parent=True)
    # REF
    self_diagnosis_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("self_diagnosis.rid"))
    self_diagnosis: Mapped["SelfDiagnosis"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class ResourceAllocation(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "resource_allocation"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Calibration(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "calibration"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Safety(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "safety"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Quality(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "quality"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class GeneralCond(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_cond"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class AddDesignDoc(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "add_design_doc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class DevelopmentProcessSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "development_process_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class GeneralProductData1(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_product_data_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "ProductDesc": ("product_desc", "R"),
        "FunctionOverview": ("function_overview", "R"),
        "KeyData": ("key_data", "R"),
        "ProductDemarcation": ("product_demarcation", "R"),
        "SimilarProducts": ("similar_products", "R"),
        "GeneralHardware": ("general_hardware", "R"),
        "GeneralSoftware": ("general_software", "R"),
        "GeneralInterfaces": ("general_interfaces", "R"),
        "FailureManagement": ("failure_management", "R"),
        "ResourceAllocation": ("resource_allocation", "R"),
        "Calibration": ("calibration", "R"),
        "Safety": ("safety", "R"),
        "Quality": ("quality", "R"),
        "Maintenance": ("maintenance", "R"),
        "GeneralCond": ("general_cond", "R"),
        "AddDesignDoc": ("add_design_doc", "R"),
        "DevelopmentProcessSpec": ("development_process_spec", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    product_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("product_desc.rid"))
    product_desc: Mapped["ProductDesc"] = relationship(single_parent=True)
    # REF
    function_overview_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("function_overview.rid"))
    function_overview: Mapped["FunctionOverview"] = relationship(single_parent=True)
    # REF
    key_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("key_data.rid"))
    key_data: Mapped["KeyData"] = relationship(single_parent=True)
    # REF
    product_demarcation_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("product_demarcation.rid"))
    product_demarcation: Mapped["ProductDemarcation"] = relationship(single_parent=True)
    # REF
    similar_products_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("similar_products.rid"))
    similar_products: Mapped["SimilarProducts"] = relationship(single_parent=True)
    # REF
    general_hardware_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_hardware.rid"))
    general_hardware: Mapped["GeneralHardware"] = relationship(single_parent=True)
    # REF
    general_software_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_software.rid"))
    general_software: Mapped["GeneralSoftware"] = relationship(single_parent=True)
    # REF
    general_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_interfaces.rid"))
    general_interfaces: Mapped["GeneralInterfaces"] = relationship(single_parent=True)
    # REF
    failure_management_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("failure_management.rid"))
    failure_management: Mapped["FailureManagement"] = relationship(single_parent=True)
    # REF
    resource_allocation_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("resource_allocation.rid"))
    resource_allocation: Mapped["ResourceAllocation"] = relationship(single_parent=True)
    # REF
    calibration_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("calibration.rid"))
    calibration: Mapped["Calibration"] = relationship(single_parent=True)
    # REF
    safety_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("safety.rid"))
    safety: Mapped["Safety"] = relationship(single_parent=True)
    # REF
    quality_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("quality.rid"))
    quality: Mapped["Quality"] = relationship(single_parent=True)
    # REF
    maintenance_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("maintenance.rid"))
    maintenance: Mapped["Maintenance"] = relationship(single_parent=True)
    # REF
    general_cond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_cond.rid"))
    general_cond: Mapped["GeneralCond"] = relationship(single_parent=True)
    # REF
    add_design_doc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_design_doc.rid"))
    add_design_doc: Mapped["AddDesignDoc"] = relationship(single_parent=True)
    # REF
    development_process_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("development_process_spec.rid"))
    development_process_spec: Mapped["DevelopmentProcessSpec"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class RequirementSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "requirement_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "Requirements": ("requirements", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("requirements.rid"))
    requirements: Mapped["Requirements"] = relationship(single_parent=True)


class Monitoring(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "monitoring"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class Diagnosis(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "diagnosis"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class RequirementBody(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "requirement_body"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class CriticalAspects(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "critical_aspects"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class TechnicalAspects(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "technical_aspects"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class RealtimeRequirements(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "realtime_requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class Risks(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "risks"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class RequirementsDependency(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "requirements_dependency"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class AddInfo(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "add_info"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter

    # N-I: Requirement


class Communication(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "communication"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class OperationalRequirements(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "operational_requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class FunctionalRequirements(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "functional_requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "RequirementSpec": ("requirement_spec", "R"),
        "Monitoring": ("monitoring", "R"),
        "Diagnosis": ("diagnosis", "R"),
        "Communication": ("communication", "R"),
        "OperationalRequirements": ("operational_requirements", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    requirement_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("requirement_spec.rid"))
    requirement_spec: Mapped["RequirementSpec"] = relationship(single_parent=True)
    # REF
    monitoring_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("monitoring.rid"))
    monitoring: Mapped["Monitoring"] = relationship(single_parent=True)
    # REF
    diagnosis_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("diagnosis.rid"))
    diagnosis: Mapped["Diagnosis"] = relationship(single_parent=True)
    # REF
    communication_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("communication.rid"))
    communication: Mapped["Communication"] = relationship(single_parent=True)
    # REF
    operational_requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("operational_requirements.rid"))
    operational_requirements: Mapped["OperationalRequirements"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class GeneralRequirements(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "general_requirements"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "GeneralProductData1": ("general_product_data_1", "R"),
        "FunctionalRequirements": ("functional_requirements", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    general_product_data_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_product_data_1.rid"))
    general_product_data_1: Mapped["GeneralProductData1"] = relationship(single_parent=True)
    # REF
    functional_requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("functional_requirements.rid"))
    functional_requirements: Mapped["FunctionalRequirements"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class SwMcInterfaceSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcInterface']
    __tablename__ = "sw_mc_interface_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwMcInterface": ("sw_mc_interface", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_mc_interface: Mapped[list["SwMcInterface"]] = relationship(back_populates="sw_mc_interface_spec")


class Overview(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "overview"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class SwTestSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_test_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class SwTasks(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwTask']
    __tablename__ = "sw_tasks"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwTask": ("sw_task", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_task: Mapped[list["SwTask"]] = relationship(back_populates="sw_tasks")


class SwTaskSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_task_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwTasks": ("sw_tasks", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_tasks_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_tasks.rid"))
    sw_tasks: Mapped["SwTasks"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class InterruptSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "interrupt_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class SwCseCode(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cse_code"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCseCodeFactor(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cse_code_factor"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRefreshTiming(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_refresh_timing"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCseCode": ("sw_cse_code", "R"),
        "SwCseCodeFactor": ("sw_cse_code_factor", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_cse_code_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cse_code.rid"))
    sw_cse_code: Mapped["SwCseCode"] = relationship(single_parent=True)
    # REF
    sw_cse_code_factor_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cse_code_factor.rid"))
    sw_cse_code_factor: Mapped["SwCseCodeFactor"] = relationship(single_parent=True)


class SwTask(Base):
    # SIMPLE: SwTasks == SR: False
    # P: ('SwTasks', 'sw_tasks')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwRefreshTiming": ("sw_refresh_timing", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_refresh_timing_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_refresh_timing.rid"))
    sw_refresh_timing: Mapped["SwRefreshTiming"] = relationship(single_parent=True)
    # PARENT
    sw_tasks_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_tasks.rid"))
    sw_tasks: Mapped["SwTasks"] = relationship(back_populates="sw_task")


class TimeDependency(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "time_dependency"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class SwArchitecture(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_architecture"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "Overview": ("overview", "R"),
        "SwTaskSpec": ("sw_task_spec", "R"),
        "InterruptSpec": ("interrupt_spec", "R"),
        "TimeDependency": ("time_dependency", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    overview_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("overview.rid"))
    overview: Mapped["Overview"] = relationship(single_parent=True)
    # REF
    sw_task_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_task_spec.rid"))
    sw_task_spec: Mapped["SwTaskSpec"] = relationship(single_parent=True)
    # REF
    interrupt_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("interrupt_spec.rid"))
    interrupt_spec: Mapped["InterruptSpec"] = relationship(single_parent=True)
    # REF
    time_dependency_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("time_dependency.rid"))
    time_dependency: Mapped["TimeDependency"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)


class SwUnits(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwUnit']
    __tablename__ = "sw_units"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwUnit": ("sw_unit", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_unit: Mapped[list["SwUnit"]] = relationship(back_populates="sw_units")


class SwComponents(Base, HasChapters):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwClass', 'SwFeature']
    __tablename__ = "sw_components"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Chapter": ("chapters", "A"),
        "SwClass": ("sw_class", "A"),
        "SwFeature": ("sw_feature", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         chapter
    # ARR
    # PARENT-OBJ
    sw_class: Mapped[list["SwClass"]] = relationship(back_populates="sw_components")
    # ARR
    # PARENT-OBJ
    sw_feature: Mapped[list["SwFeature"]] = relationship(back_populates="sw_components")


class SwTemplates(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwTemplate']
    __tablename__ = "sw_templates"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwTemplate": ("sw_template", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_template: Mapped[list["SwTemplate"]] = relationship(back_populates="sw_templates")


class SwUnitDisplay(Base, HasSups, HasSubs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_unit_display"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sup": ("sups", "A"),
        "Sub": ("subs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sup
    # ARR
    # NO_PA         sub


class SwUnitGradient(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_unit_gradient"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SiUnit(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_unit_offset"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwUnitConversionMethod(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_unit_conversion_method"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUnitGradient": ("sw_unit_gradient", "R"),
        "SwUnitOffset": ("sw_unit_offset", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_unit_gradient_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_gradient.rid"))
    sw_unit_gradient: Mapped["SwUnitGradient"] = relationship(single_parent=True)
    # REF
    sw_unit_offset_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_offset.rid"))
    sw_unit_offset: Mapped["SwUnitOffset"] = relationship(single_parent=True)


class SwUnitRef(Base):
    # SIMPLE: SwUnitRefs == SR: False
    # P: ('SwUnitRefs', 'sw_unit_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_unit_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_refs.rid"))
    sw_unit_refs: Mapped["SwUnitRefs"] = relationship(back_populates="sw_unit_ref")


class SwUnit(Base):
    # SIMPLE: SwUnits == SR: False
    # P: ('SwUnits', 'sw_units')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwUnitDisplay": ("sw_unit_display", "R"),
        "SwUnitConversionMethod": ("sw_unit_conversion_method", "R"),
        "SiUnit": ("si_unit", "R"),
        "SwUnitRef": ("sw_unit_ref", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_unit_display_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_display.rid"))
    sw_unit_display: Mapped["SwUnitDisplay"] = relationship(single_parent=True)
    # REF
    sw_unit_conversion_method_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_conversion_method.rid"))
    sw_unit_conversion_method: Mapped["SwUnitConversionMethod"] = relationship(single_parent=True)
    # REF
    si_unit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("si_unit.rid"))
    si_unit: Mapped["SiUnit"] = relationship(single_parent=True)
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_units_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_units.rid"))
    sw_units: Mapped["SwUnits"] = relationship(back_populates="sw_unit")


class SwVariables(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwVariable']
    __tablename__ = "sw_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwVariable": ("sw_variable", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_variable: Mapped[list["SwVariable"]] = relationship(back_populates="sw_variables")


class Annotations(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Annotation']
    __tablename__ = "annotations"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Annotation": ("annotation", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    annotation: Mapped[list["Annotation"]] = relationship(back_populates="annotations")


class SwAddrMethodRef(Base):
    # SIMPLE: SwAddrMethodRefs == SR: False
    # P: ('SwAddrMethodRefs', 'sw_addr_method_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_addr_method_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_method_refs.rid"))
    sw_addr_method_refs: Mapped["SwAddrMethodRefs"] = relationship(back_populates="sw_addr_method_ref")


class SwAliasName(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_alias_name"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class AnnotationOrigin(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "annotation_origin"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class AnnotationText(Base, HasPs, HasVerbatims):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "annotation_text"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim


class Annotation(Base):
    # SIMPLE: Annotations == SR: False
    # P: ('Annotations', 'annotations')  --  C: []
    __tablename__ = "annotation"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "AnnotationOrigin": ("annotation_origin", "R"),
        "AnnotationText": ("annotation_text", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    annotation_origin_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotation_origin.rid"))
    annotation_origin: Mapped["AnnotationOrigin"] = relationship(single_parent=True)
    # REF
    annotation_text_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotation_text.rid"))
    annotation_text: Mapped["AnnotationText"] = relationship(single_parent=True)
    # PARENT
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(back_populates="annotation")


class SwBaseTypeRef(Base):
    # SIMPLE: SwBaseTypeRefs == SR: False
    # P: ('SwBaseTypeRefs', 'sw_base_type_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_base_type_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_refs.rid"))
    sw_base_type_refs: Mapped["SwBaseTypeRefs"] = relationship(back_populates="sw_base_type_ref")


class BitPosition(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "bit_position"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class NumberOfBits(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "number_of_bits"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwBitRepresentation(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_bit_representation"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "BitPosition": ("bit_position", "R"),
        "NumberOfBits": ("number_of_bits", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    bit_position_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("bit_position.rid"))
    bit_position: Mapped["BitPosition"] = relationship(single_parent=True)
    # REF
    number_of_bits_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("number_of_bits.rid"))
    number_of_bits: Mapped["NumberOfBits"] = relationship(single_parent=True)


class SwCalibrationAccess(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calibration_access"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCalprmAxisSet(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCalprmAxis']
    __tablename__ = "sw_calprm_axis_set"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmAxis": ("sw_calprm_axis", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_calprm_axis: Mapped[list["SwCalprmAxis"]] = relationship(back_populates="sw_calprm_axis_set")


class SwCalprmNoEffectValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_no_effect_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwTemplateRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_axis_index"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwVariableRefs(Base, HasSwVariableRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variable_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref

    # N-I: SwCalprmRef

    # N-I: SwCompuMethodRef

    # N-I: SwVariableRef


class SwMaxAxisPoints(Base, HasSwSystemconstCodedRefs, HasSwSystemconstPhysRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_max_axis_points"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwSystemconstPhysRef": ("sw_systemconst_phys_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_systemconst_coded_ref
    # ARR
    # NO_PA         sw_systemconst_phys_ref


class SwMinAxisPoints(Base, HasSwSystemconstCodedRefs, HasSwSystemconstPhysRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_min_axis_points"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwSystemconstPhysRef": ("sw_systemconst_phys_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_systemconst_coded_ref
    # ARR
    # NO_PA         sw_systemconst_phys_ref

    # N-I: SwSystemconstCodedRef

    # N-I: SwSystemconstPhysRef


class SwDataConstrRef(Base):
    # SIMPLE: SwDataConstrRefs == SR: False
    # P: ('SwDataConstrRefs', 'sw_data_constr_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_data_constr_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr_refs.rid"))
    sw_data_constr_refs: Mapped["SwDataConstrRefs"] = relationship(back_populates="sw_data_constr_ref")


class SwAxisTypeRef(Base):
    # SIMPLE: SwAxisTypeRefs == SR: False
    # P: ('SwAxisTypeRefs', 'sw_axis_type_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_axis_type_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_type_refs.rid"))
    sw_axis_type_refs: Mapped["SwAxisTypeRefs"] = relationship(back_populates="sw_axis_type_ref")


class SwNumberOfAxisPoints(Base, HasSwSystemconstCodedRefs, HasSwSystemconstPhysRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_number_of_axis_points"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwSystemconstPhysRef": ("sw_systemconst_phys_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_systemconst_coded_ref
    # ARR
    # NO_PA         sw_systemconst_phys_ref


class SwGenericAxisParams(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwGenericAxisParam']
    __tablename__ = "sw_generic_axis_params"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwGenericAxisParam": ("sw_generic_axis_param", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_generic_axis_param: Mapped[list["SwGenericAxisParam"]] = relationship(back_populates="sw_generic_axis_params")


class SwValuesPhys(Base, HasVfs, HasVts, HasVhs, HasVs, HasVgs, HasSwInstanceRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_values_phys"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
        "Vt": ("vts", "A"),
        "Vh": ("vhs", "A"),
        "V": ("vs", "A"),
        "Vg": ("vgs", "A"),
        "SwInstanceRef": ("sw_instance_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf
    # ARR
    # NO_PA         vt
    # ARR
    # NO_PA         vh
    # ARR
    # NO_PA         v
    # ARR
    # NO_PA         vg
    # ARR
    # NO_PA         sw_instance_ref


class SwValuesCoded(Base, HasVfs, HasVts, HasVhs, HasVs, HasVgs, HasSwInstanceRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_values_coded"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
        "Vt": ("vts", "A"),
        "Vh": ("vhs", "A"),
        "V": ("vs", "A"),
        "Vg": ("vgs", "A"),
        "SwInstanceRef": ("sw_instance_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf
    # ARR
    # NO_PA         vt
    # ARR
    # NO_PA         vh
    # ARR
    # NO_PA         v
    # ARR
    # NO_PA         vg
    # ARR
    # NO_PA         sw_instance_ref


class SwGenericAxisParamTypeRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: SwGenericAxisParam

    # N-I: Vf


class SwAxisGeneric(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_axis_generic"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisTypeRef": ("sw_axis_type_ref", "R"),
        "SwNumberOfAxisPoints": ("sw_number_of_axis_points", "R"),
        "SwGenericAxisParams": ("sw_generic_axis_params", "R"),
        "SwValuesPhys": ("sw_values_phys", "R"),
        "SwValuesCoded": ("sw_values_coded", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_axis_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_type_ref.rid"))
    sw_axis_type_ref: Mapped["SwAxisTypeRef"] = relationship(single_parent=True)
    # REF
    sw_number_of_axis_points_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_number_of_axis_points.rid"))
    sw_number_of_axis_points: Mapped["SwNumberOfAxisPoints"] = relationship(single_parent=True)
    # REF
    sw_generic_axis_params_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_params.rid"))
    sw_generic_axis_params: Mapped["SwGenericAxisParams"] = relationship(single_parent=True)
    # REF
    sw_values_phys_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_phys.rid"))
    sw_values_phys: Mapped["SwValuesPhys"] = relationship(single_parent=True)
    # REF
    sw_values_coded_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_coded.rid"))
    sw_values_coded: Mapped["SwValuesCoded"] = relationship(single_parent=True)

    # N-I: Vt

    # N-I: Vh

    # N-I: V

    # N-I: Vg

    # N-I: SwInstanceRef


class SwAxisIndividual(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_axis_individual"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRefs": ("sw_variable_refs", "R"),
        "SwCompuMethodRef": ("sw_compu_method_ref", "R"),
        "SwUnitRef": ("sw_unit_ref", "R"),
        "SwBitRepresentation": ("sw_bit_representation", "R"),
        "SwMaxAxisPoints": ("sw_max_axis_points", "R"),
        "SwMinAxisPoints": ("sw_min_axis_points", "R"),
        "SwDataConstrRef": ("sw_data_constr_ref", "R"),
        "SwAxisGeneric": ("sw_axis_generic", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_refs.rid"))
    sw_variable_refs: Mapped["SwVariableRefs"] = relationship(single_parent=True)
    # REF
    sw_compu_method_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_method_ref.rid"))
    sw_compu_method_ref: Mapped["SwCompuMethodRef"] = relationship(single_parent=True)
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    sw_bit_representation_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_bit_representation.rid"))
    sw_bit_representation: Mapped["SwBitRepresentation"] = relationship(single_parent=True)
    # REF
    sw_max_axis_points_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_max_axis_points.rid"))
    sw_max_axis_points: Mapped["SwMaxAxisPoints"] = relationship(single_parent=True)
    # REF
    sw_min_axis_points_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_min_axis_points.rid"))
    sw_min_axis_points: Mapped["SwMinAxisPoints"] = relationship(single_parent=True)
    # REF
    sw_data_constr_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr_ref.rid"))
    sw_data_constr_ref: Mapped["SwDataConstrRef"] = relationship(single_parent=True)
    # REF
    sw_axis_generic_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_generic.rid"))
    sw_axis_generic: Mapped["SwAxisGeneric"] = relationship(single_parent=True)


class SwDisplayFormat(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_display_format"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwAxisGrouped(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_axis_grouped"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisIndex": ("sw_axis_index", "R"),
        "SwCalprmRef": ("sw_calprm_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_axis_index_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_index.rid"))
    sw_axis_index: Mapped["SwAxisIndex"] = relationship(single_parent=True)
    # REF
    sw_calprm_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_ref.rid"))
    sw_calprm_ref: Mapped["SwCalprmRef"] = relationship(single_parent=True)


class SwCalprmAxis(Base):
    # SIMPLE: SwCalprmAxisSet == SR: False
    # P: ('SwCalprmAxisSet', 'sw_calprm_axis_set')  --  C: []
    __tablename__ = "sw_calprm_axis"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisIndex": ("sw_axis_index", "R"),
        "SwAxisIndividual": ("sw_axis_individual", "R"),
        "SwAxisGrouped": ("sw_axis_grouped", "R"),
        "SwCalibrationAccess": ("sw_calibration_access", "R"),
        "SwDisplayFormat": ("sw_display_format", "R"),
        "SwBaseTypeRef": ("sw_base_type_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_axis_index_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_index.rid"))
    sw_axis_index: Mapped["SwAxisIndex"] = relationship(single_parent=True)
    # REF
    sw_axis_individual_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_individual.rid"))
    sw_axis_individual: Mapped["SwAxisIndividual"] = relationship(single_parent=True)
    # REF
    sw_axis_grouped_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_grouped.rid"))
    sw_axis_grouped: Mapped["SwAxisGrouped"] = relationship(single_parent=True)
    # REF
    sw_calibration_access_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calibration_access.rid"))
    sw_calibration_access: Mapped["SwCalibrationAccess"] = relationship(single_parent=True)
    # REF
    sw_display_format_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_display_format.rid"))
    sw_display_format: Mapped["SwDisplayFormat"] = relationship(single_parent=True)
    # REF
    sw_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_ref.rid"))
    sw_base_type_ref: Mapped["SwBaseTypeRef"] = relationship(single_parent=True)
    # PARENT
    sw_calprm_axis_set_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_axis_set.rid"))
    sw_calprm_axis_set: Mapped["SwCalprmAxisSet"] = relationship(back_populates="sw_calprm_axis")


class SwClassAttrImplRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_pointer"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwTemplateRef": ("sw_template_ref", "R"),
        "SwClassAttrImplRef": ("sw_class_attr_impl_ref", "R"),
        "Desc": ("_desc", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_template_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_template_ref.rid"))
    sw_template_ref: Mapped["SwTemplateRef"] = relationship(single_parent=True)
    # REF
    sw_class_attr_impl_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_attr_impl_ref.rid"))
    sw_class_attr_impl_ref: Mapped["SwClassAttrImplRef"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)


class SwCalprmTarget(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_target"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref.rid"))
    sw_variable_ref: Mapped["SwVariableRef"] = relationship(single_parent=True)


class SwCalprmMaxTextSize(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_max_text_size"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwFillCharacter(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_fill_character"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCalprmText(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_text"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmMaxTextSize": ("sw_calprm_max_text_size", "R"),
        "SwBaseTypeRef": ("sw_base_type_ref", "R"),
        "SwFillCharacter": ("sw_fill_character", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_calprm_max_text_size_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_max_text_size.rid"))
    sw_calprm_max_text_size: Mapped["SwCalprmMaxTextSize"] = relationship(single_parent=True)
    # REF
    sw_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_ref.rid"))
    sw_base_type_ref: Mapped["SwBaseTypeRef"] = relationship(single_parent=True)
    # REF
    sw_fill_character_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_fill_character.rid"))
    sw_fill_character: Mapped["SwFillCharacter"] = relationship(single_parent=True)


class SwCalprmValueAxisLabels(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Label']
    __tablename__ = "sw_calprm_value_axis_labels"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    label: Mapped[list["Label"]] = relationship(back_populates="sw_calprm_value_axis_labels")


class SwCodeSyntaxRef(Base):
    # SIMPLE: SwCodeSyntaxRefs == SR: False
    # P: ('SwCodeSyntaxRefs', 'sw_code_syntax_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_code_syntax_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_code_syntax_refs.rid"))
    sw_code_syntax_refs: Mapped["SwCodeSyntaxRefs"] = relationship(back_populates="sw_code_syntax_ref")


class SwComparisonVariables(Base, HasSwVariableRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_comparison_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref


class SwDataDependencyFormula(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_data_dependency_formula"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwDataDependencyArgs(Base, HasSwVariableRefs, HasSwSystemconstCodedRefs, HasSwCalprmRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_data_dependency_args"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwCalprmRef": ("sw_calprm_refs", "A"),
        "SwVariableRef": ("sw_variable_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_systemconst_coded_ref
    # ARR
    # NO_PA         sw_calprm_ref
    # ARR
    # NO_PA         sw_variable_ref


class SwDataDependency(Base):
    # SIMPLE: SwRelatedConstrs == SR: False
    # P: ('SwRelatedConstrs', 'sw_related_constrs')  --  C: []
    __tablename__ = "sw_data_dependency"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Desc": ("_desc", "R"),
        "SwDataDependencyFormula": ("sw_data_dependency_formula", "R"),
        "SwDataDependencyArgs": ("sw_data_dependency_args", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    sw_data_dependency_formula_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_dependency_formula.rid"))
    sw_data_dependency_formula: Mapped["SwDataDependencyFormula"] = relationship(single_parent=True)
    # REF
    sw_data_dependency_args_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_dependency_args.rid"))
    sw_data_dependency_args: Mapped["SwDataDependencyArgs"] = relationship(single_parent=True)
    # PARENT
    sw_related_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_related_constrs.rid"))
    sw_related_constrs: Mapped["SwRelatedConstrs"] = relationship(back_populates="sw_data_dependency")


class SwHostVariable(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_host_variable"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref.rid"))
    sw_variable_ref: Mapped["SwVariableRef"] = relationship(single_parent=True)


class SwImplPolicy(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_impl_policy"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwIntendedResolution(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_intended_resolution"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwInterpolationMethod(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_interpolation_method"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwIsVirtual(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_is_virtual"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcBaseTypeRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: SwRecordLayoutRef


class SwTaskRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variable_kind"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwVarInitValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_var_init_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwVarNotAvlValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_var_not_avl_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwVcdCriterionRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwVcdCriterionRef']
    __tablename__ = "sw_vcd_criterion_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterionRef": ("sw_vcd_criterion_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_vcd_criterion_ref: Mapped[list["SwVcdCriterionRef"]] = relationship(back_populates="sw_vcd_criterion_refs")


class SwDataDefProps(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_data_def_props"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Annotations": ("annotations", "R"),
        "SwAddrMethodRef": ("sw_addr_method_ref", "R"),
        "SwAliasName": ("sw_alias_name", "R"),
        "SwBaseTypeRef": ("sw_base_type_ref", "R"),
        "SwBitRepresentation": ("sw_bit_representation", "R"),
        "SwCalibrationAccess": ("sw_calibration_access", "R"),
        "SwCalprmAxisSet": ("sw_calprm_axis_set", "R"),
        "SwCalprmNoEffectValue": ("sw_calprm_no_effect_value", "R"),
        "SwCalprmPointer": ("sw_calprm_pointer", "R"),
        "SwCalprmTarget": ("sw_calprm_target", "R"),
        "SwCalprmText": ("sw_calprm_text", "R"),
        "SwCalprmValueAxisLabels": ("sw_calprm_value_axis_labels", "R"),
        "SwCodeSyntaxRef": ("sw_code_syntax_ref", "R"),
        "SwComparisonVariables": ("sw_comparison_variables", "R"),
        "SwCompuMethodRef": ("sw_compu_method_ref", "R"),
        "SwDataConstrRef": ("sw_data_constr_ref", "R"),
        "SwDataDependency": ("sw_data_dependency", "R"),
        "SwDisplayFormat": ("sw_display_format", "R"),
        "SwHostVariable": ("sw_host_variable", "R"),
        "SwImplPolicy": ("sw_impl_policy", "R"),
        "SwIntendedResolution": ("sw_intended_resolution", "R"),
        "SwInterpolationMethod": ("sw_interpolation_method", "R"),
        "SwIsVirtual": ("sw_is_virtual", "R"),
        "SwMcBaseTypeRef": ("sw_mc_base_type_ref", "R"),
        "SwRecordLayoutRef": ("sw_record_layout_ref", "R"),
        "SwRefreshTiming": ("sw_refresh_timing", "R"),
        "SwTaskRef": ("sw_task_ref", "R"),
        "SwTemplateRef": ("sw_template_ref", "R"),
        "SwUnitRef": ("sw_unit_ref", "R"),
        "SwVariableKind": ("sw_variable_kind", "R"),
        "SwVarInitValue": ("sw_var_init_value", "R"),
        "SwVarNotAvlValue": ("sw_var_not_avl_value", "R"),
        "SwVcdCriterionRefs": ("sw_vcd_criterion_refs", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    sw_addr_method_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_method_ref.rid"))
    sw_addr_method_ref: Mapped["SwAddrMethodRef"] = relationship(single_parent=True)
    # REF
    sw_alias_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_alias_name.rid"))
    sw_alias_name: Mapped["SwAliasName"] = relationship(single_parent=True)
    # REF
    sw_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_ref.rid"))
    sw_base_type_ref: Mapped["SwBaseTypeRef"] = relationship(single_parent=True)
    # REF
    sw_bit_representation_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_bit_representation.rid"))
    sw_bit_representation: Mapped["SwBitRepresentation"] = relationship(single_parent=True)
    # REF
    sw_calibration_access_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calibration_access.rid"))
    sw_calibration_access: Mapped["SwCalibrationAccess"] = relationship(single_parent=True)
    # REF
    sw_calprm_axis_set_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_axis_set.rid"))
    sw_calprm_axis_set: Mapped["SwCalprmAxisSet"] = relationship(single_parent=True)
    # REF
    sw_calprm_no_effect_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_no_effect_value.rid"))
    sw_calprm_no_effect_value: Mapped["SwCalprmNoEffectValue"] = relationship(single_parent=True)
    # REF
    sw_calprm_pointer_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_pointer.rid"))
    sw_calprm_pointer: Mapped["SwCalprmPointer"] = relationship(single_parent=True)
    # REF
    sw_calprm_target_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_target.rid"))
    sw_calprm_target: Mapped["SwCalprmTarget"] = relationship(single_parent=True)
    # REF
    sw_calprm_text_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_text.rid"))
    sw_calprm_text: Mapped["SwCalprmText"] = relationship(single_parent=True)
    # REF
    sw_calprm_value_axis_labels_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_value_axis_labels.rid"))
    sw_calprm_value_axis_labels: Mapped["SwCalprmValueAxisLabels"] = relationship(single_parent=True)
    # REF
    sw_code_syntax_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_code_syntax_ref.rid"))
    sw_code_syntax_ref: Mapped["SwCodeSyntaxRef"] = relationship(single_parent=True)
    # REF
    sw_comparison_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_comparison_variables.rid"))
    sw_comparison_variables: Mapped["SwComparisonVariables"] = relationship(single_parent=True)
    # REF
    sw_compu_method_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_method_ref.rid"))
    sw_compu_method_ref: Mapped["SwCompuMethodRef"] = relationship(single_parent=True)
    # REF
    sw_data_constr_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr_ref.rid"))
    sw_data_constr_ref: Mapped["SwDataConstrRef"] = relationship(single_parent=True)
    # REF
    sw_data_dependency_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_dependency.rid"))
    sw_data_dependency: Mapped["SwDataDependency"] = relationship(single_parent=True)
    # REF
    sw_display_format_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_display_format.rid"))
    sw_display_format: Mapped["SwDisplayFormat"] = relationship(single_parent=True)
    # REF
    sw_host_variable_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_host_variable.rid"))
    sw_host_variable: Mapped["SwHostVariable"] = relationship(single_parent=True)
    # REF
    sw_impl_policy_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_impl_policy.rid"))
    sw_impl_policy: Mapped["SwImplPolicy"] = relationship(single_parent=True)
    # REF
    sw_intended_resolution_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_intended_resolution.rid"))
    sw_intended_resolution: Mapped["SwIntendedResolution"] = relationship(single_parent=True)
    # REF
    sw_interpolation_method_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_interpolation_method.rid"))
    sw_interpolation_method: Mapped["SwInterpolationMethod"] = relationship(single_parent=True)
    # REF
    sw_is_virtual_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_is_virtual.rid"))
    sw_is_virtual: Mapped["SwIsVirtual"] = relationship(single_parent=True)
    # REF
    sw_mc_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_base_type_ref.rid"))
    sw_mc_base_type_ref: Mapped["SwMcBaseTypeRef"] = relationship(single_parent=True)
    # REF
    sw_record_layout_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_ref.rid"))
    sw_record_layout_ref: Mapped["SwRecordLayoutRef"] = relationship(single_parent=True)
    # REF
    sw_refresh_timing_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_refresh_timing.rid"))
    sw_refresh_timing: Mapped["SwRefreshTiming"] = relationship(single_parent=True)
    # REF
    sw_task_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_task_ref.rid"))
    sw_task_ref: Mapped["SwTaskRef"] = relationship(single_parent=True)
    # REF
    sw_template_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_template_ref.rid"))
    sw_template_ref: Mapped["SwTemplateRef"] = relationship(single_parent=True)
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    sw_variable_kind_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_kind.rid"))
    sw_variable_kind: Mapped["SwVariableKind"] = relationship(single_parent=True)
    # REF
    sw_var_init_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_var_init_value.rid"))
    sw_var_init_value: Mapped["SwVarInitValue"] = relationship(single_parent=True)
    # REF
    sw_var_not_avl_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_var_not_avl_value.rid"))
    sw_var_not_avl_value: Mapped["SwVarNotAvlValue"] = relationship(single_parent=True)
    # REF
    sw_vcd_criterion_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criterion_refs.rid"))
    sw_vcd_criterion_refs: Mapped["SwVcdCriterionRefs"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwTemplate(Base):
    # SIMPLE: SwTemplates == SR: False
    # P: ('SwTemplates', 'sw_templates')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # PARENT
    sw_templates_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_templates.rid"))
    sw_templates: Mapped["SwTemplates"] = relationship(back_populates="sw_template")


class SwVcdCriterionRef(Base):
    # SIMPLE: SwVcdCriterionRefs == SR: False
    # P: ('SwVcdCriterionRefs', 'sw_vcd_criterion_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_vcd_criterion_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criterion_refs.rid"))
    sw_vcd_criterion_refs: Mapped["SwVcdCriterionRefs"] = relationship(back_populates="sw_vcd_criterion_ref")


class SwCalprms(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCalprm']
    __tablename__ = "sw_calprms"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwCalprm": ("sw_calprm", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_calprm: Mapped[list["SwCalprm"]] = relationship(back_populates="sw_calprms")


class SwArraysize(Base, HasVfs, HasVs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_arraysize"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "V": ("vs", "A"),
        "Vf": ("vfs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         v
    # ARR
    # NO_PA         vf


class SwVariable(Base):
    # SIMPLE: SwVariables == SR: False
    # P: ('SwVariables', 'sw_variables')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
        "SwVariables": ("sw_variables", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    ENUMS = {
        "calibration": ["CALIBRATION", "NO-CALIBRATION", "NOT-IN-MC-SYSTEM"],
    }
    calibration = StdString()
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # REF
    sw_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables.rid"))
    sw_variables: Mapped["SwVariables"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables.rid"))
    sw_variables: Mapped["SwVariables"] = relationship(back_populates="sw_variable")


class SwSystemconsts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwSystemconst']
    __tablename__ = "sw_systemconsts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconst": ("sw_systemconst", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_systemconst: Mapped[list["SwSystemconst"]] = relationship(back_populates="sw_systemconsts")


class SwCalprm(Base):
    # SIMPLE: SwCalprms == SR: False
    # P: ('SwCalprms', 'sw_calprms')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
        "SwCalprms": ("sw_calprms", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # REF
    sw_calprms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprms.rid"))
    sw_calprms: Mapped["SwCalprms"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_calprms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprms.rid"))
    sw_calprms: Mapped["SwCalprms"] = relationship(back_populates="sw_calprm")


class SwClassInstances(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwClassInstance']
    __tablename__ = "sw_class_instances"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstance": ("sw_class_instance", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_class_instance: Mapped[list["SwClassInstance"]] = relationship(back_populates="sw_class_instances")


class SwSystemconst(Base):
    # SIMPLE: SwSystemconsts == SR: False
    # P: ('SwSystemconsts', 'sw_systemconsts')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwValuesPhys": ("sw_values_phys", "R"),
        "SwValuesCoded": ("sw_values_coded", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_values_phys_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_phys.rid"))
    sw_values_phys: Mapped["SwValuesPhys"] = relationship(single_parent=True)
    # REF
    sw_values_coded_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_coded.rid"))
    sw_values_coded: Mapped["SwValuesCoded"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # PARENT
    sw_systemconsts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconsts.rid"))
    sw_systemconsts: Mapped["SwSystemconsts"] = relationship(back_populates="sw_systemconst")


class SwCompuMethods(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCompuMethod']
    __tablename__ = "sw_compu_methods"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwCompuMethod": ("sw_compu_method", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_compu_method: Mapped[list["SwCompuMethod"]] = relationship(back_populates="sw_compu_methods")


class SwClassRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwClassInstances == SR: False
    # P: ('SwClassInstances', 'sw_class_instances')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwClassRef": ("sw_class_ref", "R"),
        "SwClassAttrImplRef": ("sw_class_attr_impl_ref", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_class_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_ref.rid"))
    sw_class_ref: Mapped["SwClassRef"] = relationship(single_parent=True)
    # REF
    sw_class_attr_impl_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_attr_impl_ref.rid"))
    sw_class_attr_impl_ref: Mapped["SwClassAttrImplRef"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_instances.rid"))
    sw_class_instances: Mapped["SwClassInstances"] = relationship(back_populates="sw_class_instance")


class SwAddrMethods(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAddrMethod']
    __tablename__ = "sw_addr_methods"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwAddrMethod": ("sw_addr_method", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_addr_method: Mapped[list["SwAddrMethod"]] = relationship(back_populates="sw_addr_methods")


class SwPhysConstrs1(Base, HasSwScaleConstrs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_phys_constrs_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwScaleConstr": ("sw_scale_constrs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_scale_constr


class SwInternalConstrs1(Base, HasSwScaleConstrs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_internal_constrs_1"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwScaleConstr": ("sw_scale_constrs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_scale_constr


class LowerLimit(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "lower_limit"

    ATTRIBUTES = {
        "INTERVAL-TYPE": "interval_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    ENUMS = {
        "interval_type": ["OPEN", "CLOSED"],
    }
    TERMINAL = True
    interval_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class UpperLimit(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "upper_limit"

    ATTRIBUTES = {
        "INTERVAL-TYPE": "interval_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    ENUMS = {
        "interval_type": ["OPEN", "CLOSED"],
    }
    TERMINAL = True
    interval_type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: SwScaleConstr


class SwCompuIdentity(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_identity"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCompuScales(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCompuScale']
    __tablename__ = "sw_compu_scales"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuScale": ("sw_compu_scale", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_compu_scale: Mapped[list["SwCompuScale"]] = relationship(back_populates="sw_compu_scales")


class SwCompuDefaultValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_default_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCompuInternalToPhys(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_internal_to_phys"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuScales": ("sw_compu_scales", "R"),
        "SwCompuDefaultValue": ("sw_compu_default_value", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_compu_scales_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_scales.rid"))
    sw_compu_scales: Mapped["SwCompuScales"] = relationship(single_parent=True)
    # REF
    sw_compu_default_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_default_value.rid"))
    sw_compu_default_value: Mapped["SwCompuDefaultValue"] = relationship(single_parent=True)


class CIdentifier(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "c_identifier"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCompuInverseValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_inverse_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vf", "R"),
        "V": ("v", "R"),
        "Vt": ("vt", "R"),
        "Vh": ("vh", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    vf_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vf.rid"))
    vf: Mapped["Vf"] = relationship(single_parent=True)
    # REF
    v_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("v.rid"))
    v: Mapped["V"] = relationship(single_parent=True)
    # REF
    vt_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vt.rid"))
    vt: Mapped["Vt"] = relationship(single_parent=True)
    # REF
    vh_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vh.rid"))
    vh: Mapped["Vh"] = relationship(single_parent=True)


class SwCompuConst(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_const"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vf", "R"),
        "V": ("v", "R"),
        "Vt": ("vt", "R"),
        "Vh": ("vh", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    vf_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vf.rid"))
    vf: Mapped["Vf"] = relationship(single_parent=True)
    # REF
    v_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("v.rid"))
    v: Mapped["V"] = relationship(single_parent=True)
    # REF
    vt_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vt.rid"))
    vt: Mapped["Vt"] = relationship(single_parent=True)
    # REF
    vh_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vh.rid"))
    vh: Mapped["Vh"] = relationship(single_parent=True)


class SwCompuNumerator(Base, HasVfs, HasVs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_numerator"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
        "V": ("vs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf
    # ARR
    # NO_PA         v


class SwCompuProgramCode(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    lang_subset = StdString()
    used_libs = StdString()
    program_lang = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCompuDenominator(Base, HasVfs, HasVs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_denominator"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
        "V": ("vs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf
    # ARR
    # NO_PA         v


class SwCompuRationalCoeffs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_rational_coeffs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuNumerator": ("sw_compu_numerator", "R"),
        "SwCompuDenominator": ("sw_compu_denominator", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_compu_numerator_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_numerator.rid"))
    sw_compu_numerator: Mapped["SwCompuNumerator"] = relationship(single_parent=True)
    # REF
    sw_compu_denominator_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_denominator.rid"))
    sw_compu_denominator: Mapped["SwCompuDenominator"] = relationship(single_parent=True)


class SwCompuGenericMath(Base, HasSwSystemconstCodedRefs, HasSwSystemconstPhysRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_generic_math"

    ATTRIBUTES = {
        "LEVEL": "level",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwSystemconstPhysRef": ("sw_systemconst_phys_refs", "A"),
    }
    level = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_systemconst_coded_ref
    # ARR
    # NO_PA         sw_systemconst_phys_ref


class SwCompuScale(Base):
    # SIMPLE: SwCompuScales == SR: False
    # P: ('SwCompuScales', 'sw_compu_scales')  --  C: []
    __tablename__ = "sw_compu_scale"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CIdentifier": ("c_identifier", "R"),
        "Desc": ("_desc", "R"),
        "LowerLimit": ("lower_limit", "R"),
        "UpperLimit": ("upper_limit", "R"),
        "SwCompuInverseValue": ("sw_compu_inverse_value", "R"),
        "SwCompuConst": ("sw_compu_const", "R"),
        "SwCompuRationalCoeffs": ("sw_compu_rational_coeffs", "R"),
        "SwCompuProgramCode": ("sw_compu_program_code", "R"),
        "SwCompuGenericMath": ("sw_compu_generic_math", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    c_identifier_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("c_identifier.rid"))
    c_identifier: Mapped["CIdentifier"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    lower_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("lower_limit.rid"))
    lower_limit: Mapped["LowerLimit"] = relationship(single_parent=True)
    # REF
    upper_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("upper_limit.rid"))
    upper_limit: Mapped["UpperLimit"] = relationship(single_parent=True)
    # REF
    sw_compu_inverse_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_inverse_value.rid"))
    sw_compu_inverse_value: Mapped["SwCompuInverseValue"] = relationship(single_parent=True)
    # REF
    sw_compu_const_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_const.rid"))
    sw_compu_const: Mapped["SwCompuConst"] = relationship(single_parent=True)
    # REF
    sw_compu_rational_coeffs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_rational_coeffs.rid"))
    sw_compu_rational_coeffs: Mapped["SwCompuRationalCoeffs"] = relationship(single_parent=True)
    # REF
    sw_compu_program_code_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_program_code.rid"))
    sw_compu_program_code: Mapped["SwCompuProgramCode"] = relationship(single_parent=True)
    # REF
    sw_compu_generic_math_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_generic_math.rid"))
    sw_compu_generic_math: Mapped["SwCompuGenericMath"] = relationship(single_parent=True)
    # PARENT
    sw_compu_scales_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_scales.rid"))
    sw_compu_scales: Mapped["SwCompuScales"] = relationship(back_populates="sw_compu_scale")


class SwCompuPhysToInternal(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_phys_to_internal"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuScales": ("sw_compu_scales", "R"),
        "SwCompuDefaultValue": ("sw_compu_default_value", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_compu_scales_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_scales.rid"))
    sw_compu_scales: Mapped["SwCompuScales"] = relationship(single_parent=True)
    # REF
    sw_compu_default_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_default_value.rid"))
    sw_compu_default_value: Mapped["SwCompuDefaultValue"] = relationship(single_parent=True)


class SwCompuMethod(Base):
    # SIMPLE: SwCompuMethods == SR: False
    # P: ('SwCompuMethods', 'sw_compu_methods')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwDisplayFormat": ("sw_display_format", "R"),
        "SwUnitRef": ("sw_unit_ref", "R"),
        "SwDataConstrRef": ("sw_data_constr_ref", "R"),
        "SwPhysConstrs1": ("sw_phys_constrs_1", "R"),
        "SwInternalConstrs1": ("sw_internal_constrs_1", "R"),
        "SwCompuIdentity": ("sw_compu_identity", "R"),
        "SwCompuPhysToInternal": ("sw_compu_phys_to_internal", "R"),
        "SwCompuInternalToPhys": ("sw_compu_internal_to_phys", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_display_format_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_display_format.rid"))
    sw_display_format: Mapped["SwDisplayFormat"] = relationship(single_parent=True)
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    sw_data_constr_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr_ref.rid"))
    sw_data_constr_ref: Mapped["SwDataConstrRef"] = relationship(single_parent=True)
    # REF
    sw_phys_constrs_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_phys_constrs_1.rid"))
    sw_phys_constrs_1: Mapped["SwPhysConstrs1"] = relationship(single_parent=True)
    # REF
    sw_internal_constrs_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_internal_constrs_1.rid"))
    sw_internal_constrs_1: Mapped["SwInternalConstrs1"] = relationship(single_parent=True)
    # REF
    sw_compu_identity_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_identity.rid"))
    sw_compu_identity: Mapped["SwCompuIdentity"] = relationship(single_parent=True)
    # REF
    sw_compu_phys_to_internal_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_phys_to_internal.rid"))
    sw_compu_phys_to_internal: Mapped["SwCompuPhysToInternal"] = relationship(single_parent=True)
    # REF
    sw_compu_internal_to_phys_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_internal_to_phys.rid"))
    sw_compu_internal_to_phys: Mapped["SwCompuInternalToPhys"] = relationship(single_parent=True)
    # PARENT
    sw_compu_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_methods.rid"))
    sw_compu_methods: Mapped["SwCompuMethods"] = relationship(back_populates="sw_compu_method")


class SwRecordLayouts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwRecordLayout']
    __tablename__ = "sw_record_layouts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwRecordLayout": ("sw_record_layout", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_record_layout: Mapped[list["SwRecordLayout"]] = relationship(back_populates="sw_record_layouts")


class SwCpuMemSegRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwAddrMethodDesc(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_addr_method_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwAddrMethod(Base):
    # SIMPLE: SwAddrMethods == SR: False
    # P: ('SwAddrMethods', 'sw_addr_methods')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwCpuMemSegRef": ("sw_cpu_mem_seg_ref", "R"),
        "SwAddrMethodDesc": ("sw_addr_method_desc", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_cpu_mem_seg_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_mem_seg_ref.rid"))
    sw_cpu_mem_seg_ref: Mapped["SwCpuMemSegRef"] = relationship(single_parent=True)
    # REF
    sw_addr_method_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_method_desc.rid"))
    sw_addr_method_desc: Mapped["SwAddrMethodDesc"] = relationship(single_parent=True)
    # PARENT
    sw_addr_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_methods.rid"))
    sw_addr_methods: Mapped["SwAddrMethods"] = relationship(back_populates="sw_addr_method")


class SwCodeSyntaxes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCodeSyntax']
    __tablename__ = "sw_code_syntaxes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwCodeSyntax": ("sw_code_syntax", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_code_syntax: Mapped[list["SwCodeSyntax"]] = relationship(back_populates="sw_code_syntaxes")


class SwRecordLayout(Base, HasSwRecordLayoutGroups):
    # SIMPLE: SwRecordLayouts == SR: False
    # P: ('SwRecordLayouts', 'sw_record_layouts')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwRecordLayoutGroup": ("sw_record_layout_groups", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sw_record_layout_group
    # PARENT
    sw_record_layouts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layouts.rid"))
    sw_record_layouts: Mapped["SwRecordLayouts"] = relationship(back_populates="sw_record_layout")


class SwRecordLayoutGroupAxis(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_group_axis"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutGroupIndex(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_group_index"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutGroupFrom(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_group_from"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutGroupTo(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_group_to"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutGroupStep(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_group_step"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutComponent(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_component"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()

    # N-I: SwRecordLayoutGroup


class SwRecordLayoutVAxis(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_v_axis"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutVProp(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_v_prop"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutVIndex(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_v_index"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutVFixValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_v_fix_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRecordLayoutV(Base):
    # SIMPLE: SwRecordLayoutGroup == SR: False
    # P: ('SwRecordLayoutGroup', 'sw_record_layout_group')  --  C: []
    __tablename__ = "sw_record_layout_v"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Desc": ("_desc", "R"),
        "SwBaseTypeRef": ("sw_base_type_ref", "R"),
        "SwRecordLayoutVAxis": ("sw_record_layout_v_axis", "R"),
        "SwRecordLayoutVProp": ("sw_record_layout_v_prop", "R"),
        "SwRecordLayoutVIndex": ("sw_record_layout_v_index", "R"),
        "SwGenericAxisParamTypeRef": ("sw_generic_axis_param_type_ref", "R"),
        "SwRecordLayoutVFixValue": ("sw_record_layout_v_fix_value", "R"),
        "SwRecordLayoutRef": ("sw_record_layout_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    sw_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_ref.rid"))
    sw_base_type_ref: Mapped["SwBaseTypeRef"] = relationship(single_parent=True)
    # REF
    sw_record_layout_v_axis_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_v_axis.rid"))
    sw_record_layout_v_axis: Mapped["SwRecordLayoutVAxis"] = relationship(single_parent=True)
    # REF
    sw_record_layout_v_prop_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_v_prop.rid"))
    sw_record_layout_v_prop: Mapped["SwRecordLayoutVProp"] = relationship(single_parent=True)
    # REF
    sw_record_layout_v_index_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_v_index.rid"))
    sw_record_layout_v_index: Mapped["SwRecordLayoutVIndex"] = relationship(single_parent=True)
    # REF
    sw_generic_axis_param_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_generic_axis_param_type_ref.rid")
    )
    sw_generic_axis_param_type_ref: Mapped["SwGenericAxisParamTypeRef"] = relationship(single_parent=True)
    # REF
    sw_record_layout_v_fix_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_v_fix_value.rid"))
    sw_record_layout_v_fix_value: Mapped["SwRecordLayoutVFixValue"] = relationship(single_parent=True)
    # REF
    sw_record_layout_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_ref.rid"))
    sw_record_layout_ref: Mapped["SwRecordLayoutRef"] = relationship(single_parent=True)
    # PARENT
    sw_record_layout_group_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_group.rid"))
    sw_record_layout_group: Mapped["SwRecordLayoutGroup"] = relationship(back_populates="sw_record_layout_v")


class SwBaseTypes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwBase']
    __tablename__ = "sw_base_types"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwBaseType": ("sw_base_type", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sw_base_type
    sw_base_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type.rid"))
    sw_base_type: Mapped[list["SwBaseType"]] = relationship()


class SwCodeSyntaxDesc(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_code_syntax_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwCodeSyntax(Base):
    # SIMPLE: SwCodeSyntaxes == SR: False
    # P: ('SwCodeSyntaxes', 'sw_code_syntaxes')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwCodeSyntaxDesc": ("sw_code_syntax_desc", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_code_syntax_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_code_syntax_desc.rid"))
    sw_code_syntax_desc: Mapped["SwCodeSyntaxDesc"] = relationship(single_parent=True)
    # PARENT
    sw_code_syntaxes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_code_syntaxes.rid"))
    sw_code_syntaxes: Mapped["SwCodeSyntaxes"] = relationship(back_populates="sw_code_syntax")


class SwDataConstrs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwDataConstr']
    __tablename__ = "sw_data_constrs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwDataConstr": ("sw_data_constr", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_data_constr: Mapped[list["SwDataConstr"]] = relationship(back_populates="sw_data_constrs")


class SwBaseTypeSize(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_base_type_size"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCodedType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_coded_type"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemAlignment(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mem_alignment"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class ByteOrder(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "byte_order"

    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    ENUMS = {
        "_type": ["MOST-SIGNIFICANT-BYTE-FIRST", "MOST-SIGNIFICANT-BYTE-LAST"],
    }
    TERMINAL = True
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwBaseType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwBaseTypeSize": ("sw_base_type_size", "R"),
        "SwCodedType": ("sw_coded_type", "R"),
        "SwMemAlignment": ("sw_mem_alignment", "R"),
        "ByteOrder": ("byte_order", "R"),
        "SwBaseTypeRef": ("sw_base_type_ref", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_base_type_size_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_size.rid"))
    sw_base_type_size: Mapped["SwBaseTypeSize"] = relationship(single_parent=True)
    # REF
    sw_coded_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_coded_type.rid"))
    sw_coded_type: Mapped["SwCodedType"] = relationship(single_parent=True)
    # REF
    sw_mem_alignment_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_alignment.rid"))
    sw_mem_alignment: Mapped["SwMemAlignment"] = relationship(single_parent=True)
    # REF
    byte_order_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("byte_order.rid"))
    byte_order: Mapped["ByteOrder"] = relationship(single_parent=True)
    # REF
    sw_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_ref.rid"))
    sw_base_type_ref: Mapped["SwBaseTypeRef"] = relationship(single_parent=True)


class SwAxisTypes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAxis']
    __tablename__ = "sw_axis_types"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwAxisType": ("sw_axis_type", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sw_axis_type
    sw_axis_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_type.rid"))
    sw_axis_type: Mapped[list["SwAxisType"]] = relationship()


class SwConstrObjects(Base, HasSwVariableRefs, HasSwCalprmRefs, HasSwCompuMethodRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_constr_objects"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
        "SwCalprmRef": ("sw_calprm_refs", "A"),
        "SwCompuMethodRef": ("sw_compu_method_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref
    # ARR
    # NO_PA         sw_calprm_ref
    # ARR
    # NO_PA         sw_compu_method_ref


class SwDataConstr(Base):
    # SIMPLE: SwDataConstrs == SR: False
    # P: ('SwDataConstrs', 'sw_data_constrs')  --  C: ['SwDataConstrRule']
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwConstrObjects": ("sw_constr_objects", "R"),
        "SwDataConstrRule": ("sw_data_constr_rule", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_constr_objects_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_constr_objects.rid"))
    sw_constr_objects: Mapped["SwConstrObjects"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_data_constr_rule: Mapped[list["SwDataConstrRule"]] = relationship(back_populates="sw_data_constr")
    # PARENT
    sw_data_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constrs.rid"))
    sw_data_constrs: Mapped["SwDataConstrs"] = relationship(back_populates="sw_data_constr")


class SwConstrLevel(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_constr_level"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMaxGradient(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_max_gradient"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwScaleConstrs(Base, HasSwScaleConstrs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_scale_constrs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwScaleConstr": ("sw_scale_constrs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_scale_constr


class SwMaxDiff(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_max_diff"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMonotony(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_monotony"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwRelatedConstrs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwDataDependency']
    __tablename__ = "sw_related_constrs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwDataDependency": ("sw_data_dependency", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_data_dependency: Mapped[list["SwDataDependency"]] = relationship(back_populates="sw_related_constrs")


class SwInternalConstrs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_internal_constrs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LowerLimit": ("lower_limit", "R"),
        "UpperLimit": ("upper_limit", "R"),
        "SwScaleConstrs": ("sw_scale_constrs", "R"),
        "SwMaxDiff": ("sw_max_diff", "R"),
        "SwMonotony": ("sw_monotony", "R"),
        "SwRelatedConstrs": ("sw_related_constrs", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    lower_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("lower_limit.rid"))
    lower_limit: Mapped["LowerLimit"] = relationship(single_parent=True)
    # REF
    upper_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("upper_limit.rid"))
    upper_limit: Mapped["UpperLimit"] = relationship(single_parent=True)
    # REF
    sw_scale_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_scale_constrs.rid"))
    sw_scale_constrs: Mapped["SwScaleConstrs"] = relationship(single_parent=True)
    # REF
    sw_max_diff_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_max_diff.rid"))
    sw_max_diff: Mapped["SwMaxDiff"] = relationship(single_parent=True)
    # REF
    sw_monotony_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_monotony.rid"))
    sw_monotony: Mapped["SwMonotony"] = relationship(single_parent=True)
    # REF
    sw_related_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_related_constrs.rid"))
    sw_related_constrs: Mapped["SwRelatedConstrs"] = relationship(single_parent=True)


class SwPhysConstrs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_phys_constrs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "LowerLimit": ("lower_limit", "R"),
        "UpperLimit": ("upper_limit", "R"),
        "SwScaleConstrs": ("sw_scale_constrs", "R"),
        "SwUnitRef": ("sw_unit_ref", "R"),
        "SwMaxDiff": ("sw_max_diff", "R"),
        "SwMonotony": ("sw_monotony", "R"),
        "SwRelatedConstrs": ("sw_related_constrs", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    lower_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("lower_limit.rid"))
    lower_limit: Mapped["LowerLimit"] = relationship(single_parent=True)
    # REF
    upper_limit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("upper_limit.rid"))
    upper_limit: Mapped["UpperLimit"] = relationship(single_parent=True)
    # REF
    sw_scale_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_scale_constrs.rid"))
    sw_scale_constrs: Mapped["SwScaleConstrs"] = relationship(single_parent=True)
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    sw_max_diff_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_max_diff.rid"))
    sw_max_diff: Mapped["SwMaxDiff"] = relationship(single_parent=True)
    # REF
    sw_monotony_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_monotony.rid"))
    sw_monotony: Mapped["SwMonotony"] = relationship(single_parent=True)
    # REF
    sw_related_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_related_constrs.rid"))
    sw_related_constrs: Mapped["SwRelatedConstrs"] = relationship(single_parent=True)


class SwDataConstrRule(Base):
    # SIMPLE: SwDataConstr == SR: False
    # P: ('SwDataConstr', 'sw_data_constr')  --  C: []
    __tablename__ = "sw_data_constr_rule"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwConstrLevel": ("sw_constr_level", "R"),
        "SwMaxGradient": ("sw_max_gradient", "R"),
        "SwPhysConstrs": ("sw_phys_constrs", "R"),
        "SwInternalConstrs": ("sw_internal_constrs", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_constr_level_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_constr_level.rid"))
    sw_constr_level: Mapped["SwConstrLevel"] = relationship(single_parent=True)
    # REF
    sw_max_gradient_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_max_gradient.rid"))
    sw_max_gradient: Mapped["SwMaxGradient"] = relationship(single_parent=True)
    # REF
    sw_phys_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_phys_constrs.rid"))
    sw_phys_constrs: Mapped["SwPhysConstrs"] = relationship(single_parent=True)
    # REF
    sw_internal_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_internal_constrs.rid"))
    sw_internal_constrs: Mapped["SwInternalConstrs"] = relationship(single_parent=True)
    # PARENT
    sw_data_constr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr.rid"))
    sw_data_constr: Mapped["SwDataConstr"] = relationship(back_populates="sw_data_constr_rule")


class SwDataDictionarySpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_data_dictionary_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "Desc": ("_desc", "R"),
        "SwUnits": ("sw_units", "R"),
        "SwTemplates": ("sw_templates", "R"),
        "SwVariables": ("sw_variables", "R"),
        "SwCalprms": ("sw_calprms", "R"),
        "SwSystemconsts": ("sw_systemconsts", "R"),
        "SwClassInstances": ("sw_class_instances", "R"),
        "SwCompuMethods": ("sw_compu_methods", "R"),
        "SwAddrMethods": ("sw_addr_methods", "R"),
        "SwRecordLayouts": ("sw_record_layouts", "R"),
        "SwCodeSyntaxes": ("sw_code_syntaxes", "R"),
        "SwBaseTypes": ("sw_base_types", "R"),
        "SwDataConstrs": ("sw_data_constrs", "R"),
        "SwAxisTypes": ("sw_axis_types", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    sw_units_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_units.rid"))
    sw_units: Mapped["SwUnits"] = relationship(single_parent=True)
    # REF
    sw_templates_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_templates.rid"))
    sw_templates: Mapped["SwTemplates"] = relationship(single_parent=True)
    # REF
    sw_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables.rid"))
    sw_variables: Mapped["SwVariables"] = relationship(single_parent=True)
    # REF
    sw_calprms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprms.rid"))
    sw_calprms: Mapped["SwCalprms"] = relationship(single_parent=True)
    # REF
    sw_systemconsts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconsts.rid"))
    sw_systemconsts: Mapped["SwSystemconsts"] = relationship(single_parent=True)
    # REF
    sw_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_instances.rid"))
    sw_class_instances: Mapped["SwClassInstances"] = relationship(single_parent=True)
    # REF
    sw_compu_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_methods.rid"))
    sw_compu_methods: Mapped["SwCompuMethods"] = relationship(single_parent=True)
    # REF
    sw_addr_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_methods.rid"))
    sw_addr_methods: Mapped["SwAddrMethods"] = relationship(single_parent=True)
    # REF
    sw_record_layouts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layouts.rid"))
    sw_record_layouts: Mapped["SwRecordLayouts"] = relationship(single_parent=True)
    # REF
    sw_code_syntaxes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_code_syntaxes.rid"))
    sw_code_syntaxes: Mapped["SwCodeSyntaxes"] = relationship(single_parent=True)
    # REF
    sw_base_types_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_types.rid"))
    sw_base_types: Mapped["SwBaseTypes"] = relationship(single_parent=True)
    # REF
    sw_data_constrs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constrs.rid"))
    sw_data_constrs: Mapped["SwDataConstrs"] = relationship(single_parent=True)
    # REF
    sw_axis_types_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_types.rid"))
    sw_axis_types: Mapped["SwAxisTypes"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwGenericAxisDesc(Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_generic_axis_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note


class SwGenericAxisParamTypes(Base, HasSwGenericAxisParams):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_generic_axis_param_types"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwGenericAxisParamType": ("sw_generic_axis_param_type", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_generic_axis_param_type
    sw_generic_axis_param_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_param_type.rid"))
    sw_generic_axis_param_type: Mapped[list["SwGenericAxisParamType"]] = relationship()


class SwAxisType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwGenericAxisDesc": ("sw_generic_axis_desc", "R"),
        "SwGenericAxisParamTypes": ("sw_generic_axis_param_types", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_generic_axis_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_desc.rid"))
    sw_generic_axis_desc: Mapped["SwGenericAxisDesc"] = relationship(single_parent=True)
    # REF
    sw_generic_axis_param_types_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_param_types.rid"))
    sw_generic_axis_param_types: Mapped["SwGenericAxisParamTypes"] = relationship(single_parent=True)


class SwGenericAxisParamType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwDataConstrRef": ("sw_data_constr_ref", "R"),
        "SwGenericAxisParamType": ("sw_generic_axis_param_type", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_data_constr_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr_ref.rid"))
    sw_data_constr_ref: Mapped["SwDataConstrRef"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sw_generic_axis_param_type
    sw_generic_axis_param_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_generic_axis_param_type.rid"))
    sw_generic_axis_param_type: Mapped[list["SwGenericAxisParamType"]] = relationship()


class SwInstanceSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwInstanceTree']
    __tablename__ = "sw_instance_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwInstanceTree": ("sw_instance_tree", "A"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_instance_tree: Mapped[list["SwInstanceTree"]] = relationship(back_populates="sw_instance_spec")
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwRootFeatures(Base, HasSwFeatureRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_root_features"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRef": ("sw_feature_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_feature_ref


class SwFeatureDef(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_def"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwFeatureDesc(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwFulfils(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['FunctionRef', 'RequirementRef']
    __tablename__ = "sw_fulfils"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "FunctionRef": ("function_ref", "A"),
        "RequirementRef": ("requirement_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    function_ref: Mapped[list["FunctionRef"]] = relationship(back_populates="sw_fulfils")
    # ARR
    # PARENT-OBJ
    requirement_ref: Mapped[list["RequirementRef"]] = relationship(back_populates="sw_fulfils")


class SwClassMethods(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwClassMethod']
    __tablename__ = "sw_class_methods"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassMethod": ("sw_class_method", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_class_method: Mapped[list["SwClassMethod"]] = relationship(back_populates="sw_class_methods")


class FunctionRef(Base):
    # SIMPLE: SwFulfils == SR: False
    # P: ('SwFulfils', 'sw_fulfils')  --  C: []
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
    ELEMENTS = {}
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
    # PARENT
    sw_fulfils_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_fulfils.rid"))
    sw_fulfils: Mapped["SwFulfils"] = relationship(back_populates="function_ref")


class RequirementRef(Base):
    # SIMPLE: SwFulfils == SR: False
    # P: ('SwFulfils', 'sw_fulfils')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_fulfils_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_fulfils.rid"))
    sw_fulfils: Mapped["SwFulfils"] = relationship(back_populates="requirement_ref")


class SwVariablePrototypes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwVariableProto']
    __tablename__ = "sw_variable_prototypes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablePrototype": ("sw_variable_prototype", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_prototype
    sw_variable_prototype_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_prototype.rid"))
    sw_variable_prototype: Mapped[list["SwVariablePrototype"]] = relationship()


class ShortLabel(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "short_label"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwClassMethodReturn(Base, HasPs, HasVerbatims, HasFigures, HasFormulas, HasLists, HasDefLists, HasLabeledLists, HasNotes):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_class_method_return"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note


class SwClassMethod(Base):
    # SIMPLE: SwClassMethods == SR: False
    # P: ('SwClassMethods', 'sw_class_methods')  --  C: ['SwClassMethodArg']
    __tablename__ = "sw_class_method"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "ShortLabel": ("short_label", "R"),
        "Desc": ("_desc", "R"),
        "SwClassMethodReturn": ("sw_class_method_return", "R"),
        "SwClassMethodArg": ("sw_class_method_arg", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    short_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_label.rid"))
    short_label: Mapped["ShortLabel"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    sw_class_method_return_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_method_return.rid"))
    sw_class_method_return: Mapped["SwClassMethodReturn"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_class_method_arg: Mapped[list["SwClassMethodArg"]] = relationship(back_populates="sw_class_method")
    # PARENT
    sw_class_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_methods.rid"))
    sw_class_methods: Mapped["SwClassMethods"] = relationship(back_populates="sw_class_method")


class SwClassMethodArg(Base):
    # SIMPLE: SwClassMethod == SR: False
    # P: ('SwClassMethod', 'sw_class_method')  --  C: []
    __tablename__ = "sw_class_method_arg"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "ShortLabel": ("short_label", "R"),
        "Remark": ("remark", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    short_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_label.rid"))
    short_label: Mapped["ShortLabel"] = relationship(single_parent=True)
    # REF
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)
    # PARENT
    sw_class_method_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_method.rid"))
    sw_class_method: Mapped["SwClassMethod"] = relationship(back_populates="sw_class_method_arg")


class SwClassAttrImpls(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwClassAttrImpl']
    __tablename__ = "sw_class_attr_impls"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassAttrImpl": ("sw_class_attr_impl", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_class_attr_impl: Mapped[list["SwClassAttrImpl"]] = relationship(back_populates="sw_class_attr_impls")


class SwCalprmPrototypes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCalprmProto']
    __tablename__ = "sw_calprm_prototypes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmPrototype": ("sw_calprm_prototype", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_calprm_prototype
    sw_calprm_prototype_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_prototype.rid"))
    sw_calprm_prototype: Mapped[list["SwCalprmPrototype"]] = relationship()


class SwSyscond(Base, HasSwSystemconstCodedRefs, HasSwSystemconstPhysRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_syscond"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstCodedRef": ("sw_systemconst_coded_refs", "A"),
        "SwSystemconstPhysRef": ("sw_systemconst_phys_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_systemconst_coded_ref
    # ARR
    # NO_PA         sw_systemconst_phys_ref


class SwVariablePrototype(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwUnitRef": ("sw_unit_ref", "R"),
        "SwSyscond": ("sw_syscond", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    sw_syscond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_syscond.rid"))
    sw_syscond: Mapped["SwSyscond"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwClassPrototypes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwClassProto']
    __tablename__ = "sw_class_prototypes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassPrototype": ("sw_class_prototype", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_class_prototype
    sw_class_prototype_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_prototype.rid"))
    sw_class_prototype: Mapped[list["SwClassPrototype"]] = relationship()


class SwCalprmPrototype(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwSyscond": ("sw_syscond", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_syscond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_syscond.rid"))
    sw_syscond: Mapped["SwSyscond"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwClassAttr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_class_attr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablePrototypes": ("sw_variable_prototypes", "R"),
        "SwCalprmPrototypes": ("sw_calprm_prototypes", "R"),
        "SwClassPrototypes": ("sw_class_prototypes", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_prototypes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_prototypes.rid"))
    sw_variable_prototypes: Mapped["SwVariablePrototypes"] = relationship(single_parent=True)
    # REF
    sw_calprm_prototypes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_prototypes.rid"))
    sw_calprm_prototypes: Mapped["SwCalprmPrototypes"] = relationship(single_parent=True)
    # REF
    sw_class_prototypes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_prototypes.rid"))
    sw_class_prototypes: Mapped["SwClassPrototypes"] = relationship(single_parent=True)


class SwClassPrototype(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwClassRef": ("sw_class_ref", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwSyscond": ("sw_syscond", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_class_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_ref.rid"))
    sw_class_ref: Mapped["SwClassRef"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_syscond_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_syscond.rid"))
    sw_syscond: Mapped["SwSyscond"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwVariablesRead(Base, HasSwVariableRefs, HasSwVariableRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variables_read"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
        "SwVariableRefSyscond": ("sw_variable_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref
    # ARR
    # NO_PA         sw_variable_ref_syscond


class SwVariableImpls(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwVariableImpl']
    __tablename__ = "sw_variable_impls"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableImpl": ("sw_variable_impl", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_variable_impl: Mapped[list["SwVariableImpl"]] = relationship(back_populates="sw_variable_impls")


class SwCalprmImpls(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCalprmImpl']
    __tablename__ = "sw_calprm_impls"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmImpl": ("sw_calprm_impl", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_calprm_impl: Mapped[list["SwCalprmImpl"]] = relationship(back_populates="sw_calprm_impls")


class SwVariablePrototypeRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwVariableImpls == SR: False
    # P: ('SwVariableImpls', 'sw_variable_impls')  --  C: []
    __tablename__ = "sw_variable_impl"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablePrototypeRef": ("sw_variable_prototype_ref", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_prototype_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_prototype_ref.rid"))
    sw_variable_prototype_ref: Mapped["SwVariablePrototypeRef"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # PARENT
    sw_variable_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_impls.rid"))
    sw_variable_impls: Mapped["SwVariableImpls"] = relationship(back_populates="sw_variable_impl")


class SwClassImpls(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwClassImpl']
    __tablename__ = "sw_class_impls"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassImpl": ("sw_class_impl", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_class_impl: Mapped[list["SwClassImpl"]] = relationship(back_populates="sw_class_impls")


class SwCalprmPrototypeRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwCalprmImpls == SR: False
    # P: ('SwCalprmImpls', 'sw_calprm_impls')  --  C: []
    __tablename__ = "sw_calprm_impl"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmPrototypeRef": ("sw_calprm_prototype_ref", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_calprm_prototype_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_prototype_ref.rid"))
    sw_calprm_prototype_ref: Mapped["SwCalprmPrototypeRef"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # PARENT
    sw_calprm_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_impls.rid"))
    sw_calprm_impls: Mapped["SwCalprmImpls"] = relationship(back_populates="sw_calprm_impl")


class SwClassAttrImpl(Base):
    # SIMPLE: SwClassAttrImpls == SR: False
    # P: ('SwClassAttrImpls', 'sw_class_attr_impls')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
        "SwVariableImpls": ("sw_variable_impls", "R"),
        "SwCalprmImpls": ("sw_calprm_impls", "R"),
        "SwClassImpls": ("sw_class_impls", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # REF
    sw_variable_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_impls.rid"))
    sw_variable_impls: Mapped["SwVariableImpls"] = relationship(single_parent=True)
    # REF
    sw_calprm_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_impls.rid"))
    sw_calprm_impls: Mapped["SwCalprmImpls"] = relationship(single_parent=True)
    # REF
    sw_class_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_impls.rid"))
    sw_class_impls: Mapped["SwClassImpls"] = relationship(single_parent=True)
    # PARENT
    sw_class_attr_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_attr_impls.rid"))
    sw_class_attr_impls: Mapped["SwClassAttrImpls"] = relationship(back_populates="sw_class_attr_impl")


class SwClassPrototypeRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwClassImpls == SR: False
    # P: ('SwClassImpls', 'sw_class_impls')  --  C: []
    __tablename__ = "sw_class_impl"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassPrototypeRef": ("sw_class_prototype_ref", "R"),
        "SwClassAttrImplRef": ("sw_class_attr_impl_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_class_prototype_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_prototype_ref.rid"))
    sw_class_prototype_ref: Mapped["SwClassPrototypeRef"] = relationship(single_parent=True)
    # REF
    sw_class_attr_impl_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_attr_impl_ref.rid"))
    sw_class_attr_impl_ref: Mapped["SwClassAttrImplRef"] = relationship(single_parent=True)
    # PARENT
    sw_class_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_impls.rid"))
    sw_class_impls: Mapped["SwClassImpls"] = relationship(back_populates="sw_class_impl")


class SwFeatureExportCalprms(Base, HasSwCalprmRefs, HasSwCalprmRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_export_calprms"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": ("sw_calprm_refs", "A"),
        "SwCalprmRefSyscond": ("sw_calprm_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_calprm_ref
    # ARR
    # NO_PA         sw_calprm_ref_syscond


class SwVariablesWrite(Base, HasSwVariableRefs, HasSwVariableRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variables_write"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
        "SwVariableRefSyscond": ("sw_variable_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref
    # ARR
    # NO_PA         sw_variable_ref_syscond


class SwVariablesReadWrite(Base, HasSwVariableRefs, HasSwVariableRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_variables_read_write"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
        "SwVariableRefSyscond": ("sw_variable_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref
    # ARR
    # NO_PA         sw_variable_ref_syscond

    # N-I: SwVariableRefSyscond


class SwFeatureExportVariables(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_export_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesRead": ("sw_variables_read", "R"),
        "SwVariablesWrite": ("sw_variables_write", "R"),
        "SwVariablesReadWrite": ("sw_variables_read_write", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variables_read_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read.rid"))
    sw_variables_read: Mapped["SwVariablesRead"] = relationship(single_parent=True)
    # REF
    sw_variables_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_write.rid"))
    sw_variables_write: Mapped["SwVariablesWrite"] = relationship(single_parent=True)
    # REF
    sw_variables_read_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read_write.rid"))
    sw_variables_read_write: Mapped["SwVariablesReadWrite"] = relationship(single_parent=True)


class SwFeatureImportVariables(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_import_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesRead": ("sw_variables_read", "R"),
        "SwVariablesWrite": ("sw_variables_write", "R"),
        "SwVariablesReadWrite": ("sw_variables_read_write", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variables_read_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read.rid"))
    sw_variables_read: Mapped["SwVariablesRead"] = relationship(single_parent=True)
    # REF
    sw_variables_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_write.rid"))
    sw_variables_write: Mapped["SwVariablesWrite"] = relationship(single_parent=True)
    # REF
    sw_variables_read_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read_write.rid"))
    sw_variables_read_write: Mapped["SwVariablesReadWrite"] = relationship(single_parent=True)


class SwFeatureLocalVariables(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_local_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesReadWrite": ("sw_variables_read_write", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variables_read_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read_write.rid"))
    sw_variables_read_write: Mapped["SwVariablesReadWrite"] = relationship(single_parent=True)


class SwFeatureModelOnlyVariables(Base, HasSwVariableRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_model_only_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_variable_ref


class SwFeatureVariables(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_variables"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureExportVariables": ("sw_feature_export_variables", "R"),
        "SwFeatureImportVariables": ("sw_feature_import_variables", "R"),
        "SwFeatureLocalVariables": ("sw_feature_local_variables", "R"),
        "SwFeatureModelOnlyVariables": ("sw_feature_model_only_variables", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_feature_export_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_export_variables.rid"))
    sw_feature_export_variables: Mapped["SwFeatureExportVariables"] = relationship(single_parent=True)
    # REF
    sw_feature_import_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_import_variables.rid"))
    sw_feature_import_variables: Mapped["SwFeatureImportVariables"] = relationship(single_parent=True)
    # REF
    sw_feature_local_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_local_variables.rid"))
    sw_feature_local_variables: Mapped["SwFeatureLocalVariables"] = relationship(single_parent=True)
    # REF
    sw_feature_model_only_variables_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_feature_model_only_variables.rid")
    )
    sw_feature_model_only_variables: Mapped["SwFeatureModelOnlyVariables"] = relationship(single_parent=True)


class SwFeatureExportClassInstances(Base, HasSwClassInstanceRefs, HasSwInstanceRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_export_class_instances"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": ("sw_class_instance_refs", "A"),
        "SwInstanceRefSyscond": ("sw_instance_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_class_instance_ref
    # ARR
    # NO_PA         sw_instance_ref_syscond


class SwFeatureImportCalprms(Base, HasSwCalprmRefs, HasSwCalprmRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_import_calprms"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": ("sw_calprm_refs", "A"),
        "SwCalprmRefSyscond": ("sw_calprm_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_calprm_ref
    # ARR
    # NO_PA         sw_calprm_ref_syscond

    # N-I: SwCalprmRefSyscond


class SwFeatureLocalParams(Base, HasSwCalprmRefs, HasSwCalprmRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_local_params"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": ("sw_calprm_refs", "A"),
        "SwCalprmRefSyscond": ("sw_calprm_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_calprm_ref
    # ARR
    # NO_PA         sw_calprm_ref_syscond


class SwFeatureParams(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_params"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureExportCalprms": ("sw_feature_export_calprms", "R"),
        "SwFeatureImportCalprms": ("sw_feature_import_calprms", "R"),
        "SwFeatureLocalParams": ("sw_feature_local_params", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_feature_export_calprms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_export_calprms.rid"))
    sw_feature_export_calprms: Mapped["SwFeatureExportCalprms"] = relationship(single_parent=True)
    # REF
    sw_feature_import_calprms_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_import_calprms.rid"))
    sw_feature_import_calprms: Mapped["SwFeatureImportCalprms"] = relationship(single_parent=True)
    # REF
    sw_feature_local_params_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_local_params.rid"))
    sw_feature_local_params: Mapped["SwFeatureLocalParams"] = relationship(single_parent=True)


class SwTestDesc(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_test_desc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwFeatureImportClassInstances(Base, HasSwClassInstanceRefs, HasSwInstanceRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_import_class_instances"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": ("sw_class_instance_refs", "A"),
        "SwInstanceRefSyscond": ("sw_instance_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_class_instance_ref
    # ARR
    # NO_PA         sw_instance_ref_syscond

    # N-I: SwClassInstanceRef

    # N-I: SwInstanceRefSyscond


class SwFeatureLocalClassInstances(Base, HasSwClassInstanceRefs, HasSwInstanceRefSysconds):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_local_class_instances"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": ("sw_class_instance_refs", "A"),
        "SwInstanceRefSyscond": ("sw_instance_ref_sysconds", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_class_instance_ref
    # ARR
    # NO_PA         sw_instance_ref_syscond


class SwFeatureClassInstances(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_class_instances"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureExportClassInstances": ("sw_feature_export_class_instances", "R"),
        "SwFeatureImportClassInstances": ("sw_feature_import_class_instances", "R"),
        "SwFeatureLocalClassInstances": ("sw_feature_local_class_instances", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_feature_export_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_feature_export_class_instances.rid")
    )
    sw_feature_export_class_instances: Mapped["SwFeatureExportClassInstances"] = relationship(single_parent=True)
    # REF
    sw_feature_import_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_feature_import_class_instances.rid")
    )
    sw_feature_import_class_instances: Mapped["SwFeatureImportClassInstances"] = relationship(single_parent=True)
    # REF
    sw_feature_local_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_feature_local_class_instances.rid")
    )
    sw_feature_local_class_instances: Mapped["SwFeatureLocalClassInstances"] = relationship(single_parent=True)


class SwApplicationNotes(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_application_notes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwMaintenanceNotes(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_maintenance_notes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwCarbDoc(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_carb_doc"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SwClass(Base):
    # SIMPLE: SwComponents == SR: False
    # P: ('SwComponents', 'sw_components')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwFeatureDef": ("sw_feature_def", "R"),
        "SwFeatureDesc": ("sw_feature_desc", "R"),
        "SwFulfils": ("sw_fulfils", "R"),
        "SwClassMethods": ("sw_class_methods", "R"),
        "SwClassAttr": ("sw_class_attr", "R"),
        "SwClassAttrImpls": ("sw_class_attr_impls", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
        "SwFeatureVariables": ("sw_feature_variables", "R"),
        "SwFeatureParams": ("sw_feature_params", "R"),
        "SwFeatureClassInstances": ("sw_feature_class_instances", "R"),
        "SwTestDesc": ("sw_test_desc", "R"),
        "SwApplicationNotes": ("sw_application_notes", "R"),
        "SwMaintenanceNotes": ("sw_maintenance_notes", "R"),
        "SwCarbDoc": ("sw_carb_doc", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_feature_def_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_def.rid"))
    sw_feature_def: Mapped["SwFeatureDef"] = relationship(single_parent=True)
    # REF
    sw_feature_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_desc.rid"))
    sw_feature_desc: Mapped["SwFeatureDesc"] = relationship(single_parent=True)
    # REF
    sw_fulfils_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_fulfils.rid"))
    sw_fulfils: Mapped["SwFulfils"] = relationship(single_parent=True)
    # REF
    sw_class_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_methods.rid"))
    sw_class_methods: Mapped["SwClassMethods"] = relationship(single_parent=True)
    # REF
    sw_class_attr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_attr.rid"))
    sw_class_attr: Mapped["SwClassAttr"] = relationship(single_parent=True)
    # REF
    sw_class_attr_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_attr_impls.rid"))
    sw_class_attr_impls: Mapped["SwClassAttrImpls"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # REF
    sw_feature_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_variables.rid"))
    sw_feature_variables: Mapped["SwFeatureVariables"] = relationship(single_parent=True)
    # REF
    sw_feature_params_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_params.rid"))
    sw_feature_params: Mapped["SwFeatureParams"] = relationship(single_parent=True)
    # REF
    sw_feature_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_class_instances.rid"))
    sw_feature_class_instances: Mapped["SwFeatureClassInstances"] = relationship(single_parent=True)
    # REF
    sw_test_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_test_desc.rid"))
    sw_test_desc: Mapped["SwTestDesc"] = relationship(single_parent=True)
    # REF
    sw_application_notes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_application_notes.rid"))
    sw_application_notes: Mapped["SwApplicationNotes"] = relationship(single_parent=True)
    # REF
    sw_maintenance_notes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_maintenance_notes.rid"))
    sw_maintenance_notes: Mapped["SwMaintenanceNotes"] = relationship(single_parent=True)
    # REF
    sw_carb_doc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_carb_doc.rid"))
    sw_carb_doc: Mapped["SwCarbDoc"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_components_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_components.rid"))
    sw_components: Mapped["SwComponents"] = relationship(back_populates="sw_class")


class SwFeatureDesignData(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_design_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariablesRead": ("sw_variables_read", "R"),
        "SwVariablesWrite": ("sw_variables_write", "R"),
        "SwVariablesReadWrite": ("sw_variables_read_write", "R"),
        "SwFeatureLocalParams": ("sw_feature_local_params", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variables_read_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read.rid"))
    sw_variables_read: Mapped["SwVariablesRead"] = relationship(single_parent=True)
    # REF
    sw_variables_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_write.rid"))
    sw_variables_write: Mapped["SwVariablesWrite"] = relationship(single_parent=True)
    # REF
    sw_variables_read_write_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variables_read_write.rid"))
    sw_variables_read_write: Mapped["SwVariablesReadWrite"] = relationship(single_parent=True)
    # REF
    sw_feature_local_params_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_local_params.rid"))
    sw_feature_local_params: Mapped["SwFeatureLocalParams"] = relationship(single_parent=True)


class SwEffectFlows(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwEffectFlow']
    __tablename__ = "sw_effect_flows"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwEffectFlow": ("sw_effect_flow", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_effect_flow: Mapped[list["SwEffectFlow"]] = relationship(back_populates="sw_effect_flows")


class SwSystemconstRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwSystemconstRef']
    __tablename__ = "sw_systemconst_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSystemconstRef": ("sw_systemconst_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_systemconst_ref: Mapped[list["SwSystemconstRef"]] = relationship(back_populates="sw_systemconst_refs")


class SwEffectFlow(Base):
    # SIMPLE: SwEffectFlows == SR: False
    # P: ('SwEffectFlows', 'sw_effect_flows')  --  C: ['SwEffectingVariable']
    __tablename__ = "sw_effect_flow"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_ref", "R"),
        "SwEffectingVariable": ("sw_effecting_variable", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref.rid"))
    sw_variable_ref: Mapped["SwVariableRef"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_effecting_variable: Mapped[list["SwEffectingVariable"]] = relationship(back_populates="sw_effect_flow")
    # PARENT
    sw_effect_flows_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_effect_flows.rid"))
    sw_effect_flows: Mapped["SwEffectFlows"] = relationship(back_populates="sw_effect_flow")


class SwEffectingVariable(Base):
    # SIMPLE: SwEffectFlow == SR: False
    # P: ('SwEffectFlow', 'sw_effect_flow')  --  C: ['SwEffect']
    __tablename__ = "sw_effecting_variable"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVariableRef": ("sw_variable_ref", "R"),
        "SwEffect": ("sw_effect", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_variable_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref.rid"))
    sw_variable_ref: Mapped["SwVariableRef"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_effect: Mapped[list["SwEffect"]] = relationship(back_populates="sw_effecting_variable")
    # PARENT
    sw_effect_flow_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_effect_flow.rid"))
    sw_effect_flow: Mapped["SwEffectFlow"] = relationship(back_populates="sw_effecting_variable")


class SwEffect(Base):
    # SIMPLE: SwEffectingVariable == SR: False
    # P: ('SwEffectingVariable', 'sw_effecting_variable')  --  C: []
    __tablename__ = "sw_effect"

    ATTRIBUTES = {
        "ORIGIN": "origin",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    origin = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_effecting_variable_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_effecting_variable.rid"))
    sw_effecting_variable: Mapped["SwEffectingVariable"] = relationship(back_populates="sw_effect")


class SwFeatureDecomposition(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwSubcomponent']
    __tablename__ = "sw_feature_decomposition"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwSubcomponent": ("sw_subcomponent", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_subcomponent: Mapped[list["SwSubcomponent"]] = relationship(back_populates="sw_feature_decomposition")


class SwSystemconstRef(Base):
    # SIMPLE: SwSystemconstRefs == SR: False
    # P: ('SwSystemconstRefs', 'sw_systemconst_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_systemconst_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconst_refs.rid"))
    sw_systemconst_refs: Mapped["SwSystemconstRefs"] = relationship(back_populates="sw_systemconst_ref")


class SwFeature(Base):
    # SIMPLE: SwComponents == SR: False
    # P: ('SwComponents', 'sw_components')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwFeatureDef": ("sw_feature_def", "R"),
        "SwFeatureDesc": ("sw_feature_desc", "R"),
        "SwFulfils": ("sw_fulfils", "R"),
        "SwFeatureDesignData": ("sw_feature_design_data", "R"),
        "SwEffectFlows": ("sw_effect_flows", "R"),
        "SwFeatureVariables": ("sw_feature_variables", "R"),
        "SwFeatureParams": ("sw_feature_params", "R"),
        "SwFeatureClassInstances": ("sw_feature_class_instances", "R"),
        "SwSystemconstRefs": ("sw_systemconst_refs", "R"),
        "SwDataDictionarySpec": ("sw_data_dictionary_spec", "R"),
        "SwTestDesc": ("sw_test_desc", "R"),
        "SwApplicationNotes": ("sw_application_notes", "R"),
        "SwMaintenanceNotes": ("sw_maintenance_notes", "R"),
        "SwCarbDoc": ("sw_carb_doc", "R"),
        "SwFeatureDecomposition": ("sw_feature_decomposition", "R"),
        "Annotations": ("annotations", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_feature_def_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_def.rid"))
    sw_feature_def: Mapped["SwFeatureDef"] = relationship(single_parent=True)
    # REF
    sw_feature_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_desc.rid"))
    sw_feature_desc: Mapped["SwFeatureDesc"] = relationship(single_parent=True)
    # REF
    sw_fulfils_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_fulfils.rid"))
    sw_fulfils: Mapped["SwFulfils"] = relationship(single_parent=True)
    # REF
    sw_feature_design_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_design_data.rid"))
    sw_feature_design_data: Mapped["SwFeatureDesignData"] = relationship(single_parent=True)
    # REF
    sw_effect_flows_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_effect_flows.rid"))
    sw_effect_flows: Mapped["SwEffectFlows"] = relationship(single_parent=True)
    # REF
    sw_feature_variables_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_variables.rid"))
    sw_feature_variables: Mapped["SwFeatureVariables"] = relationship(single_parent=True)
    # REF
    sw_feature_params_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_params.rid"))
    sw_feature_params: Mapped["SwFeatureParams"] = relationship(single_parent=True)
    # REF
    sw_feature_class_instances_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_class_instances.rid"))
    sw_feature_class_instances: Mapped["SwFeatureClassInstances"] = relationship(single_parent=True)
    # REF
    sw_systemconst_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconst_refs.rid"))
    sw_systemconst_refs: Mapped["SwSystemconstRefs"] = relationship(single_parent=True)
    # REF
    sw_data_dictionary_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_dictionary_spec.rid"))
    sw_data_dictionary_spec: Mapped["SwDataDictionarySpec"] = relationship(single_parent=True)
    # REF
    sw_test_desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_test_desc.rid"))
    sw_test_desc: Mapped["SwTestDesc"] = relationship(single_parent=True)
    # REF
    sw_application_notes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_application_notes.rid"))
    sw_application_notes: Mapped["SwApplicationNotes"] = relationship(single_parent=True)
    # REF
    sw_maintenance_notes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_maintenance_notes.rid"))
    sw_maintenance_notes: Mapped["SwMaintenanceNotes"] = relationship(single_parent=True)
    # REF
    sw_carb_doc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_carb_doc.rid"))
    sw_carb_doc: Mapped["SwCarbDoc"] = relationship(single_parent=True)
    # REF
    sw_feature_decomposition_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_decomposition.rid"))
    sw_feature_decomposition: Mapped["SwFeatureDecomposition"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_components_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_components.rid"))
    sw_components: Mapped["SwComponents"] = relationship(back_populates="sw_feature")

    # N-I: SwFeatureRef


class SwProcesses(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwProcess']
    __tablename__ = "sw_processes"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwProcess": ("sw_process", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_process: Mapped[list["SwProcess"]] = relationship(back_populates="sw_processes")


class SwSubcomponent(Base):
    # SIMPLE: SwFeatureDecomposition == SR: False
    # P: ('SwFeatureDecomposition', 'sw_feature_decomposition')  --  C: []
    __tablename__ = "sw_subcomponent"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRef": ("sw_feature_ref", "R"),
        "SwProcesses": ("sw_processes", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_feature_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_ref.rid"))
    sw_feature_ref: Mapped["SwFeatureRef"] = relationship(single_parent=True)
    # REF
    sw_processes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_processes.rid"))
    sw_processes: Mapped["SwProcesses"] = relationship(single_parent=True)
    # PARENT
    sw_feature_decomposition_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_decomposition.rid"))
    sw_feature_decomposition: Mapped["SwFeatureDecomposition"] = relationship(back_populates="sw_subcomponent")


class SwProcess(Base):
    # SIMPLE: SwProcesses == SR: False
    # P: ('SwProcesses', 'sw_processes')  --  C: []
    __tablename__ = "sw_process"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "ShortLabel": ("short_label", "R"),
        "SwTaskRef": ("sw_task_ref", "R"),
        "Desc": ("_desc", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    short_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_label.rid"))
    short_label: Mapped["ShortLabel"] = relationship(single_parent=True)
    # REF
    sw_task_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_task_ref.rid"))
    sw_task_ref: Mapped["SwTaskRef"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # PARENT
    sw_processes_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_processes.rid"))
    sw_processes: Mapped["SwProcesses"] = relationship(back_populates="sw_process")


class SwComponentSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_component_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwComponents": ("sw_components", "R"),
        "SwRootFeatures": ("sw_root_features", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_components_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_components.rid"))
    sw_components: Mapped["SwComponents"] = relationship(single_parent=True)
    # REF
    sw_root_features_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_root_features.rid"))
    sw_root_features: Mapped["SwRootFeatures"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwCollections(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCollection']
    __tablename__ = "sw_collections"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollection": ("sw_collection", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_collection: Mapped[list["SwCollection"]] = relationship(back_populates="sw_collections")


class DisplayName(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwCollectionRefs == SR: False
    # P: ('SwCollectionRefs', 'sw_collection_refs')  --  C: []
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
    ELEMENTS = {}
    ENUMS = {
        "invert": ["INVERT", "NO-INVERT"],
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
    # PARENT
    sw_collection_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_refs.rid"))
    sw_collection_refs: Mapped["SwCollectionRefs"] = relationship(back_populates="sw_collection_ref")


class SwCsCollections(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCsCollection']
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
        "SwCsCollection": ("sw_cs_collection", "A"),
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    # ARR
    # PARENT-OBJ
    sw_cs_collection: Mapped[list["SwCsCollection"]] = relationship(back_populates="sw_cs_collections")


class SymbolicFile(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['CsEntry', 'SwCsEntry']
    __tablename__ = "sw_cs_history"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "CsEntry": ("cs_entry", "A"),
        "SwCsEntry": ("sw_cs_entry", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    cs_entry: Mapped[list["CsEntry"]] = relationship(back_populates="sw_cs_history")
    # ARR
    # PARENT-OBJ
    sw_cs_entry: Mapped[list["SwCsEntry"]] = relationship(back_populates="sw_cs_history")


class Csus(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_state"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsContext(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_context"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsProjectInfo(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_project_info"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsTargetVariant(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_target_variant"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsTestObject(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_test_object"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsProgramIdentifier(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_program_identifier"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsDataIdentifier(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_data_identifier"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCsPerformedBy(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cs_performed_by"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Cspr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwCsEntry == SR: False
    # P: ('SwCsEntry', 'sw_cs_entry')  --  C: []
    __tablename__ = "sw_cs_field"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_cs_entry_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_entry.rid"))
    sw_cs_entry: Mapped["SwCsEntry"] = relationship(back_populates="sw_cs_field")


class SwVcdCriterionValues(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwVcdCriterionValue']
    __tablename__ = "sw_vcd_criterion_values"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterionValue": ("sw_vcd_criterion_value", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_vcd_criterion_value: Mapped[list["SwVcdCriterionValue"]] = relationship(back_populates="sw_vcd_criterion_values")


class SwVcdCriterionValue(Base):
    # SIMPLE: SwVcdCriterionValues == SR: False
    # P: ('SwVcdCriterionValues', 'sw_vcd_criterion_values')  --  C: []
    __tablename__ = "sw_vcd_criterion_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterionRef": ("sw_vcd_criterion_ref", "R"),
        "Vt": ("vt", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_vcd_criterion_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criterion_ref.rid"))
    sw_vcd_criterion_ref: Mapped["SwVcdCriterionRef"] = relationship(single_parent=True)
    # REF
    vt_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("vt.rid"))
    vt: Mapped["Vt"] = relationship(single_parent=True)
    # PARENT
    sw_vcd_criterion_values_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criterion_values.rid"))
    sw_vcd_criterion_values: Mapped["SwVcdCriterionValues"] = relationship(back_populates="sw_vcd_criterion_value")


class UnitDisplayName(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    ENUMS = {
        "space": ["default", "preserve"],
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "UnitDisplayName": ("unit_display_name", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwValuesPhys": ("sw_values_phys", "R"),
        "SwValuesCoded": ("sw_values_coded", "R"),
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    # REF
    unit_display_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("unit_display_name.rid"))
    unit_display_name: Mapped["UnitDisplayName"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_values_phys_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_phys.rid"))
    sw_values_phys: Mapped["SwValuesPhys"] = relationship(single_parent=True)
    # REF
    sw_values_coded_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_coded.rid"))
    sw_values_coded: Mapped["SwValuesCoded"] = relationship(single_parent=True)


class SwModelLink(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_array_index"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwAxisConts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAxisCont']
    __tablename__ = "sw_axis_conts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisCont": ("sw_axis_cont", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_axis_cont: Mapped[list["SwAxisCont"]] = relationship(back_populates="sw_axis_conts")


class SwInstancePropsVariants(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwInstancePropsVariant']
    __tablename__ = "sw_instance_props_variants"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwInstancePropsVariant": ("sw_instance_props_variant", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_instance_props_variant: Mapped[list["SwInstancePropsVariant"]] = relationship(back_populates="sw_instance_props_variants")


class SwCsFlags(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCsFlag']
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
        "SwCsFlag": ("sw_cs_flag", "A"),
    }
    s = StdString()
    si = StdString()
    c = StdString()
    lc = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    # ARR
    # PARENT-OBJ
    sw_cs_flag: Mapped[list["SwCsFlag"]] = relationship(back_populates="sw_cs_flags")


class SwAddrInfos(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAddrInfo']
    __tablename__ = "sw_addr_infos"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAddrInfo": ("sw_addr_info", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_addr_info: Mapped[list["SwAddrInfo"]] = relationship(back_populates="sw_addr_infos")


class SwBaseAddr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_base_addr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwAddrOffset(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_addr_offset"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class Csdi(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    value = StdString()
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()


class SwCsEntry(Base, HasSds):
    # SIMPLE: SwCsHistory == SR: False
    # P: ('SwCsHistory', 'sw_cs_history')  --  C: ['SwCsField']
    __tablename__ = "sw_cs_entry"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCsState": ("sw_cs_state", "R"),
        "State": ("state", "R"),
        "SwCsContext": ("sw_cs_context", "R"),
        "SwCsProjectInfo": ("sw_cs_project_info", "R"),
        "SwCsTargetVariant": ("sw_cs_target_variant", "R"),
        "SwCsTestObject": ("sw_cs_test_object", "R"),
        "SwCsProgramIdentifier": ("sw_cs_program_identifier", "R"),
        "SwCsDataIdentifier": ("sw_cs_data_identifier", "R"),
        "SwCsPerformedBy": ("sw_cs_performed_by", "R"),
        "Csus": ("csus", "R"),
        "Cspr": ("cspr", "R"),
        "Cswp": ("cswp", "R"),
        "Csto": ("csto", "R"),
        "Cstv": ("cstv", "R"),
        "Cspi": ("cspi", "R"),
        "Csdi": ("csdi", "R"),
        "Remark": ("remark", "R"),
        "Date": ("date", "R"),
        "Sd": ("sds", "A"),
        "SwCsField": ("sw_cs_field", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_cs_state_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_state.rid"))
    sw_cs_state: Mapped["SwCsState"] = relationship(single_parent=True)
    # REF
    state_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("state.rid"))
    state: Mapped["State"] = relationship(single_parent=True)
    # REF
    sw_cs_context_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_context.rid"))
    sw_cs_context: Mapped["SwCsContext"] = relationship(single_parent=True)
    # REF
    sw_cs_project_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_project_info.rid"))
    sw_cs_project_info: Mapped["SwCsProjectInfo"] = relationship(single_parent=True)
    # REF
    sw_cs_target_variant_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_target_variant.rid"))
    sw_cs_target_variant: Mapped["SwCsTargetVariant"] = relationship(single_parent=True)
    # REF
    sw_cs_test_object_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_test_object.rid"))
    sw_cs_test_object: Mapped["SwCsTestObject"] = relationship(single_parent=True)
    # REF
    sw_cs_program_identifier_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_program_identifier.rid"))
    sw_cs_program_identifier: Mapped["SwCsProgramIdentifier"] = relationship(single_parent=True)
    # REF
    sw_cs_data_identifier_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_data_identifier.rid"))
    sw_cs_data_identifier: Mapped["SwCsDataIdentifier"] = relationship(single_parent=True)
    # REF
    sw_cs_performed_by_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_performed_by.rid"))
    sw_cs_performed_by: Mapped["SwCsPerformedBy"] = relationship(single_parent=True)
    # REF
    csus_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csus.rid"))
    csus: Mapped["Csus"] = relationship(single_parent=True)
    # REF
    cspr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cspr.rid"))
    cspr: Mapped["Cspr"] = relationship(single_parent=True)
    # REF
    cswp_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cswp.rid"))
    cswp: Mapped["Cswp"] = relationship(single_parent=True)
    # REF
    csto_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csto.rid"))
    csto: Mapped["Csto"] = relationship(single_parent=True)
    # REF
    cstv_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cstv.rid"))
    cstv: Mapped["Cstv"] = relationship(single_parent=True)
    # REF
    cspi_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cspi.rid"))
    cspi: Mapped["Cspi"] = relationship(single_parent=True)
    # REF
    csdi_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csdi.rid"))
    csdi: Mapped["Csdi"] = relationship(single_parent=True)
    # REF
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)
    # REF
    date_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date.rid"))
    date: Mapped["Date"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sd
    # ARR
    # PARENT-OBJ
    sw_cs_field: Mapped[list["SwCsField"]] = relationship(back_populates="sw_cs_entry")
    # PARENT
    sw_cs_history_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_history.rid"))
    sw_cs_history: Mapped["SwCsHistory"] = relationship(back_populates="sw_cs_entry")


class CsEntry(Base, HasSds):
    # SIMPLE: SwCsHistory == SR: False
    # P: ('SwCsHistory', 'sw_cs_history')  --  C: []
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
        "State": ("state", "R"),
        "Date": ("date", "R"),
        "Csus": ("csus", "R"),
        "Cspr": ("cspr", "R"),
        "Cswp": ("cswp", "R"),
        "Csto": ("csto", "R"),
        "Cstv": ("cstv", "R"),
        "Cspi": ("cspi", "R"),
        "Csdi": ("csdi", "R"),
        "Remark": ("remark", "R"),
        "Sd": ("sds", "A"),
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    # REF
    state_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("state.rid"))
    state: Mapped["State"] = relationship(single_parent=True)
    # REF
    date_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date.rid"))
    date: Mapped["Date"] = relationship(single_parent=True)
    # REF
    csus_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csus.rid"))
    csus: Mapped["Csus"] = relationship(single_parent=True)
    # REF
    cspr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cspr.rid"))
    cspr: Mapped["Cspr"] = relationship(single_parent=True)
    # REF
    cswp_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cswp.rid"))
    cswp: Mapped["Cswp"] = relationship(single_parent=True)
    # REF
    csto_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csto.rid"))
    csto: Mapped["Csto"] = relationship(single_parent=True)
    # REF
    cstv_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cstv.rid"))
    cstv: Mapped["Cstv"] = relationship(single_parent=True)
    # REF
    cspi_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("cspi.rid"))
    cspi: Mapped["Cspi"] = relationship(single_parent=True)
    # REF
    csdi_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csdi.rid"))
    csdi: Mapped["Csdi"] = relationship(single_parent=True)
    # REF
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sd
    # PARENT
    sw_cs_history_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_history.rid"))
    sw_cs_history: Mapped["SwCsHistory"] = relationship(back_populates="cs_entry")


class SwCsFlag(Base):
    # SIMPLE: SwCsFlags == SR: False
    # P: ('SwCsFlags', 'sw_cs_flags')  --  C: []
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
        "Category": ("category", "R"),
        "Flag": ("flag", "R"),
        "Csus": ("csus", "R"),
        "Date": ("date", "R"),
        "Remark": ("remark", "R"),
    }
    c = StdString()
    lc = StdString()
    t = StdString()
    ti = StdString()
    s = StdString()
    si = StdString()
    _view = StdString()
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    flag_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("flag.rid"))
    flag: Mapped["Flag"] = relationship(single_parent=True)
    # REF
    csus_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("csus.rid"))
    csus: Mapped["Csus"] = relationship(single_parent=True)
    # REF
    date_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("date.rid"))
    date: Mapped["Date"] = relationship(single_parent=True)
    # REF
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)
    # PARENT
    sw_cs_flags_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_flags.rid"))
    sw_cs_flags: Mapped["SwCsFlags"] = relationship(back_populates="sw_cs_flag")


class SwMcInstanceInterfaces(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcInstanceInterface']
    __tablename__ = "sw_mc_instance_interfaces"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInstanceInterface": ("sw_mc_instance_interface", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_instance_interface: Mapped[list["SwMcInstanceInterface"]] = relationship(back_populates="sw_mc_instance_interfaces")


class SwSizeofInstance(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_sizeof_instance"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwAddrInfo(Base):
    # SIMPLE: SwAddrInfos == SR: False
    # P: ('SwAddrInfos', 'sw_addr_infos')  --  C: []
    __tablename__ = "sw_addr_info"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCpuMemSegRef": ("sw_cpu_mem_seg_ref", "R"),
        "SwBaseAddr": ("sw_base_addr", "R"),
        "SwAddrOffset": ("sw_addr_offset", "R"),
        "SwSizeofInstance": ("sw_sizeof_instance", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_cpu_mem_seg_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_mem_seg_ref.rid"))
    sw_cpu_mem_seg_ref: Mapped["SwCpuMemSegRef"] = relationship(single_parent=True)
    # REF
    sw_base_addr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_addr.rid"))
    sw_base_addr: Mapped["SwBaseAddr"] = relationship(single_parent=True)
    # REF
    sw_addr_offset_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_offset.rid"))
    sw_addr_offset: Mapped["SwAddrOffset"] = relationship(single_parent=True)
    # REF
    sw_sizeof_instance_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_sizeof_instance.rid"))
    sw_sizeof_instance: Mapped["SwSizeofInstance"] = relationship(single_parent=True)
    # PARENT
    sw_addr_infos_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_infos.rid"))
    sw_addr_infos: Mapped["SwAddrInfos"] = relationship(back_populates="sw_addr_info")

    # N-I: SwInstance


class SwValuesCodedHex(Base, HasVfs, HasVts, HasVhs, HasVs, HasVgs, HasSwInstanceRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_values_coded_hex"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
        "Vt": ("vts", "A"),
        "Vh": ("vhs", "A"),
        "V": ("vs", "A"),
        "Vg": ("vgs", "A"),
        "SwInstanceRef": ("sw_instance_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf
    # ARR
    # NO_PA         vt
    # ARR
    # NO_PA         vh
    # ARR
    # NO_PA         v
    # ARR
    # NO_PA         vg
    # ARR
    # NO_PA         sw_instance_ref


class SwAxisCont(Base):
    # SIMPLE: SwAxisConts == SR: False
    # P: ('SwAxisConts', 'sw_axis_conts')  --  C: ['SwValuesGeneric']
    __tablename__ = "sw_axis_cont"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUnitRef": ("sw_unit_ref", "R"),
        "UnitDisplayName": ("unit_display_name", "R"),
        "SwAxisIndex": ("sw_axis_index", "R"),
        "SwValuesPhys": ("sw_values_phys", "R"),
        "SwValuesCoded": ("sw_values_coded", "R"),
        "SwValuesCodedHex": ("sw_values_coded_hex", "R"),
        "Category": ("category", "R"),
        "SwArraysize": ("sw_arraysize", "R"),
        "SwInstanceRef": ("sw_instance_ref", "R"),
        "SwValuesGeneric": ("sw_values_generic", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_unit_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_ref.rid"))
    sw_unit_ref: Mapped["SwUnitRef"] = relationship(single_parent=True)
    # REF
    unit_display_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("unit_display_name.rid"))
    unit_display_name: Mapped["UnitDisplayName"] = relationship(single_parent=True)
    # REF
    sw_axis_index_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_index.rid"))
    sw_axis_index: Mapped["SwAxisIndex"] = relationship(single_parent=True)
    # REF
    sw_values_phys_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_phys.rid"))
    sw_values_phys: Mapped["SwValuesPhys"] = relationship(single_parent=True)
    # REF
    sw_values_coded_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_coded.rid"))
    sw_values_coded: Mapped["SwValuesCoded"] = relationship(single_parent=True)
    # REF
    sw_values_coded_hex_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_values_coded_hex.rid"))
    sw_values_coded_hex: Mapped["SwValuesCodedHex"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    sw_arraysize_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_arraysize.rid"))
    sw_arraysize: Mapped["SwArraysize"] = relationship(single_parent=True)
    # REF
    sw_instance_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_ref.rid"))
    sw_instance_ref: Mapped["SwInstanceRef"] = relationship(single_parent=True)
    # ARR
    # PARENT-OBJ
    sw_values_generic: Mapped[list["SwValuesGeneric"]] = relationship(back_populates="sw_axis_cont")
    # PARENT
    sw_axis_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_conts.rid"))
    sw_axis_conts: Mapped["SwAxisConts"] = relationship(back_populates="sw_axis_cont")


class SwValuesGeneric(Base, HasVfs, HasVts, HasVhs, HasVs, HasVgs, HasSwInstanceRefs):
    # SIMPLE: SwAxisCont == SR: False
    # P: ('SwAxisCont', 'sw_axis_cont')  --  C: []
    __tablename__ = "sw_values_generic"

    ATTRIBUTES = {
        "TYPE": "_type",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
        "Vt": ("vts", "A"),
        "Vh": ("vhs", "A"),
        "V": ("vs", "A"),
        "Vg": ("vgs", "A"),
        "SwInstanceRef": ("sw_instance_refs", "A"),
    }
    _type = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf
    # ARR
    # NO_PA         vt
    # ARR
    # NO_PA         vh
    # ARR
    # NO_PA         v
    # ARR
    # NO_PA         vg
    # ARR
    # NO_PA         sw_instance_ref
    # PARENT
    sw_axis_cont_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_cont.rid"))
    sw_axis_cont: Mapped["SwAxisCont"] = relationship(back_populates="sw_values_generic")


class SwInstancePropsVariant(Base):
    # SIMPLE: SwInstancePropsVariants == SR: False
    # P: ('SwInstancePropsVariants', 'sw_instance_props_variants')  --  C: []
    __tablename__ = "sw_instance_props_variant"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "Desc": ("_desc", "R"),
        "SwVcdCriterionValues": ("sw_vcd_criterion_values", "R"),
        "SwValueCont": ("sw_value_cont", "R"),
        "SwCsFlags": ("sw_cs_flags", "R"),
        "SwAddrInfos": ("sw_addr_infos", "R"),
        "SwAxisConts": ("sw_axis_conts", "R"),
        "SwDataDefProps": ("sw_data_def_props", "R"),
        "SwMcInstanceInterfaces": ("sw_mc_instance_interfaces", "R"),
        "SwCsHistory": ("sw_cs_history", "R"),
        "Annotations": ("annotations", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    sw_vcd_criterion_values_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criterion_values.rid"))
    sw_vcd_criterion_values: Mapped["SwVcdCriterionValues"] = relationship(single_parent=True)
    # REF
    sw_value_cont_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_value_cont.rid"))
    sw_value_cont: Mapped["SwValueCont"] = relationship(single_parent=True)
    # REF
    sw_cs_flags_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_flags.rid"))
    sw_cs_flags: Mapped["SwCsFlags"] = relationship(single_parent=True)
    # REF
    sw_addr_infos_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_infos.rid"))
    sw_addr_infos: Mapped["SwAddrInfos"] = relationship(single_parent=True)
    # REF
    sw_axis_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_conts.rid"))
    sw_axis_conts: Mapped["SwAxisConts"] = relationship(single_parent=True)
    # REF
    sw_data_def_props_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_def_props.rid"))
    sw_data_def_props: Mapped["SwDataDefProps"] = relationship(single_parent=True)
    # REF
    sw_mc_instance_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_instance_interfaces.rid"))
    sw_mc_instance_interfaces: Mapped["SwMcInstanceInterfaces"] = relationship(single_parent=True)
    # REF
    sw_cs_history_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_history.rid"))
    sw_cs_history: Mapped["SwCsHistory"] = relationship(single_parent=True)
    # REF
    annotations_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotations.rid"))
    annotations: Mapped["Annotations"] = relationship(single_parent=True)
    # PARENT
    sw_instance_props_variants_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_props_variants.rid"))
    sw_instance_props_variants: Mapped["SwInstancePropsVariants"] = relationship(back_populates="sw_instance_props_variant")


class SwMcInterfaceRef(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: SwMcInterfaceAvlSources == SR: False
    # P: ('SwMcInterfaceAvlSources', 'sw_mc_interface_avl_sources')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_mc_interface_avl_sources_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_avl_sources.rid"))
    sw_mc_interface_avl_sources: Mapped["SwMcInterfaceAvlSources"] = relationship(back_populates="sw_mc_interface_source_ref")


class SwMcInterfaceAvlSources(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcInterfaceSourceRef']
    __tablename__ = "sw_mc_interface_avl_sources"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceSourceRef": ("sw_mc_interface_source_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_interface_source_ref: Mapped[list["SwMcInterfaceSourceRef"]] = relationship(back_populates="sw_mc_interface_avl_sources")


class SwMcInterfaceDefaultSource(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_interface_default_source"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceSourceRef": ("sw_mc_interface_source_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_mc_interface_source_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_source_ref.rid"))
    sw_mc_interface_source_ref: Mapped["SwMcInterfaceSourceRef"] = relationship(single_parent=True)


class SwMcKpBlobConts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_kp_blob_conts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcDpBlobConts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_dp_blob_conts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcPaBlobConts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_pa_blob_conts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcAddrMappings(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcAddrMapping']
    __tablename__ = "sw_mc_addr_mappings"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcAddrMapping": ("sw_mc_addr_mapping", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_addr_mapping: Mapped[list["SwMcAddrMapping"]] = relationship(back_populates="sw_mc_addr_mappings")


class SwMcInstanceInterface(Base):
    # SIMPLE: SwMcInstanceInterfaces == SR: False
    # P: ('SwMcInstanceInterfaces', 'sw_mc_instance_interfaces')  --  C: []
    __tablename__ = "sw_mc_instance_interface"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceRef": ("sw_mc_interface_ref", "R"),
        "SwMcInterfaceDefaultSource": ("sw_mc_interface_default_source", "R"),
        "SwMcInterfaceAvlSources": ("sw_mc_interface_avl_sources", "R"),
        "SwMcKpBlobConts": ("sw_mc_kp_blob_conts", "R"),
        "SwMcDpBlobConts": ("sw_mc_dp_blob_conts", "R"),
        "SwMcPaBlobConts": ("sw_mc_pa_blob_conts", "R"),
        "SwMcAddrMappings": ("sw_mc_addr_mappings", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_mc_interface_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_ref.rid"))
    sw_mc_interface_ref: Mapped["SwMcInterfaceRef"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_default_source_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_mc_interface_default_source.rid")
    )
    sw_mc_interface_default_source: Mapped["SwMcInterfaceDefaultSource"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_avl_sources_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_avl_sources.rid"))
    sw_mc_interface_avl_sources: Mapped["SwMcInterfaceAvlSources"] = relationship(single_parent=True)
    # REF
    sw_mc_kp_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_kp_blob_conts.rid"))
    sw_mc_kp_blob_conts: Mapped["SwMcKpBlobConts"] = relationship(single_parent=True)
    # REF
    sw_mc_dp_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_dp_blob_conts.rid"))
    sw_mc_dp_blob_conts: Mapped["SwMcDpBlobConts"] = relationship(single_parent=True)
    # REF
    sw_mc_pa_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_pa_blob_conts.rid"))
    sw_mc_pa_blob_conts: Mapped["SwMcPaBlobConts"] = relationship(single_parent=True)
    # REF
    sw_mc_addr_mappings_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_addr_mappings.rid"))
    sw_mc_addr_mappings: Mapped["SwMcAddrMappings"] = relationship(single_parent=True)
    # PARENT
    sw_mc_instance_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_instance_interfaces.rid"))
    sw_mc_instance_interfaces: Mapped["SwMcInstanceInterfaces"] = relationship(back_populates="sw_mc_instance_interface")


class SwMcOriginalAddr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_original_addr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcMappedAddr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_mapped_addr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcAddrMappedSize(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_addr_mapped_size"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcAddrMapping(Base):
    # SIMPLE: SwMcAddrMappings == SR: False
    # P: ('SwMcAddrMappings', 'sw_mc_addr_mappings')  --  C: []
    __tablename__ = "sw_mc_addr_mapping"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcOriginalAddr": ("sw_mc_original_addr", "R"),
        "SwMcMappedAddr": ("sw_mc_mapped_addr", "R"),
        "SwMcAddrMappedSize": ("sw_mc_addr_mapped_size", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_mc_original_addr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_original_addr.rid"))
    sw_mc_original_addr: Mapped["SwMcOriginalAddr"] = relationship(single_parent=True)
    # REF
    sw_mc_mapped_addr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_mapped_addr.rid"))
    sw_mc_mapped_addr: Mapped["SwMcMappedAddr"] = relationship(single_parent=True)
    # REF
    sw_mc_addr_mapped_size_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_addr_mapped_size.rid"))
    sw_mc_addr_mapped_size: Mapped["SwMcAddrMappedSize"] = relationship(single_parent=True)
    # PARENT
    sw_mc_addr_mappings_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_addr_mappings.rid"))
    sw_mc_addr_mappings: Mapped["SwMcAddrMappings"] = relationship(back_populates="sw_mc_addr_mapping")


class SwUserGroups(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwUserGroup']
    __tablename__ = "sw_user_groups"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserGroup": ("sw_user_group", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_user_group: Mapped[list["SwUserGroup"]] = relationship(back_populates="sw_user_groups")


class SwCollectionSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_collection_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwCollections": ("sw_collections", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_collections_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collections.rid"))
    sw_collections: Mapped["SwCollections"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwCollectionRules(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCollectionRule']
    __tablename__ = "sw_collection_rules"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRule": ("sw_collection_rule", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_collection_rule: Mapped[list["SwCollectionRule"]] = relationship(back_populates="sw_collection_rules")


class SwCollectionRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCollectionRef']
    __tablename__ = "sw_collection_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRef": ("sw_collection_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_collection_ref: Mapped[list["SwCollectionRef"]] = relationship(back_populates="sw_collection_refs")


class SwCollectionRegexps(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCollectionRegexp']
    __tablename__ = "sw_collection_regexps"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionRegexp": ("sw_collection_regexp", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_collection_regexp: Mapped[list["SwCollectionRegexp"]] = relationship(back_populates="sw_collection_regexps")


class SwCollectionWildcards(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCollectionWildcard']
    __tablename__ = "sw_collection_wildcards"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionWildcard": ("sw_collection_wildcard", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_collection_wildcard: Mapped[list["SwCollectionWildcard"]] = relationship(back_populates="sw_collection_wildcards")


class SwCollectionRegexp(Base):
    # SIMPLE: SwCollectionRegexps == SR: False
    # P: ('SwCollectionRegexps', 'sw_collection_regexps')  --  C: []
    __tablename__ = "sw_collection_regexp"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_collection_regexps_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_regexps.rid"))
    sw_collection_regexps: Mapped["SwCollectionRegexps"] = relationship(back_populates="sw_collection_regexp")


class SwCollectionScripts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCollectionScript']
    __tablename__ = "sw_collection_scripts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCollectionScript": ("sw_collection_script", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_collection_script: Mapped[list["SwCollectionScript"]] = relationship(back_populates="sw_collection_scripts")


class SwCollectionWildcard(Base):
    # SIMPLE: SwCollectionWildcards == SR: False
    # P: ('SwCollectionWildcards', 'sw_collection_wildcards')  --  C: []
    __tablename__ = "sw_collection_wildcard"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_collection_wildcards_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_wildcards.rid"))
    sw_collection_wildcards: Mapped["SwCollectionWildcards"] = relationship(back_populates="sw_collection_wildcard")


class SwCollectionRule(Base):
    # SIMPLE: SwCollectionRules == SR: False
    # P: ('SwCollectionRules', 'sw_collection_rules')  --  C: []
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
        "SwCollectionRegexps": ("sw_collection_regexps", "R"),
        "SwCollectionWildcards": ("sw_collection_wildcards", "R"),
        "SwCollectionScripts": ("sw_collection_scripts", "R"),
    }
    ENUMS = {
        "scope": [
            "SW-ADDR-METHOD",
            "SW-AXIS-TYPE",
            "SW-BASE-TYPE",
            "SW-CALPRM",
            "SW-CLASS-INSTANCE",
            "SW-CODE-SYNTAX",
            "SW-COMPU-METHOD",
            "SW-DATA-CONSTR",
            "SW-FEATURE",
            "SW-INSTANCE",
            "SW-RECORD-LAYOUT",
            "SW-SYSTEMCONST",
            "SW-UNIT",
            "SW-VARIABLE",
            "ALL",
        ],
        "resolve_refs": ["RESOLVE-REFS", "NOT-RESOLVE-REFS"],
    }
    scope = StdString()
    resolve_refs = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_collection_regexps_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_regexps.rid"))
    sw_collection_regexps: Mapped["SwCollectionRegexps"] = relationship(single_parent=True)
    # REF
    sw_collection_wildcards_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_wildcards.rid"))
    sw_collection_wildcards: Mapped["SwCollectionWildcards"] = relationship(single_parent=True)
    # REF
    sw_collection_scripts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_scripts.rid"))
    sw_collection_scripts: Mapped["SwCollectionScripts"] = relationship(single_parent=True)
    # PARENT
    sw_collection_rules_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_rules.rid"))
    sw_collection_rules: Mapped["SwCollectionRules"] = relationship(back_populates="sw_collection_rule")


class SwCollectionScript(Base):
    # SIMPLE: SwCollectionScripts == SR: False
    # P: ('SwCollectionScripts', 'sw_collection_scripts')  --  C: []
    __tablename__ = "sw_collection_script"

    ATTRIBUTES = {
        "LANGUAGE": "language",
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    language = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_collection_scripts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_scripts.rid"))
    sw_collection_scripts: Mapped["SwCollectionScripts"] = relationship(back_populates="sw_collection_script")


class SwFeatureRefs(Base, HasSwFeatureRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_feature_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRef": ("sw_feature_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_feature_ref


class SwCsCollection(Base):
    # SIMPLE: SwCsCollections == SR: False
    # P: ('SwCsCollections', 'sw_cs_collections')  --  C: []
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
        "Category": ("category", "R"),
        "SwFeatureRef": ("sw_feature_ref", "R"),
        "Revision": ("revision", "R"),
        "SwCollectionRef": ("sw_collection_ref", "R"),
        "SwCsHistory": ("sw_cs_history", "R"),
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    sw_feature_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_ref.rid"))
    sw_feature_ref: Mapped["SwFeatureRef"] = relationship(single_parent=True)
    # REF
    revision_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("revision.rid"))
    revision: Mapped["Revision"] = relationship(single_parent=True)
    # REF
    sw_collection_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_ref.rid"))
    sw_collection_ref: Mapped["SwCollectionRef"] = relationship(single_parent=True)
    # REF
    sw_cs_history_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_history.rid"))
    sw_cs_history: Mapped["SwCsHistory"] = relationship(single_parent=True)
    # PARENT
    sw_cs_collections_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_collections.rid"))
    sw_cs_collections: Mapped["SwCsCollections"] = relationship(back_populates="sw_cs_collection")


class SwUnitRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwUnitRef']
    __tablename__ = "sw_unit_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUnitRef": ("sw_unit_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_unit_ref: Mapped[list["SwUnitRef"]] = relationship(back_populates="sw_unit_refs")


class SwCalprmRefs(Base, HasSwCalprmRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calprm_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalprmRef": ("sw_calprm_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_calprm_ref


class SwInstanceRefs(Base, HasSwInstanceRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_instance_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwInstanceRef": ("sw_instance_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_instance_ref


class SwClassInstanceRefs(Base, HasSwClassInstanceRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_class_instance_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwClassInstanceRef": ("sw_class_instance_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_class_instance_ref


class SwCompuMethodRefs(Base, HasSwCompuMethodRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_compu_method_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCompuMethodRef": ("sw_compu_method_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_compu_method_ref


class SwAddrMethodRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAddrMethodRef']
    __tablename__ = "sw_addr_method_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAddrMethodRef": ("sw_addr_method_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_addr_method_ref: Mapped[list["SwAddrMethodRef"]] = relationship(back_populates="sw_addr_method_refs")


class SwRecordLayoutRefs(Base, HasSwRecordLayoutRefs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_record_layout_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwRecordLayoutRef": ("sw_record_layout_refs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_record_layout_ref


class SwCodeSyntaxRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCodeSyntaxRef']
    __tablename__ = "sw_code_syntax_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCodeSyntaxRef": ("sw_code_syntax_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_code_syntax_ref: Mapped[list["SwCodeSyntaxRef"]] = relationship(back_populates="sw_code_syntax_refs")


class SwBaseTypeRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwBaseTypeRef']
    __tablename__ = "sw_base_type_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwBaseTypeRef": ("sw_base_type_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_base_type_ref: Mapped[list["SwBaseTypeRef"]] = relationship(back_populates="sw_base_type_refs")


class SwDataConstrRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwDataConstrRef']
    __tablename__ = "sw_data_constr_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwDataConstrRef": ("sw_data_constr_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_data_constr_ref: Mapped[list["SwDataConstrRef"]] = relationship(back_populates="sw_data_constr_refs")


class SwAxisTypeRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAxisTypeRef']
    __tablename__ = "sw_axis_type_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAxisTypeRef": ("sw_axis_type_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_axis_type_ref: Mapped[list["SwAxisTypeRef"]] = relationship(back_populates="sw_axis_type_refs")


class SwCollectionCont(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_collection_cont"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwFeatureRefs": ("sw_feature_refs", "R"),
        "SwUnitRefs": ("sw_unit_refs", "R"),
        "SwVariableRefs": ("sw_variable_refs", "R"),
        "SwCalprmRefs": ("sw_calprm_refs", "R"),
        "SwInstanceRefs": ("sw_instance_refs", "R"),
        "SwClassInstanceRefs": ("sw_class_instance_refs", "R"),
        "SwCompuMethodRefs": ("sw_compu_method_refs", "R"),
        "SwAddrMethodRefs": ("sw_addr_method_refs", "R"),
        "SwRecordLayoutRefs": ("sw_record_layout_refs", "R"),
        "SwCodeSyntaxRefs": ("sw_code_syntax_refs", "R"),
        "SwBaseTypeRefs": ("sw_base_type_refs", "R"),
        "SwSystemconstRefs": ("sw_systemconst_refs", "R"),
        "SwDataConstrRefs": ("sw_data_constr_refs", "R"),
        "SwAxisTypeRefs": ("sw_axis_type_refs", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_feature_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_refs.rid"))
    sw_feature_refs: Mapped["SwFeatureRefs"] = relationship(single_parent=True)
    # REF
    sw_unit_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_unit_refs.rid"))
    sw_unit_refs: Mapped["SwUnitRefs"] = relationship(single_parent=True)
    # REF
    sw_variable_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_refs.rid"))
    sw_variable_refs: Mapped["SwVariableRefs"] = relationship(single_parent=True)
    # REF
    sw_calprm_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_refs.rid"))
    sw_calprm_refs: Mapped["SwCalprmRefs"] = relationship(single_parent=True)
    # REF
    sw_instance_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_refs.rid"))
    sw_instance_refs: Mapped["SwInstanceRefs"] = relationship(single_parent=True)
    # REF
    sw_class_instance_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_class_instance_refs.rid"))
    sw_class_instance_refs: Mapped["SwClassInstanceRefs"] = relationship(single_parent=True)
    # REF
    sw_compu_method_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_method_refs.rid"))
    sw_compu_method_refs: Mapped["SwCompuMethodRefs"] = relationship(single_parent=True)
    # REF
    sw_addr_method_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_method_refs.rid"))
    sw_addr_method_refs: Mapped["SwAddrMethodRefs"] = relationship(single_parent=True)
    # REF
    sw_record_layout_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_refs.rid"))
    sw_record_layout_refs: Mapped["SwRecordLayoutRefs"] = relationship(single_parent=True)
    # REF
    sw_code_syntax_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_code_syntax_refs.rid"))
    sw_code_syntax_refs: Mapped["SwCodeSyntaxRefs"] = relationship(single_parent=True)
    # REF
    sw_base_type_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_refs.rid"))
    sw_base_type_refs: Mapped["SwBaseTypeRefs"] = relationship(single_parent=True)
    # REF
    sw_systemconst_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systemconst_refs.rid"))
    sw_systemconst_refs: Mapped["SwSystemconstRefs"] = relationship(single_parent=True)
    # REF
    sw_data_constr_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_constr_refs.rid"))
    sw_data_constr_refs: Mapped["SwDataConstrRefs"] = relationship(single_parent=True)
    # REF
    sw_axis_type_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_axis_type_refs.rid"))
    sw_axis_type_refs: Mapped["SwAxisTypeRefs"] = relationship(single_parent=True)


class SwCollection(Base):
    # SIMPLE: SwCollections == SR: False
    # P: ('SwCollections', 'sw_collections')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "Annotation": ("annotation", "R"),
        "SwCollectionRules": ("sw_collection_rules", "R"),
        "SwCollectionRefs": ("sw_collection_refs", "R"),
        "SwCollectionCont": ("sw_collection_cont", "R"),
    }
    ENUMS = {
        "root": ["ROOT", "NO-ROOT"],
    }
    root = StdString()
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    annotation_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("annotation.rid"))
    annotation: Mapped["Annotation"] = relationship(single_parent=True)
    # REF
    sw_collection_rules_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_rules.rid"))
    sw_collection_rules: Mapped["SwCollectionRules"] = relationship(single_parent=True)
    # REF
    sw_collection_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_refs.rid"))
    sw_collection_refs: Mapped["SwCollectionRefs"] = relationship(single_parent=True)
    # REF
    sw_collection_cont_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_cont.rid"))
    sw_collection_cont: Mapped["SwCollectionCont"] = relationship(single_parent=True)
    # PARENT
    sw_collections_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collections.rid"))
    sw_collections: Mapped["SwCollections"] = relationship(back_populates="sw_collection")


class SwCpuStandardRecordLayout(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_standard_record_layout"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwRecordLayoutRef": ("sw_record_layout_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_record_layout_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_record_layout_ref.rid"))
    sw_record_layout_ref: Mapped["SwRecordLayoutRef"] = relationship(single_parent=True)


class SwUserAccessCases(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwUserAccessCase']
    __tablename__ = "sw_user_access_cases"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserAccessCase": ("sw_user_access_case", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_user_access_case: Mapped[list["SwUserAccessCase"]] = relationship(back_populates="sw_user_access_cases")


class SystemUsers(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SystemUser']
    __tablename__ = "system_users"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SystemUser": ("system_user", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    system_user: Mapped[list["SystemUser"]] = relationship(back_populates="system_users")


class SwUserGroupRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwUserGroupRef']
    __tablename__ = "sw_user_group_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserGroupRef": ("sw_user_group_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_user_group_ref: Mapped[list["SwUserGroupRef"]] = relationship(back_populates="sw_user_group_refs")


class SystemUser(Base):
    # SIMPLE: SystemUsers == SR: False
    # P: ('SystemUsers', 'system_users')  --  C: []
    __tablename__ = "system_user"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    system_users_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("system_users.rid"))
    system_users: Mapped["SystemUsers"] = relationship(back_populates="system_user")


class SwUserGroup(Base):
    # SIMPLE: SwUserGroups == SR: False
    # P: ('SwUserGroups', 'sw_user_groups')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "TeamMemberRefs": ("team_member_refs", "R"),
        "SystemUsers": ("system_users", "R"),
        "SwUserGroupRefs": ("sw_user_group_refs", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    team_member_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("team_member_refs.rid"))
    team_member_refs: Mapped["TeamMemberRefs"] = relationship(single_parent=True)
    # REF
    system_users_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("system_users.rid"))
    system_users: Mapped["SystemUsers"] = relationship(single_parent=True)
    # REF
    sw_user_group_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_group_refs.rid"))
    sw_user_group_refs: Mapped["SwUserGroupRefs"] = relationship(single_parent=True)
    # PARENT
    sw_user_groups_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_groups.rid"))
    sw_user_groups: Mapped["SwUserGroups"] = relationship(back_populates="sw_user_group")


class SwUserGroupRef(Base):
    # SIMPLE: SwUserGroupRefs == SR: False
    # P: ('SwUserGroupRefs', 'sw_user_group_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_user_group_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_group_refs.rid"))
    sw_user_group_refs: Mapped["SwUserGroupRefs"] = relationship(back_populates="sw_user_group_ref")


class SwUserAccessDefintions(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwAccessDef']
    __tablename__ = "sw_user_access_defintions"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAccessDef": ("sw_access_def", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_access_def: Mapped[list["SwAccessDef"]] = relationship(back_populates="sw_user_access_defintions")


class SwUserAccessCaseRefs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwUserAccessCaseRef']
    __tablename__ = "sw_user_access_case_refs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserAccessCaseRef": ("sw_user_access_case_ref", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_user_access_case_ref: Mapped[list["SwUserAccessCaseRef"]] = relationship(back_populates="sw_user_access_case_refs")


class SwUserAccessCase(Base):
    # SIMPLE: SwUserAccessCases == SR: False
    # P: ('SwUserAccessCases', 'sw_user_access_cases')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwUserAccessCaseRefs": ("sw_user_access_case_refs", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_user_access_case_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_case_refs.rid"))
    sw_user_access_case_refs: Mapped["SwUserAccessCaseRefs"] = relationship(single_parent=True)
    # PARENT
    sw_user_access_cases_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_cases.rid"))
    sw_user_access_cases: Mapped["SwUserAccessCases"] = relationship(back_populates="sw_user_access_case")


class SwUserAccessCaseRef(Base):
    # SIMPLE: SwUserAccessCaseRefs == SR: False
    # P: ('SwUserAccessCaseRefs', 'sw_user_access_case_refs')  --  C: []
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
    ELEMENTS = {}
    TERMINAL = True
    id_ref = StdString()
    hytime = StdString()
    hynames = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_user_access_case_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_case_refs.rid"))
    sw_user_access_case_refs: Mapped["SwUserAccessCaseRefs"] = relationship(back_populates="sw_user_access_case_ref")


class SwUserRightSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_user_right_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwUserGroups": ("sw_user_groups", "R"),
        "SwUserAccessCases": ("sw_user_access_cases", "R"),
        "SwUserAccessDefintions": ("sw_user_access_defintions", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_user_groups_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_groups.rid"))
    sw_user_groups: Mapped["SwUserGroups"] = relationship(single_parent=True)
    # REF
    sw_user_access_cases_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_cases.rid"))
    sw_user_access_cases: Mapped["SwUserAccessCases"] = relationship(single_parent=True)
    # REF
    sw_user_access_defintions_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_defintions.rid"))
    sw_user_access_defintions: Mapped["SwUserAccessDefintions"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwAccessDef(Base):
    # SIMPLE: SwUserAccessDefintions == SR: False
    # P: ('SwUserAccessDefintions', 'sw_user_access_defintions')  --  C: []
    __tablename__ = "sw_access_def"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwUserGroupRef": ("sw_user_group_ref", "R"),
        "SwUserAccessCaseRef": ("sw_user_access_case_ref", "R"),
        "SwCollectionRef": ("sw_collection_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_user_group_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_group_ref.rid"))
    sw_user_group_ref: Mapped["SwUserGroupRef"] = relationship(single_parent=True)
    # REF
    sw_user_access_case_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_case_ref.rid"))
    sw_user_access_case_ref: Mapped["SwUserAccessCaseRef"] = relationship(single_parent=True)
    # REF
    sw_collection_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_ref.rid"))
    sw_collection_ref: Mapped["SwCollectionRef"] = relationship(single_parent=True)
    # PARENT
    sw_user_access_defintions_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_access_defintions.rid"))
    sw_user_access_defintions: Mapped["SwUserAccessDefintions"] = relationship(back_populates="sw_access_def")


class SwCalibrationMethods(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCalibrationMethod']
    __tablename__ = "sw_calibration_methods"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalibrationMethod": ("sw_calibration_method", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_calibration_method: Mapped[list["SwCalibrationMethod"]] = relationship(back_populates="sw_calibration_methods")


class SwCpuMemSegs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCpuMemSeg']
    __tablename__ = "sw_cpu_mem_segs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCpuMemSeg": ("sw_cpu_mem_seg", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_cpu_mem_seg: Mapped[list["SwCpuMemSeg"]] = relationship(back_populates="sw_cpu_mem_segs")


class SwCpuEpk(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_epk"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemProgramType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mem_program_type"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mem_type"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemAttr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mem_attr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemBaseAddr(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mem_base_addr"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemSize(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mem_size"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMemOffsets(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMemOffset']
    __tablename__ = "sw_mem_offsets"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMemOffset": ("sw_mem_offset", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mem_offset: Mapped[list["SwMemOffset"]] = relationship(back_populates="sw_mem_offsets")


class SwCpuMemSeg(Base):
    # SIMPLE: SwCpuMemSegs == SR: False
    # P: ('SwCpuMemSegs', 'sw_cpu_mem_segs')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwMemProgramType": ("sw_mem_program_type", "R"),
        "SwMemType": ("sw_mem_type", "R"),
        "SwMemAttr": ("sw_mem_attr", "R"),
        "SwMemBaseAddr": ("sw_mem_base_addr", "R"),
        "SwMemSize": ("sw_mem_size", "R"),
        "SwMemOffsets": ("sw_mem_offsets", "R"),
        "SwMcInstanceInterfaces": ("sw_mc_instance_interfaces", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_mem_program_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_program_type.rid"))
    sw_mem_program_type: Mapped["SwMemProgramType"] = relationship(single_parent=True)
    # REF
    sw_mem_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_type.rid"))
    sw_mem_type: Mapped["SwMemType"] = relationship(single_parent=True)
    # REF
    sw_mem_attr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_attr.rid"))
    sw_mem_attr: Mapped["SwMemAttr"] = relationship(single_parent=True)
    # REF
    sw_mem_base_addr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_base_addr.rid"))
    sw_mem_base_addr: Mapped["SwMemBaseAddr"] = relationship(single_parent=True)
    # REF
    sw_mem_size_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_size.rid"))
    sw_mem_size: Mapped["SwMemSize"] = relationship(single_parent=True)
    # REF
    sw_mem_offsets_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_offsets.rid"))
    sw_mem_offsets: Mapped["SwMemOffsets"] = relationship(single_parent=True)
    # REF
    sw_mc_instance_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_instance_interfaces.rid"))
    sw_mc_instance_interfaces: Mapped["SwMcInstanceInterfaces"] = relationship(single_parent=True)
    # PARENT
    sw_cpu_mem_segs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_mem_segs.rid"))
    sw_cpu_mem_segs: Mapped["SwCpuMemSegs"] = relationship(back_populates="sw_cpu_mem_seg")


class SwMemOffset(Base):
    # SIMPLE: SwMemOffsets == SR: False
    # P: ('SwMemOffsets', 'sw_mem_offsets')  --  C: []
    __tablename__ = "sw_mem_offset"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # PARENT
    sw_mem_offsets_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_offsets.rid"))
    sw_mem_offsets: Mapped["SwMemOffsets"] = relationship(back_populates="sw_mem_offset")


class SwCpuAddrEpk(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_addr_epk"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwAddrInfo": ("sw_addr_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_addr_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_addr_info.rid"))
    sw_addr_info: Mapped["SwAddrInfo"] = relationship(single_parent=True)


class SwCpuType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_type"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCpuCalibrationOffset(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_calibration_offset"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCpuNumberOfInterfaces(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_number_of_interfaces"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwCpuSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_cpu_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "ByteOrder": ("byte_order", "R"),
        "SwBaseTypeSize": ("sw_base_type_size", "R"),
        "SwMemAlignment": ("sw_mem_alignment", "R"),
        "SwCpuStandardRecordLayout": ("sw_cpu_standard_record_layout", "R"),
        "SwCpuMemSegs": ("sw_cpu_mem_segs", "R"),
        "SwCpuEpk": ("sw_cpu_epk", "R"),
        "SwCpuAddrEpk": ("sw_cpu_addr_epk", "R"),
        "SwCpuType": ("sw_cpu_type", "R"),
        "SwCpuCalibrationOffset": ("sw_cpu_calibration_offset", "R"),
        "SwCpuNumberOfInterfaces": ("sw_cpu_number_of_interfaces", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    byte_order_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("byte_order.rid"))
    byte_order: Mapped["ByteOrder"] = relationship(single_parent=True)
    # REF
    sw_base_type_size_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_size.rid"))
    sw_base_type_size: Mapped["SwBaseTypeSize"] = relationship(single_parent=True)
    # REF
    sw_mem_alignment_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_alignment.rid"))
    sw_mem_alignment: Mapped["SwMemAlignment"] = relationship(single_parent=True)
    # REF
    sw_cpu_standard_record_layout_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_standard_record_layout.rid"))
    sw_cpu_standard_record_layout: Mapped["SwCpuStandardRecordLayout"] = relationship(single_parent=True)
    # REF
    sw_cpu_mem_segs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_mem_segs.rid"))
    sw_cpu_mem_segs: Mapped["SwCpuMemSegs"] = relationship(single_parent=True)
    # REF
    sw_cpu_epk_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_epk.rid"))
    sw_cpu_epk: Mapped["SwCpuEpk"] = relationship(single_parent=True)
    # REF
    sw_cpu_addr_epk_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_addr_epk.rid"))
    sw_cpu_addr_epk: Mapped["SwCpuAddrEpk"] = relationship(single_parent=True)
    # REF
    sw_cpu_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_type.rid"))
    sw_cpu_type: Mapped["SwCpuType"] = relationship(single_parent=True)
    # REF
    sw_cpu_calibration_offset_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_calibration_offset.rid"))
    sw_cpu_calibration_offset: Mapped["SwCpuCalibrationOffset"] = relationship(single_parent=True)
    # REF
    sw_cpu_number_of_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_number_of_interfaces.rid"))
    sw_cpu_number_of_interfaces: Mapped["SwCpuNumberOfInterfaces"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwVcdCriteria(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwVcdCriterion']
    __tablename__ = "sw_vcd_criteria"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwVcdCriterion": ("sw_vcd_criterion", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_vcd_criterion: Mapped[list["SwVcdCriterion"]] = relationship(back_populates="sw_vcd_criteria")


class SwCalibrationMethodSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calibration_method_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwCalibrationMethods": ("sw_calibration_methods", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_calibration_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calibration_methods.rid"))
    sw_calibration_methods: Mapped["SwCalibrationMethods"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwCalibrationMethodVersions(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwCalibrationMethodVersion']
    __tablename__ = "sw_calibration_method_versions"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwCalibrationMethodVersion": ("sw_calibration_method_version", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_calibration_method_version: Mapped[list["SwCalibrationMethodVersion"]] = relationship(
        back_populates="sw_calibration_method_versions"
    )


class SwCalibrationMethod(Base):
    # SIMPLE: SwCalibrationMethods == SR: False
    # P: ('SwCalibrationMethods', 'sw_calibration_methods')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwCalibrationMethodVersions": ("sw_calibration_method_versions", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_calibration_method_versions_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_calibration_method_versions.rid")
    )
    sw_calibration_method_versions: Mapped["SwCalibrationMethodVersions"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)
    # PARENT
    sw_calibration_methods_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calibration_methods.rid"))
    sw_calibration_methods: Mapped["SwCalibrationMethods"] = relationship(back_populates="sw_calibration_method")


class SwCalibrationHandle(Base, HasVfs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_calibration_handle"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vf": ("vfs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vf


class SwCalibrationMethodVersion(Base):
    # SIMPLE: SwCalibrationMethodVersions == SR: False
    # P: ('SwCalibrationMethodVersions', 'sw_calibration_method_versions')  --  C: []
    __tablename__ = "sw_calibration_method_version"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "SwCalibrationHandle": ("sw_calibration_handle", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    sw_calibration_handle_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calibration_handle.rid"))
    sw_calibration_handle: Mapped["SwCalibrationHandle"] = relationship(single_parent=True)
    # PARENT
    sw_calibration_method_versions_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_calibration_method_versions.rid")
    )
    sw_calibration_method_versions: Mapped["SwCalibrationMethodVersions"] = relationship(
        back_populates="sw_calibration_method_version"
    )


class SwVcdSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_vcd_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwVcdCriteria": ("sw_vcd_criteria", "R"),
        "AddInfo": ("add_info", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_vcd_criteria_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criteria.rid"))
    sw_vcd_criteria: Mapped["SwVcdCriteria"] = relationship(single_parent=True)
    # REF
    add_info_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_info.rid"))
    add_info: Mapped["AddInfo"] = relationship(single_parent=True)


class SwSystem(Base):
    # SIMPLE: SwSystems == SR: False
    # P: ('SwSystems', 'sw_systems')  --  C: []
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
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwArchitecture": ("sw_architecture", "R"),
        "SwTestSpec": ("sw_test_spec", "R"),
        "SwDataDictionarySpec": ("sw_data_dictionary_spec", "R"),
        "SwComponentSpec": ("sw_component_spec", "R"),
        "SwInstanceSpec": ("sw_instance_spec", "R"),
        "SwCollectionSpec": ("sw_collection_spec", "R"),
        "SwUserRightSpec": ("sw_user_right_spec", "R"),
        "SwCpuSpec": ("sw_cpu_spec", "R"),
        "SwCalibrationMethodSpec": ("sw_calibration_method_spec", "R"),
        "SwVcdSpec": ("sw_vcd_spec", "R"),
        "AddSpec": ("add_spec", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_architecture_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_architecture.rid"))
    sw_architecture: Mapped["SwArchitecture"] = relationship(single_parent=True)
    # REF
    sw_test_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_test_spec.rid"))
    sw_test_spec: Mapped["SwTestSpec"] = relationship(single_parent=True)
    # REF
    sw_data_dictionary_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_data_dictionary_spec.rid"))
    sw_data_dictionary_spec: Mapped["SwDataDictionarySpec"] = relationship(single_parent=True)
    # REF
    sw_component_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_component_spec.rid"))
    sw_component_spec: Mapped["SwComponentSpec"] = relationship(single_parent=True)
    # REF
    sw_instance_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_spec.rid"))
    sw_instance_spec: Mapped["SwInstanceSpec"] = relationship(single_parent=True)
    # REF
    sw_collection_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_collection_spec.rid"))
    sw_collection_spec: Mapped["SwCollectionSpec"] = relationship(single_parent=True)
    # REF
    sw_user_right_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_user_right_spec.rid"))
    sw_user_right_spec: Mapped["SwUserRightSpec"] = relationship(single_parent=True)
    # REF
    sw_cpu_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cpu_spec.rid"))
    sw_cpu_spec: Mapped["SwCpuSpec"] = relationship(single_parent=True)
    # REF
    sw_calibration_method_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calibration_method_spec.rid"))
    sw_calibration_method_spec: Mapped["SwCalibrationMethodSpec"] = relationship(single_parent=True)
    # REF
    sw_vcd_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_spec.rid"))
    sw_vcd_spec: Mapped["SwVcdSpec"] = relationship(single_parent=True)
    # REF
    add_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("add_spec.rid"))
    add_spec: Mapped["AddSpec"] = relationship(single_parent=True)
    # PARENT
    sw_systems_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systems.rid"))
    sw_systems: Mapped["SwSystems"] = relationship(back_populates="sw_system")


class SwVcdCriterionPossibleValues(Base, HasVts):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_vcd_criterion_possible_values"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Vt": ("vts", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         vt


class SwVcdCriterion(Base):
    # SIMPLE: SwVcdCriteria == SR: False
    # P: ('SwVcdCriteria', 'sw_vcd_criteria')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwCalprmRef": ("sw_calprm_ref", "R"),
        "SwVariableRef": ("sw_variable_ref", "R"),
        "SwVcdCriterionPossibleValues": ("sw_vcd_criterion_possible_values", "R"),
        "SwCompuMethodRef": ("sw_compu_method_ref", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_calprm_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_calprm_ref.rid"))
    sw_calprm_ref: Mapped["SwCalprmRef"] = relationship(single_parent=True)
    # REF
    sw_variable_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_ref.rid"))
    sw_variable_ref: Mapped["SwVariableRef"] = relationship(single_parent=True)
    # REF
    sw_vcd_criterion_possible_values_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_vcd_criterion_possible_values.rid")
    )
    sw_vcd_criterion_possible_values: Mapped["SwVcdCriterionPossibleValues"] = relationship(single_parent=True)
    # REF
    sw_compu_method_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_compu_method_ref.rid"))
    sw_compu_method_ref: Mapped["SwCompuMethodRef"] = relationship(single_parent=True)
    # PARENT
    sw_vcd_criteria_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criteria.rid"))
    sw_vcd_criteria: Mapped["SwVcdCriteria"] = relationship(back_populates="sw_vcd_criterion")


class SwGlossary(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_glossary"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "Introduction": ("introduction", "R"),
        "AdminData": ("admin_data", "R"),
        "Ncoi1": ("ncoi_1", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    ncoi_1_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("ncoi_1.rid"))
    ncoi_1: Mapped["Ncoi1"] = relationship(single_parent=True)


class SwMcBaseTypes(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcBase']
    __tablename__ = "sw_mc_base_types"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcBaseType": ("sw_mc_base_type", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sw_mc_base_type
    sw_mc_base_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_base_type.rid"))
    sw_mc_base_type: Mapped[list["SwMcBaseType"]] = relationship()


class SwMcTpBlobLayout(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_tp_blob_layout"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcQpBlobLayout(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_qp_blob_layout"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcKpBlobLayout(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_kp_blob_layout"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcDpBlobLayout(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_dp_blob_layout"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcPaBlobLayout(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_pa_blob_layout"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcBlobLayouts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_blob_layouts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcTpBlobLayout": ("sw_mc_tp_blob_layout", "R"),
        "SwMcQpBlobLayout": ("sw_mc_qp_blob_layout", "R"),
        "SwMcKpBlobLayout": ("sw_mc_kp_blob_layout", "R"),
        "SwMcDpBlobLayout": ("sw_mc_dp_blob_layout", "R"),
        "SwMcPaBlobLayout": ("sw_mc_pa_blob_layout", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_mc_tp_blob_layout_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_tp_blob_layout.rid"))
    sw_mc_tp_blob_layout: Mapped["SwMcTpBlobLayout"] = relationship(single_parent=True)
    # REF
    sw_mc_qp_blob_layout_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_qp_blob_layout.rid"))
    sw_mc_qp_blob_layout: Mapped["SwMcQpBlobLayout"] = relationship(single_parent=True)
    # REF
    sw_mc_kp_blob_layout_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_kp_blob_layout.rid"))
    sw_mc_kp_blob_layout: Mapped["SwMcKpBlobLayout"] = relationship(single_parent=True)
    # REF
    sw_mc_dp_blob_layout_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_dp_blob_layout.rid"))
    sw_mc_dp_blob_layout: Mapped["SwMcDpBlobLayout"] = relationship(single_parent=True)
    # REF
    sw_mc_pa_blob_layout_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_pa_blob_layout.rid"))
    sw_mc_pa_blob_layout: Mapped["SwMcPaBlobLayout"] = relationship(single_parent=True)


class SwMcInterface(Base):
    # SIMPLE: SwMcInterfaceSpec == SR: False
    # P: ('SwMcInterfaceSpec', 'sw_mc_interface_spec')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwMcBlobLayouts": ("sw_mc_blob_layouts", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_mc_blob_layouts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_blob_layouts.rid"))
    sw_mc_blob_layouts: Mapped["SwMcBlobLayouts"] = relationship(single_parent=True)
    # PARENT
    sw_mc_interface_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_spec.rid"))
    sw_mc_interface_spec: Mapped["SwMcInterfaceSpec"] = relationship(back_populates="sw_mc_interface")


class SwMcInterfaceImpls(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcInterfaceImpl']
    __tablename__ = "sw_mc_interface_impls"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceImpl": ("sw_mc_interface_impl", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_interface_impl: Mapped[list["SwMcInterfaceImpl"]] = relationship(back_populates="sw_mc_interface_impls")


class SwMcBaseType(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwBaseTypeSize": ("sw_base_type_size", "R"),
        "SwCodedType": ("sw_coded_type", "R"),
        "SwMemAlignment": ("sw_mem_alignment", "R"),
        "ByteOrder": ("byte_order", "R"),
        "SwBaseTypeRef": ("sw_base_type_ref", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_base_type_size_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_size.rid"))
    sw_base_type_size: Mapped["SwBaseTypeSize"] = relationship(single_parent=True)
    # REF
    sw_coded_type_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_coded_type.rid"))
    sw_coded_type: Mapped["SwCodedType"] = relationship(single_parent=True)
    # REF
    sw_mem_alignment_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mem_alignment.rid"))
    sw_mem_alignment: Mapped["SwMemAlignment"] = relationship(single_parent=True)
    # REF
    byte_order_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("byte_order.rid"))
    byte_order: Mapped["ByteOrder"] = relationship(single_parent=True)
    # REF
    sw_base_type_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_base_type_ref.rid"))
    sw_base_type_ref: Mapped["SwBaseTypeRef"] = relationship(single_parent=True)


class SwMcCommunicationSpec(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_communication_spec"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Na": ("na", "R"),
        "Tbd": ("tbd", "R"),
        "Tbr": ("tbr", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "SwMcInterfaceSpec": ("sw_mc_interface_spec", "R"),
        "SwMcBaseTypes": ("sw_mc_base_types", "R"),
        "SwMcInterfaceImpls": ("sw_mc_interface_impls", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    na_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("na.rid"))
    na: Mapped["Na"] = relationship(single_parent=True)
    # REF
    tbd_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbd.rid"))
    tbd: Mapped["Tbd"] = relationship(single_parent=True)
    # REF
    tbr_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("tbr.rid"))
    tbr: Mapped["Tbr"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_spec.rid"))
    sw_mc_interface_spec: Mapped["SwMcInterfaceSpec"] = relationship(single_parent=True)
    # REF
    sw_mc_base_types_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_base_types.rid"))
    sw_mc_base_types: Mapped["SwMcBaseTypes"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_impls.rid"))
    sw_mc_interface_impls: Mapped["SwMcInterfaceImpls"] = relationship(single_parent=True)


class SwMcBlobValue(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_blob_value"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {}
    TERMINAL = True
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()


class SwMcGenericInterfaces(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcGenericInterface']
    __tablename__ = "sw_mc_generic_interfaces"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcGenericInterface": ("sw_mc_generic_interface", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_generic_interface: Mapped[list["SwMcGenericInterface"]] = relationship(back_populates="sw_mc_generic_interfaces")


class SwMcBlobEcuDeposit(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_blob_ecu_deposit"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwInstanceRef": ("sw_instance_ref", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_instance_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_ref.rid"))
    sw_instance_ref: Mapped["SwInstanceRef"] = relationship(single_parent=True)


class SwMcTpBlobConts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_tp_blob_conts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcBlobValue": ("sw_mc_blob_value", "R"),
        "SwMcBlobEcuDeposit": ("sw_mc_blob_ecu_deposit", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_mc_blob_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_blob_value.rid"))
    sw_mc_blob_value: Mapped["SwMcBlobValue"] = relationship(single_parent=True)
    # REF
    sw_mc_blob_ecu_deposit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_blob_ecu_deposit.rid"))
    sw_mc_blob_ecu_deposit: Mapped["SwMcBlobEcuDeposit"] = relationship(single_parent=True)


class SwMcInterfaceSources(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcInterfaceSource']
    __tablename__ = "sw_mc_interface_sources"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcInterfaceSource": ("sw_mc_interface_source", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_interface_source: Mapped[list["SwMcInterfaceSource"]] = relationship(back_populates="sw_mc_interface_sources")


class SwMcGenericInterface(Base):
    # SIMPLE: SwMcGenericInterfaces == SR: False
    # P: ('SwMcGenericInterfaces', 'sw_mc_generic_interfaces')  --  C: []
    __tablename__ = "sw_mc_generic_interface"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "ShortLabel": ("short_label", "R"),
        "Desc": ("_desc", "R"),
        "SwMcInterfaceDefaultSource": ("sw_mc_interface_default_source", "R"),
        "SwMcInterfaceAvlSources": ("sw_mc_interface_avl_sources", "R"),
        "SwMcKpBlobConts": ("sw_mc_kp_blob_conts", "R"),
        "SwMcDpBlobConts": ("sw_mc_dp_blob_conts", "R"),
        "SwMcPaBlobConts": ("sw_mc_pa_blob_conts", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    short_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_label.rid"))
    short_label: Mapped["ShortLabel"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_default_source_id: Mapped[typing.Optional[int]] = mapped_column(
        ForeignKey("sw_mc_interface_default_source.rid")
    )
    sw_mc_interface_default_source: Mapped["SwMcInterfaceDefaultSource"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_avl_sources_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_avl_sources.rid"))
    sw_mc_interface_avl_sources: Mapped["SwMcInterfaceAvlSources"] = relationship(single_parent=True)
    # REF
    sw_mc_kp_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_kp_blob_conts.rid"))
    sw_mc_kp_blob_conts: Mapped["SwMcKpBlobConts"] = relationship(single_parent=True)
    # REF
    sw_mc_dp_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_dp_blob_conts.rid"))
    sw_mc_dp_blob_conts: Mapped["SwMcDpBlobConts"] = relationship(single_parent=True)
    # REF
    sw_mc_pa_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_pa_blob_conts.rid"))
    sw_mc_pa_blob_conts: Mapped["SwMcPaBlobConts"] = relationship(single_parent=True)
    # PARENT
    sw_mc_generic_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_generic_interfaces.rid"))
    sw_mc_generic_interfaces: Mapped["SwMcGenericInterfaces"] = relationship(back_populates="sw_mc_generic_interface")


class SwMcFrames(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['SwMcFrame']
    __tablename__ = "sw_mc_frames"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcFrame": ("sw_mc_frame", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    sw_mc_frame: Mapped[list["SwMcFrame"]] = relationship(back_populates="sw_mc_frames")


class SwMcQpBlobConts(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "sw_mc_qp_blob_conts"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "SwMcBlobValue": ("sw_mc_blob_value", "R"),
        "SwMcBlobEcuDeposit": ("sw_mc_blob_ecu_deposit", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    sw_mc_blob_value_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_blob_value.rid"))
    sw_mc_blob_value: Mapped["SwMcBlobValue"] = relationship(single_parent=True)
    # REF
    sw_mc_blob_ecu_deposit_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_blob_ecu_deposit.rid"))
    sw_mc_blob_ecu_deposit: Mapped["SwMcBlobEcuDeposit"] = relationship(single_parent=True)


class SwMcInterfaceSource(Base):
    # SIMPLE: SwMcInterfaceSources == SR: False
    # P: ('SwMcInterfaceSources', 'sw_mc_interface_sources')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwRefreshTiming": ("sw_refresh_timing", "R"),
        "SwMcQpBlobConts": ("sw_mc_qp_blob_conts", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_refresh_timing_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_refresh_timing.rid"))
    sw_refresh_timing: Mapped["SwRefreshTiming"] = relationship(single_parent=True)
    # REF
    sw_mc_qp_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_qp_blob_conts.rid"))
    sw_mc_qp_blob_conts: Mapped["SwMcQpBlobConts"] = relationship(single_parent=True)
    # PARENT
    sw_mc_interface_sources_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_sources.rid"))
    sw_mc_interface_sources: Mapped["SwMcInterfaceSources"] = relationship(back_populates="sw_mc_interface_source")


class SwMcInterfaceImpl(Base):
    # SIMPLE: SwMcInterfaceImpls == SR: False
    # P: ('SwMcInterfaceImpls', 'sw_mc_interface_impls')  --  C: []
    __tablename__ = "sw_mc_interface_impl"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "AdminData": ("admin_data", "R"),
        "SwMcInterfaceRef": ("sw_mc_interface_ref", "R"),
        "SwMcTpBlobConts": ("sw_mc_tp_blob_conts", "R"),
        "SwMcGenericInterfaces": ("sw_mc_generic_interfaces", "R"),
        "SwMcInterfaceSources": ("sw_mc_interface_sources", "R"),
        "SwMcFrames": ("sw_mc_frames", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_ref.rid"))
    sw_mc_interface_ref: Mapped["SwMcInterfaceRef"] = relationship(single_parent=True)
    # REF
    sw_mc_tp_blob_conts_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_tp_blob_conts.rid"))
    sw_mc_tp_blob_conts: Mapped["SwMcTpBlobConts"] = relationship(single_parent=True)
    # REF
    sw_mc_generic_interfaces_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_generic_interfaces.rid"))
    sw_mc_generic_interfaces: Mapped["SwMcGenericInterfaces"] = relationship(single_parent=True)
    # REF
    sw_mc_interface_sources_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_sources.rid"))
    sw_mc_interface_sources: Mapped["SwMcInterfaceSources"] = relationship(single_parent=True)
    # REF
    sw_mc_frames_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_frames.rid"))
    sw_mc_frames: Mapped["SwMcFrames"] = relationship(single_parent=True)
    # PARENT
    sw_mc_interface_impls_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_interface_impls.rid"))
    sw_mc_interface_impls: Mapped["SwMcInterfaceImpls"] = relationship(back_populates="sw_mc_interface_impl")


class SwMcFrame(Base):
    # SIMPLE: SwMcFrames == SR: False
    # P: ('SwMcFrames', 'sw_mc_frames')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "AdminData": ("admin_data", "R"),
        "SwRefreshTiming": ("sw_refresh_timing", "R"),
        "SwVariableRefs": ("sw_variable_refs", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_refresh_timing_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_refresh_timing.rid"))
    sw_refresh_timing: Mapped["SwRefreshTiming"] = relationship(single_parent=True)
    # REF
    sw_variable_refs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_variable_refs.rid"))
    sw_variable_refs: Mapped["SwVariableRefs"] = relationship(single_parent=True)
    # PARENT
    sw_mc_frames_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_frames.rid"))
    sw_mc_frames: Mapped["SwMcFrames"] = relationship(back_populates="sw_mc_frame")


class SpecialData(Base, HasSdgs):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "special_data"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Sdg": ("sdgs", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         sdg


class MsrProcessingLog(
    Base,
    HasPs,
    HasVerbatims,
    HasFigures,
    HasFormulas,
    HasLists,
    HasDefLists,
    HasLabeledLists,
    HasNotes,
    HasTables,
    HasPrmss,
    HasMsrQueryP1s,
    HasTopic1s,
    HasMsrQueryTopic1s,
    HasChapters,
    HasMsrQueryChapters,
):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
    __tablename__ = "msr_processing_log"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "P": ("ps", "A"),
        "Verbatim": ("verbatims", "A"),
        "Figure": ("figures", "A"),
        "Formula": ("formulas", "A"),
        "List": ("_lists", "A"),
        "DefList": ("def_lists", "A"),
        "LabeledList": ("labeled_lists", "A"),
        "Note": ("notes", "A"),
        "Table": ("tables", "A"),
        "Prms": ("prmss", "A"),
        "MsrQueryP1": ("msr_query_p_1s", "A"),
        "Topic1": ("topic_1s", "A"),
        "MsrQueryTopic1": ("msr_query_topic_1s", "A"),
        "Chapter": ("chapters", "A"),
        "MsrQueryChapter": ("msr_query_chapters", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # NO_PA         p
    # ARR
    # NO_PA         verbatim
    # ARR
    # NO_PA         figure
    # ARR
    # NO_PA         formula
    # ARR
    # NO_PA         _list
    # ARR
    # NO_PA         def_list
    # ARR
    # NO_PA         labeled_list
    # ARR
    # NO_PA         note
    # ARR
    # NO_PA         table
    # ARR
    # NO_PA         prms
    # ARR
    # NO_PA         msr_query_p_1
    # ARR
    # NO_PA         topic_1
    # ARR
    # NO_PA         msr_query_topic_1
    # ARR
    # NO_PA         chapter
    # ARR
    # NO_PA         msr_query_chapter


class SdgCaption(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
    }
    _id = StdString()
    f_id_class = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)

    # N-I: Sdg


class DataFile(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
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
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "SymbolicFile": ("symbolic_file", "R"),
        "DataFile": ("data_file", "R"),
    }
    c = StdString()
    lc = StdString()
    s = StdString()
    si = StdString()
    t = StdString()
    ti = StdString()
    _view = StdString()
    # REF
    symbolic_file_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("symbolic_file.rid"))
    symbolic_file: Mapped["SymbolicFile"] = relationship(single_parent=True)
    # REF
    data_file_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("data_file.rid"))
    data_file: Mapped["DataFile"] = relationship(single_parent=True)


class SwInstanceTree(Base, HasSwInstances):
    # SIMPLE: SwInstanceSpec == SR: False
    # P: ('SwInstanceSpec', 'sw_instance_spec')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Desc": ("_desc", "R"),
        "Category": ("category", "R"),
        "SwInstanceTreeOrigin": ("sw_instance_tree_origin", "R"),
        "SwCsCollections": ("sw_cs_collections", "R"),
        "AdminData": ("admin_data", "R"),
        "SwCsHistory": ("sw_cs_history", "R"),
        "SwVcdCriterionValues": ("sw_vcd_criterion_values", "R"),
        "SwFeatureRef": ("sw_feature_ref", "R"),
        "SwInstance": ("sw_instances", "A"),
    }
    _id = StdString()
    f_id_class = StdString()
    f_namespace = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    desc_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("_desc.rid"))
    _desc: Mapped["Desc"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    sw_instance_tree_origin_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_tree_origin.rid"))
    sw_instance_tree_origin: Mapped["SwInstanceTreeOrigin"] = relationship(single_parent=True)
    # REF
    sw_cs_collections_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_collections.rid"))
    sw_cs_collections: Mapped["SwCsCollections"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    sw_cs_history_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_cs_history.rid"))
    sw_cs_history: Mapped["SwCsHistory"] = relationship(single_parent=True)
    # REF
    sw_vcd_criterion_values_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_vcd_criterion_values.rid"))
    sw_vcd_criterion_values: Mapped["SwVcdCriterionValues"] = relationship(single_parent=True)
    # REF
    sw_feature_ref_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_feature_ref.rid"))
    sw_feature_ref: Mapped["SwFeatureRef"] = relationship(single_parent=True)
    # ARR
    # NO_PA         sw_instance
    # PARENT
    sw_instance_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_instance_spec.rid"))
    sw_instance_spec: Mapped["SwInstanceSpec"] = relationship(back_populates="sw_instance_tree")

    # N-I: Sd


class MatchingDcis(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['MatchingDci']
    __tablename__ = "matching_dcis"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "MatchingDci": ("matching_dci", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    matching_dci: Mapped[list["MatchingDci"]] = relationship(back_populates="matching_dcis")


class Locs(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: ['Nameloc']
    __tablename__ = "locs"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Nameloc": ("nameloc", "A"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # ARR
    # PARENT-OBJ
    nameloc: Mapped[list["Nameloc"]] = relationship(back_populates="locs")


class MatchingDci(Base):
    # SIMPLE: MatchingDcis == SR: False
    # P: ('MatchingDcis', 'matching_dcis')  --  C: []
    __tablename__ = "matching_dci"

    ATTRIBUTES = {
        "VIEW": "_view",
        "S": "s",
        "T": "t",
        "SI": "si",
    }
    ELEMENTS = {
        "Label": ("label", "R"),
        "ShortLabel": ("short_label", "R"),
        "Url": ("url", "R"),
        "Remark": ("remark", "R"),
    }
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("label.rid"))
    label: Mapped["Label"] = relationship(single_parent=True)
    # REF
    short_label_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_label.rid"))
    short_label: Mapped["ShortLabel"] = relationship(single_parent=True)
    # REF
    url_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("url.rid"))
    url: Mapped["Url"] = relationship(single_parent=True)
    # REF
    remark_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("remark.rid"))
    remark: Mapped["Remark"] = relationship(single_parent=True)
    # PARENT
    matching_dcis_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("matching_dcis.rid"))
    matching_dcis: Mapped["MatchingDcis"] = relationship(back_populates="matching_dci")


class Msrsw(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
        "ShortName": ("short_name", "R"),
        "Category": ("category", "R"),
        "ProjectData": ("project_data", "R"),
        "AdminData": ("admin_data", "R"),
        "Introduction": ("introduction", "R"),
        "GeneralRequirements": ("general_requirements", "R"),
        "SwSystems": ("sw_systems", "R"),
        "SwMcCommunicationSpec": ("sw_mc_communication_spec", "R"),
        "SwGlossary": ("sw_glossary", "R"),
        "SpecialData": ("special_data", "R"),
        "MsrProcessingLog": ("msr_processing_log", "R"),
        "MatchingDcis": ("matching_dcis", "R"),
        "Locs": ("locs", "R"),
    }
    pubid = StdString()
    f_pubid = StdString()
    f_namespace = StdString()
    hytime = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    category_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("category.rid"))
    category: Mapped["Category"] = relationship(single_parent=True)
    # REF
    project_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("project_data.rid"))
    project_data: Mapped["ProjectData"] = relationship(single_parent=True)
    # REF
    admin_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("admin_data.rid"))
    admin_data: Mapped["AdminData"] = relationship(single_parent=True)
    # REF
    introduction_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("introduction.rid"))
    introduction: Mapped["Introduction"] = relationship(single_parent=True)
    # REF
    general_requirements_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("general_requirements.rid"))
    general_requirements: Mapped["GeneralRequirements"] = relationship(single_parent=True)
    # REF
    sw_systems_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_systems.rid"))
    sw_systems: Mapped["SwSystems"] = relationship(single_parent=True)
    # REF
    sw_mc_communication_spec_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_mc_communication_spec.rid"))
    sw_mc_communication_spec: Mapped["SwMcCommunicationSpec"] = relationship(single_parent=True)
    # REF
    sw_glossary_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("sw_glossary.rid"))
    sw_glossary: Mapped["SwGlossary"] = relationship(single_parent=True)
    # REF
    special_data_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("special_data.rid"))
    special_data: Mapped["SpecialData"] = relationship(single_parent=True)
    # REF
    msr_processing_log_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("msr_processing_log.rid"))
    msr_processing_log: Mapped["MsrProcessingLog"] = relationship(single_parent=True)
    # REF
    matching_dcis_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("matching_dcis.rid"))
    matching_dcis: Mapped["MatchingDcis"] = relationship(single_parent=True)
    # REF
    locs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("locs.rid"))
    locs: Mapped["Locs"] = relationship(single_parent=True)


class Nmlist(Base):
    # SIMPLE: [] == SR: False
    # P: []  --  C: []
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
    ELEMENTS = {}
    ENUMS = {
        "nametype": ["ENTITY", "ELEMENT"],
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
    # SIMPLE: Locs == SR: False
    # P: ('Locs', 'locs')  --  C: []
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
        "LongName": ("long_name", "R"),
        "ShortName": ("short_name", "R"),
        "Nmlist": ("nmlist", "R"),
    }
    _id = StdString()
    ext_id_class = StdString()
    f_id_class = StdString()
    hytime = StdString()
    _view = StdString()
    s = StdString()
    t = StdString()
    si = StdString()
    # REF
    long_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("long_name.rid"))
    long_name: Mapped["LongName"] = relationship(single_parent=True)
    # REF
    short_name_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("short_name.rid"))
    short_name: Mapped["ShortName"] = relationship(single_parent=True)
    # REF
    nmlist_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("nmlist.rid"))
    nmlist: Mapped["Nmlist"] = relationship(single_parent=True)
    # PARENT
    locs_id: Mapped[typing.Optional[int]] = mapped_column(ForeignKey("locs.rid"))
    locs: Mapped["Locs"] = relationship(back_populates="nameloc")


#
# Properties
#


#
#   Post-Header
#
@dataclass
class ElementMap:
    klass: Base
    attributes: dict[str, str] = field(default_factory=dict)
    enums: dict[str, list[str]] = field(default_factory=dict)
    elements: dict[str, str] = field(default_factory=dict)
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

        self._session = orm.Session(self._engine, autoflush=False, autocommit=False)
        self._metadata = Base.metadata
        # loadInitialData(Node)
        Base.metadata.create_all(self.engine)
        meta = MetaData(schema_version=CURRENT_SCHEMA_VERSION)
        self.session.add(meta)
        self.session.flush()
        self.session.commit()
        self._closed = False

    def __del__(self):
        pass
        # if not self._closed:
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

    ATTR = re.compile("(\\{.*?\\})?(.*)", re.DOTALL)

    def __init__(self, file_name: str, db: MSRSWDatabase, root_elem: str = ROOT_ELEMENT):
        self.validator = create_validator("cdf_v2.0.0.sl.dtd")
        self.schema_version = 0
        self.variant = "MSRSW"
        self.file_name = file_name
        self.db = db
        self.msrsw = etree.parse(file_name)  # nosec

        validate_result = self.validator.validate(self.msrsw)
        if not validate_result:
            print("Validation failed:", validate_result)
            print(self.validator.error_log)
        else:
            print("Validation passed")

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
            print(f"invalid tag: {tree.tag}")
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
                    print(f"unknown key: {key}")
                    continue
                attrib, elem_tp = obj.ELEMENTS[key]
                if self_ref and (attrib[:-1] == obj.__tablename__):
                    attrib = "children"
                if not hasattr(obj, attrib):
                    print(f"unknown attribute: {attrib}")
                    continue
                try:
                    axx = getattr(obj, attrib)
                    if elem_tp == "A":
                        setattr(obj, attrib, items)
                    else:
                        setattr(obj, attrib, items[0])
                except Exception as e:
                    print(str(e), obj)
                    print("	SELF-REF:", self_ref)
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
            category = msrsw.category.content if msrsw.category else ""
            meta.variant = category
        for attr, value in self.root.attrib.items():
            attr = self.get_attr(attr)
            if attr == "noNamespaceSchemaLocation":
                meta.xml_schema = value
