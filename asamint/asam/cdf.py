#!/usr/bin/env python
# -*- coding: utf-8 -*-


from pprint import pprint

import lxml
from lxml.etree import (Element, ElementTree, DTD, SubElement, XMLSchema, parse, tounicode)
from lxml import etree
from pya2l import DB
import pya2l.model as model
from pya2l.api.inspect import ModCommon, _dissect_conversion

from asamint.utils import create_elem

#DOCTYPE = 'DOCTYPE MSRSW PUBLIC "-//ASAM//DTD MSR SOFTWARE DTD:V3.0.0:LAI:IAI:XML:MSRSW.DTD//EN"'

#CDF_DTD = "mdx_v1_0_0.sl.dtd"

CDF_EXTENSION = ".cdfx"

