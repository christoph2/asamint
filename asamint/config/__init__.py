#!/usr/bin/env python

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2024-2025 by Christoph Schueler <cpu12.gems.googlemail.com>

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

import io
import logging
import sys
import typing
from pathlib import Path

from pyxcp import config as pyxcp_config
from rich.logging import RichHandler
from rich.prompt import Confirm
from traitlets import Bool, Dict, Enum, List, Unicode
from traitlets.config import Application, Configurable, Instance, default


class General(Configurable):
    """ """

    author = Unicode(default_value="", help="Author of the project").tag(config=True)
    company = Unicode(default_value="", help="Company of the project").tag(config=True)
    department = Unicode(default_value="", help="Department of the project").tag(config=True)
    project = Unicode(default_value="", help="Project name").tag(config=True)
    shortname = Unicode(
        default_value="",
        help="Short name of the project (Contributes to filename generation)",
    ).tag(config=True)
    pyxcp_config_file = Unicode(default_value="pyxcp_conf.py", help="pyXCP config file").tag(config=True)
    a2l_file = Unicode(default_value="", help="Input A2L file").tag(config=True)
    a2l_encoding = Unicode(default_value="latin-1", help="Input A2L file encoding").tag(config=True)
    a2l_dynamic = Bool(False, help="Enable dynamic (via XCP) A2L parsing").tag(config=True)
    master_hexfile = Unicode(default_value="", help="Master HEX file").tag(config=True)
    master_hexfile_type = Enum(values=["ihex", "srec"], default_value="ihex", help="Choose HEX file type").tag(config=True)
    mdf_version = Unicode(default="4.20", help="Version used to write MDF files.").tag(config=True)
    experiments = List(
        trait=Unicode(),
        default_value=[],
        allow_none=True,
        help="""
    Measurement and calibration experiments associated with this project (configuration file names).""",
    ).tag(config=True)


class ProfileCreate(Application):
    description = "\nCreate a new profile"

    dest_file = Unicode(default_value=None, allow_none=True, help="destination file name").tag(config=True)
    aliases = Dict(  # type:ignore[assignment]
        dict(
            d="ProfileCreate.dest_file",
            o="ProfileCreate.dest_file",
        )
    )

    def start(self):
        pyxcp = self.parent.parent
        if self.dest_file:
            dest = Path(self.dest_file)
            if dest.exists():
                if not Confirm.ask(f"Destination file [green]{dest.name!r}[/green] already exists. Do you want to overwrite it?"):
                    print("Aborting...")
                    self.exit(1)
            with dest.open("w", encoding="latin1") as out_file:
                pyxcp.generate_config_file(out_file)
        else:
            pyxcp.generate_config_file(sys.stdout)


class ProfileApp(Application):
    subcommands = Dict(
        dict(
            create=(ProfileCreate, ProfileCreate.description.splitlines()[0]),
        )
    )

    def start(self):
        if self.subapp is None:
            print(f"No subcommand specified. Must specify one of: {self.subcommands.keys()}")
            print()
            self.print_description()
            self.print_subcommands()
            self.exit(1)
        else:
            self.subapp.start()


class XCP(Configurable):
    classes = List([pyxcp_config.General, pyxcp_config.Transport])

    def __init__(self, **kws):
        super().__init__(**kws)
        self.general = pyxcp_config.General(config=self.config, parent=self)
        self.transport = pyxcp_config.Transport(parent=self)


