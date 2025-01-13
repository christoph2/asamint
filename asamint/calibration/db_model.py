#!/usr/bin/env python
"""Model representing calibration data.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2021-2022 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import mmap
import re
import sqlite3

from sqlalchemy import Column, ForeignKey, create_engine, event, orm, types
from sqlalchemy.engine import Engine
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import as_declarative, declared_attr
from sqlalchemy.orm import backref, relationship

from asamint.logger import Logger


DB_EXTENSION = "caldb"

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


###########################################################
###########################################################
###########################################################


@as_declarative()
class Base:
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    rid = Column("rid", types.Integer, primary_key=True)
    comment = Column(types.Unicode(4096), default=None)


class CompareByPositionMixIn:
    """
    Enable sortability in user code.

    Implements basic comparison.
    """

    def __eq__(self, other):
        return self.position == other.position

    def __lt__(self, other):
        return self.position < other.position


def StdFloat(default=0.0):
    return Column(types.Float, default=default, nullable=False)


def StdShort(default=0, primary_key=False, unique=False):
    return Column(
        types.Integer,
        default=default,
        nullable=False,
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


def StdLong(default=0, primary_key=False, unique=False, nullable=False):
    return Column(
        types.Integer,
        default=default,
        nullable=nullable,
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


def StdString(default=0, primary_key=False, unique=False, index=False):
    return Column(
        types.VARCHAR(256),
        default=default,
        nullable=False,
        primary_key=primary_key,
        unique=unique,
        index=index,
    )


def StdIdent(default=0, primary_key=False, unique=False, index=False):
    return Column(
        types.VARCHAR(1025),
        default=default,
        nullable=False,
        primary_key=primary_key,
        unique=unique,
        index=index,
    )


################################################################################


class ValueAssociation(Base):

    __tablename__ = "value_association"

    discriminator = Column(types.String)

    __mapper_args__ = {"polymorphic_on": discriminator}


class Value(Base):

    association_rid = Column(types.Integer, ForeignKey("value_association.rid"))
    association = relationship("ValueAssociation", backref="raw_values", foreign_keys=[association_rid])
    # association = relationship("ValueAssociation", backref = "raw_values")
    parent = association_proxy("association", "parent")

    c_association_rid = Column(types.Integer, ForeignKey("value_association.rid"))
    c_association = relationship("ValueAssociation", backref="converted_values", foreign_keys=[c_association_rid])
    parent = association_proxy("c_association", "parent")

    float_value = StdFloat()
    text_value = StdString()

    def __init__(self, float_value=0.0, text_value=""):
        self.float_value = float_value
        self.text_value = text_value


class HasValues:
    @declared_attr
    def value_association_rid(cls):
        return Column(types.Integer, ForeignKey("value_association.rid"))

    @declared_attr
    def value_association(cls):
        name = cls.__name__
        discriminator = name.lower()

        assoc_cls = type(
            "%sValueAssociation" % name,
            (ValueAssociation,),
            dict(
                __tablename__=None,
                __mapper_args__={"polymorphic_identity": discriminator},
            ),
        )

        cls.raw_values = association_proxy(
            "value_association",
            "raw_values",
            creator=lambda raw_values: assoc_cls(raw_values=raw_values),
        )
        cls.converted_values = association_proxy(
            "value_association",
            "converted_values",
            creator=lambda converted_values: assoc_cls(converted_values=converted_values),
        )
        return relationship(assoc_cls, backref=backref("parent", uselist=False))


################################################################################


class BaseCharacteristic(Base):
    """ """

    __tablename__ = "base_characteristic"

    name = Column(types.Unicode(255), nullable=False, unique=True, index=True)
    category = Column(types.Unicode(255), nullable=False, index=True)
    display_identifier = Column(types.Unicode(255), nullable=True, index=False)
    _type = Column(types.String(256))

    __mapper_args__ = {
        "polymorphic_identity": "BaseCharacteristic",
        "polymorphic_on": _type,
    }


class AxisXPoint(Base):

    __tablename__ = "axis_x_point"

    value = StdFloat()

    def __init__(self, value=0.0):
        self.value = value

    __mapper_args__ = {"polymorphic_identity": "AxisXPoint"}
    axis_x_id = Column(types.Integer, ForeignKey("axis_x.rid"))


class AxisX(Base):

    __tablename__ = "axis_x"

    __mapper_args__ = {"polymorphic_identity": "AxisX"}
    values = relationship("AxisXPoint")


class AxisYPoint(Base):

    __tablename__ = "axis_y_point"

    value = StdFloat()

    def __init__(self, value=0.0):
        self.value = value

    __mapper_args__ = {"polymorphic_identity": "AxisYPoint"}
    axis_y_id = Column(types.Integer, ForeignKey("axis_y.rid"))


class AxisY(Base):

    __tablename__ = "axis_y"

    __mapper_args__ = {"polymorphic_identity": "AxisY"}
    values = relationship("AxisYPoint")


class AxisZPoint(Base):

    __tablename__ = "axis_z_point"

    value = StdFloat()

    def __init__(self, value=0.0):
        self.value = value

    __mapper_args__ = {"polymorphic_identity": "AxisZPoint"}
    axis_z_id = Column(types.Integer, ForeignKey("axis_z.rid"))


class AxisZ(Base):

    __tablename__ = "axis_z"

    __mapper_args__ = {"polymorphic_identity": "AxisZ"}
    values = relationship("AxisZPoint")


class Axis4Point(Base):

    __tablename__ = "axis_4_point"

    value = StdFloat()

    def __init__(self, value=0.0):
        self.value = value

    __mapper_args__ = {"polymorphic_identity": "Axis4Point"}
    axis_4_id = Column(types.Integer, ForeignKey("axis_4.rid"))


class Axis4(Base):

    __tablename__ = "axis_4"

    __mapper_args__ = {"polymorphic_identity": "Axis4"}
    values = relationship("Axis4Point")


class Axis5Point(Base):

    __tablename__ = "axis_5_point"

    value = StdFloat()

    def __init__(self, value=0.0):
        self.value = value

    __mapper_args__ = {"polymorphic_identity": "Axis5Point"}
    axis_5_id = Column(types.Integer, ForeignKey("axis_5.rid"))


class Axis5(Base):

    __tablename__ = "axis_5"

    __mapper_args__ = {"polymorphic_identity": "Axis5"}
    values = relationship("Axis5Point")


#####################


class Ascii(BaseCharacteristic):

    __tablename__ = "ascii"

    ascii_id = Column(
        types.Integer,
        ForeignKey("base_characteristic.rid"),
        primary_key=True,
    )
    __mapper_args__ = {"polymorphic_identity": "Ascii"}

    length = StdLong(nullable=False, default=0)
    ascii = Column(types.Unicode(255), nullable=True, default="")


class NDimContainer(HasValues, BaseCharacteristic):

    __tablename__ = "ndim_container"

    ndim_container_id = Column(
        types.Integer,
        ForeignKey("base_characteristic.rid"),
        primary_key=True,
    )
    __mapper_args__ = {"polymorphic_identity": "NDimContainer"}
    fnc_unit = Column(types.Unicode(255), nullable=True, default="")


@event.listens_for(Engine, "connect")
def set_sqlite3_pragmas(dbapi_connection, connection_record):
    dbapi_connection.create_function("REGEXP", 2, regexer)
    cursor = dbapi_connection.cursor()
    # cursor.execute("PRAGMA jornal_mode=WAL")
    cursor.execute("PRAGMA FOREIGN_KEYS=ON")
    cursor.execute(f"PRAGMA PAGE_SIZE={PAGE_SIZE}")
    cursor.execute(f"PRAGMA CACHE_SIZE={calculateCacheSize(CACHE_SIZE * 1025 * 1024)}")
    cursor.execute("PRAGMA SYNCHRONOUS=OFF")  # FULL
    cursor.execute("PRAGMA LOCKING_MODE=EXCLUSIVE")  # NORMAL
    cursor.execute("PRAGMA TEMP_STORE=MEMORY")  # FILE
    cursor.close()


class CalibrationDB:
    """ """

    def __init__(self, filename=":memory:", debug=False, logLevel="INFO", create=True):
        if filename == ":memory:":
            self.dbname = ""
        else:
            if not filename.lower().endswith(DB_EXTENSION):
                self.dbname = f"{filename}.{DB_EXTENSION}"
            else:
                self.dbname = filename
        self._engine = create_engine(
            f"sqlite:///{self.dbname}",
            echo=debug,
            connect_args={"detect_types": sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES},
            native_datetime=True,
        )
        self._session = orm.Session(self._engine, autoflush=False, autocommit=False)
        self._metadata = Base.metadata
        if create:
            Base.metadata.create_all(self.engine)
            self.session.flush()
            self.session.commit()
        self.logger = Logger(__name__, level=logLevel)

    @classmethod
    def _open_or_create(cls, filename=":memory:", debug=False, logLevel="INFO", create=True):
        """ """
        inst = cls(filename, debug, logLevel, create)
        return inst

    @classmethod
    def create(cls, filename=":memory:", debug=False, logLevel="INFO"):
        """ """
        return cls._open_or_create(filename, debug, logLevel, True)

    @classmethod
    def open(cls, filename=":memory:", debug=False, logLevel="INFO"):
        """ """
        return cls._open_or_create(filename, debug, logLevel, False)

    def close(self):
        """ """
        self.session.close()
        self.engine.dispose()

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
        """ """

    def commit_transaction(self):
        """ """

    def rollback_transaction(self):
        """ """
