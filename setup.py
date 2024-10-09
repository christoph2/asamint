#!/usr/bin/env python
"""The setup script."""
import os
from glob import glob

from setuptools import find_packages, setup

with open("docs/README.rst") as readme_file:
    readme = readme_file.read()

with open("HISTORY.rst") as history_file:
    history = history_file.read()


with open(os.path.join("asamint", "version.py")) as f:
    for line in f:
        if line.startswith("__version__"):
            version = line.split("=")[-1].strip().strip('"')
            break


requirements = [
    "asammdf",
    "objutils",
    "pya2ldb",
    "pyxcp",
    "babel",
    "lz4",
    "numpy",
    "sortedcontainers",
]

setup_requirements = [
    "pytest-runner",
]

test_requirements = [
    "pytest",
]

setup(
    author="Christoph Schueler",
    author_email="cpu12.gems@googlemail.com",
    classifiers=[
        "Development Status :: 2 - Pre-Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GPLv2",
        "Natural Language :: English",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
    ],
    description="Adds high-level, convenience, integration related functions for several opensource projects.",
    install_requires=requirements,
    license="GPLv2",
    long_description=readme + "\n\n" + history,
    include_package_data=True,
    keywords="ASAM Autosar ECU Calibration Measurement",
    name="asamint",
    # packages=find_packages(include=['asamint']),
    packages=find_packages(),
    package_data={
        "dtds": glob("asamint/data/dtds/*.*"),
        "templates": glob("asamint/data/templates/*.*"),
    },
    entry_points={
        "console_scripts": ["xcp-log = asamint.scripts.xcp_log:main"],
    },
    setup_requires=setup_requirements,
    test_suite="tests",
    tests_require=test_requirements,
    url="https://github.com/christoph2/asamint",
    version=version,
    zip_safe=False,
)