class Asamint(Application):
    description = "ASAMInt application"
    config_file = Unicode(default_value="asamint_conf.py", help="base name of config file").tag(config=True)

    classes = List([General, XCP])

    subcommands = dict(
        profile=(
            ProfileApp,
            """
            Profile stuff
            """.strip(),
        )
    )

    def start(self):
        if self.subapp:
            self.subapp.start()
            exit(2)
        else:
            self._read_configuration(self.config_file)
            self._setup_logger()

    def _setup_logger(self):
        # Remove any handlers installed by `traitlets`.
        for hdl in self.log.handlers:
            self.log.removeHandler(hdl)

        # formatter = logging.Formatter(fmt=self.log_format, datefmt=self.log_datefmt)
        rich_handler = RichHandler(
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            log_time_format=self.log_datefmt,
            level=self.log_level,
        )
        # rich_handler.setFormatter(formatter)
        self.log.addHandler(rich_handler)

    def initialize(self, argv=None):
        from asamint import __version__ as pyxcp_version

        Asamint.version = pyxcp_version
        Asamint.name = Path(sys.argv[0]).name
        self.parse_command_line(argv[1:])
        self.log.debug(f"asamint version: {self.version}")

    def _read_configuration(self, file_name: str, emit_warning: bool = True) -> None:
        self.read_configuration_file(file_name, emit_warning)
        self.general = General(config=self.config, parent=self)
        self.xcp = XCP(config=self.config, parent=self)

    def read_configuration_file(self, file_name: str, emit_warning: bool = True):
        self.legacy_config: bool = False

        pth = Path(file_name)
        if not pth.exists():
            raise FileNotFoundError(f"Configuration file {file_name!r} does not exist.")
        suffix = pth.suffix.lower()
        if suffix == ".py":
            self.load_config_file(pth)
        else:
            raise TypeError("Configuration file must be a Python (.py) file.")
        # return cfg

    flags = Dict(  # type:ignore[assignment]
        dict(
            debug=({"Asamint": {"log_level": 10}}, "Set loglevel to DEBUG"),
        )
    )

    @default("log_level")
    def _default_value(self):
        return logging.INFO  # traitlets default is logging.WARN

    aliases = Dict(  # type:ignore[assignment]
        dict(
            c="Asamint.config_file",  # Application
            log_level="Asamint.log_level",
            l="Asamint.log_level",
        )
    )

    def _iterate_config_class(
        self,
        klass,
        class_names: list[str],
        config,
        out_file: io.IOBase = sys.stdout,
    ) -> None:
        sub_classes = []
        class_path = ".".join(class_names)
        print(
            f"""\n# ------------------------------------------------------------------------------
    # {class_path} configuration
    # ------------------------------------------------------------------------------""",
            end="\n\n",
            file=out_file,
        )
        if hasattr(klass, "classes"):
            kkk = klass.classes
            if hasattr(kkk, "default"):
                # print("\tKLASS:", klass, kkk.default())
                sub_classes.extend(kkk.default())
                # if class_names[-1] not in ("Asamint"):
                #    sub_classes.extend(kkk.default())
        for name, tr in klass.class_own_traits().items():
            md = tr.metadata
            if md.get("config"):
                help = md.get("help", "").lstrip()
                commented_lines = "\n".join([f"# {line}" for line in help.split("\n")])
                print(f"#{commented_lines}", file=out_file)
                value = tr.default()
                if isinstance(tr, Instance) and tr.__class__.__name__ not in (
                    "Dict",
                    "List",
                ):
                    continue
                if isinstance(tr, Enum):
                    print(f"#  Choices: {tr.info()}", file=out_file)
                else:
                    print(f"#  Type: {tr.info()}", file=out_file)
                print(f"#  Default: {value!r}", file=out_file)
                if name in config:
                    cfg_value = config[name]
                    print(
                        f"c.{class_path!s}.{name!s} = {cfg_value!r}",
                        end="\n\n",
                        file=out_file,
                    )
                else:
                    print(
                        f"#  c.{class_path!s}.{name!s} = {value!r}",
                        end="\n\n",
                        file=out_file,
                    )
        if class_names is None:
            class_names = []
        for sub_klass in sub_classes:
            self._iterate_config_class(
                sub_klass,
                class_names + [sub_klass.__name__],
                config=config.get(sub_klass.__name__, {}),
                out_file=out_file,
            )

    def generate_config_file(self, file_like: io.IOBase, config=None) -> None:
        print("#", file=file_like)
        print("# Configuration file for Asamint.", file=file_like)
        print("#", file=file_like)
        print("c = get_config()  # noqa", end="\n\n", file=file_like)

        for klass in self._classes_with_config_traits():
            self._iterate_config_class(
                klass,
                [klass.__name__],
                config=self.config.get(klass.__name__, {}) if config is None else {},
                out_file=file_like,
            )


application: typing.Optional[Asamint] = None


def create_application(
    options: typing.Optional[list[typing.Any]] = None,
) -> Asamint:
    global application
    if options is None:
        options = []
    if application is not None:
        return application
    application = Asamint()
    application.initialize(sys.argv)
    application.start()
    return application


def get_application(
    options: typing.Optional[list[typing.Any]] = None,
) -> Asamint:
    if options is None:
        options = []
    global application
    if application is None:
        application = create_application(options)
    return application
