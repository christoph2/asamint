#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import subprocess

from distutils.core import setup, Extension

from pybind11.setup_helpers import Pybind11Extension, build_ext # noqa: E402

INCLUDE_DIRS = subprocess.getoutput('pybind11-config --include')

os.environ ["CFLAGS"] = ''

PKG_NAME = "rekorder"
EXT_NAMES = ['rekorder']
__version__ = "0.0.1"

ext_modules = [
    Pybind11Extension(
        EXT_NAMES[0],
        include_dirs = [INCLUDE_DIRS],
        sources = [ "wrap.cpp"],
        define_macros = [('EXTENSION_NAME', EXT_NAMES[0])],
        extra_compile_args = ['-O3', '-Wall', '-Weffc++', '-std=c++17'],
    ),
]

setup(
    name = PKG_NAME,
    version = "0.0.1",
    author = "Christoph Schueler",
    description = "Example",
    ext_modules = ext_modules,
    cmdclass = {"build_ext": build_ext},
)

