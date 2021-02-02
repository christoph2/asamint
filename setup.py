#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""The setup script."""

from glob import glob
from setuptools import setup, find_packages

with open('README.rst') as readme_file:
    readme = readme_file.read()

with open('HISTORY.rst') as history_file:
    history = history_file.read()

requirements = ["asammdf", "objutils", "pya2ldb", "pyxcp", "babel", "lz4"]

setup_requirements = ['pytest-runner', ]

test_requirements = ['pytest', ]

setup(
    author="Christoph Schueler",
    author_email='cpu12.gems@googlemail.com',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: GPLv2',
        'Natural Language :: English',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    description="Adds high-level, convenience, integration related functions for several opensource projects.",
    install_requires=requirements,
    license="GPLv2",
    long_description=readme + '\n\n' + history,
    include_package_data=True,
    keywords='ASAM Autosar ECU Calibration Measurement',
    name='asamint',
    #packages=find_packages(include=['asamint']),
    packages=find_packages(),
    package_data = {
        "dtds": glob('asamint/data/dtds/*.*'),
        "templates": glob('asamint/data/templates/*.*'),
    },
    setup_requires=setup_requirements,
    test_suite='tests',
    tests_require=test_requirements,
    url='https://github.com/christoph2/asam_integration_package',
    version='0.1.0',
    zip_safe=False,
)
