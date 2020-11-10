#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
"""

import toml

from asamint.mdf import MDFCreator

from asamint.utils import generate_filename

project_config = toml.load("example.apr")
experiment_config = toml.load("first_experiment.exp")
print(project_config, end = "\n\n")
print(experiment_config, end = "\n\n")

print(generate_filename(project_config, experiment_config, "mf4"))

mxx = MDFCreator(project_config = project_config, experiment_config = experiment_config)
