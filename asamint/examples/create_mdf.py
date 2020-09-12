#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
"""

import toml

from asammdf import MDF
from asamint.mdf import MDFCreator
from asamint.config import readConfiguration
#import asamint
#from pya2l import DB

mdf = MDF(version = "4.10")

project_config = toml.load("example.apr")
experiment_config = toml.load("first_experiment.epj")
print(project_config, end = "\n\n")
print(experiment_config, end = "\n\n")
mxx = MDFCreator(mdf_obj = mdf, project_config = project_config, experiment_config = experiment_config)
