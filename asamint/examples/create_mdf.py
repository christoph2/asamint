#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
"""

#from asammdf import MDF, Signal
from asamint.mdf import MDFCreator
from asamint.config import readConfiguration
#import asamint
#from pya2l import DB

mdf = MDF(version = "4.10")
create_mdf(session_obj = session, mdf_obj = mdf, mdf_filename = "ASAP2_Demo_V161.mf4")

project_config = readConfiguration("example.apj")
experiment_config = readConfiguration("first_experiment.epj")

mxx = MDFCreator(mdf_obj = mdf, project_config = project_config, experiment_config = experiment_config)
