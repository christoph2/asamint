#!/usr/bin/env python
# -*- coding: utf-8 -*-


from pprint import pprint

import lxml
from lxml.etree import (Element, ElementTree, DTD, SubElement, XMLSchema, parse, tounicode)


'''
COMPU_METHOD_RAT_FUNC = """<COMPU-METHOD>
  <SHORT-NAME>RatFuncCompu</SHORT-NAME>
  <CATEGORY>RAT-FUNC</CATEGORY>
  <UNIT-REF>rpm</UNIT-REF>
  <COMPU-PHYS-TO-INTERNAL>
    <COMPU-SCALES>    <!-- (2 + 3x)/4 -->
      <COMPU-SCALE>
        <COMPU-RATIONAL-COEFFS>
          <COMPU-NUMERATOR>    <!-- (2 + 3x) -->
            <V>2</V>
            <V>3</V>
          </COMPU-NUMERATOR>
          <COMPU-DENOMINATOR>    <!-- (4 + 0x) -->
            <V>4</V>
            <V>0</V>
          </COMPU-DENOMINATOR>
        </COMPU-RATIONAL-COEFFS>
      </COMPU-SCALE>
    </COMPU-SCALES>
  </COMPU-PHYS-TO-INTERNAL>
</COMPU-METHOD>
"""

COMPU_METHOD_IDENTICAL = """<COMPU-METHOD>
  <SHORT-NAME>PhysEqualIntRpm</SHORT-NAME>
  <CATEGORY>IDENTICAL</CATEGORY>
  <UNIT-REF>rpm</UNIT-REF>
  <COMPU-PHYS-TO-INTERNAL>
    <COMPU-SCALES>    <!-- (0 + 1x)/(1 + 0x) -->
      <COMPU-SCALE>
        <COMPU-RATIONAL-COEFFS>
          <COMPU-NUMERATOR>    <!-- (0 + 1x) -->
            <V>0</V>
            <V>1</V>
          </COMPU-NUMERATOR>
          <COMPU-DENOMINATOR>    <!-- (1 + 0x) -->
            <V>1</V>
            <V>0</V>
          </COMPU-DENOMINATOR>
        </COMPU-RATIONAL-COEFFS>
      </COMPU-SCALE>
    </COMPU-SCALES>
  </COMPU-PHYS-TO-INTERNAL>
</COMPU-METHOD>
"""

COMPU_METHOD_LINEAR = """<COMPU-METHOD>
  <SHORT-NAME>LinearCompu</SHORT-NAME>
  <CATEGORY>LINEAR</CATEGORY>
  <UNIT-REF>rpm</UNIT-REF>
  <COMPU-PHYS-TO-INTERNAL>
    <COMPU-SCALES>    <!-- (2 + 3x)/(1 + 0x) -->
      <COMPU-SCALE>
        <COMPU-RATIONAL-COEFFS>
          <COMPU-NUMERATOR>    <!-- (2 + 3x) -->
            <V>2</V>
            <V>3</V>
          </COMPU-NUMERATOR>
          <COMPU-DENOMINATOR>    <!-- (1 + 0x) -->
            <V>1</V>
            <V>0</V>
          </COMPU-DENOMINATOR>
        </COMPU-RATIONAL-COEFFS>
      </COMPU-SCALE>
    </COMPU-SCALES>
  </COMPU-PHYS-TO-INTERNAL>
</COMPU-METHOD>
"""

COMPU_METHOD_TAB_INTP = """<COMPU-METHOD>
  <SHORT-NAME>TabNoIntpCompu</SHORT-NAME>
  <CATEGORY>TAB-INTP</CATEGORY>
  <UNIT-REF>ms</UNIT-REF>
  <COMPU-PHYS-TO-INTERNAL>
    <COMPU-SCALES>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="CLOSED">0</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">100</UPPER-LIMIT>
        <COMPU-CONST>
          <V>0</V>
        </COMPU-CONST>
      </COMPU-SCALE>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="OPEN">100</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">200</UPPER-LIMIT>
        <COMPU-CONST>
          <V>1</V>
        </COMPU-CONST>
      </COMPU-SCALE>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="OPEN">200</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">255</UPPER-LIMIT>
        <COMPU-CONST>
          <V>2</V>
        </COMPU-CONST>
      </COMPU-SCALE>
    </COMPU-SCALES>
    <COMPU-DEFAULT-VALUE>
      <V>3</V>
    </COMPU-DEFAULT-VALUE>
  </COMPU-PHYS-TO-INTERNAL>
</COMPU-METHOD>

"""

COMPU_METHOD_TAB_NOINTP  = """<COMPU-METHOD>
  <SHORT-NAME>TabNoIntpCompu</SHORT-NAME>
  <CATEGORY>TAB-NOINTP</CATEGORY>
  <UNIT-REF>ms</UNIT-REF>
  <COMPU-PHYS-TO-INTERNAL>
    <COMPU-SCALES>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="CLOSED">0</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">100</UPPER-LIMIT>
        <COMPU-CONST>
          <V>0</V>
        </COMPU-CONST>
      </COMPU-SCALE>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="OPEN">100</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">200</UPPER-LIMIT>
        <COMPU-CONST>
          <V>1</V>
        </COMPU-CONST>
      </COMPU-SCALE>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="OPEN">200</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">255</UPPER-LIMIT>
        <COMPU-CONST>
          <V>2</V>
        </COMPU-CONST>
      </COMPU-SCALE>
    </COMPU-SCALES>
    <COMPU-DEFAULT-VALUE>
      <V>3</V>
    </COMPU-DEFAULT-VALUE>
  </COMPU-PHYS-TO-INTERNAL>
</COMPU-METHOD>

"""

COMPU_METHOD_TEXTTABLE = """<COMPU-METHOD>
  <SHORT-NAME>TextTableCompu</SHORT-NAME>
  <CATEGORY>TEXTTABLE</CATEGORY>
  <COMPU-INTERNAL-TO-PHYS>
    <COMPU-SCALES>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="CLOSED">1</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">1</UPPER-LIMIT>
        <COMPU-CONST>
          <VT>No Turbo (state one)</VT>
        </COMPU-CONST>
      </COMPU-SCALE>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="CLOSED">2</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">2</UPPER-LIMIT>
        <COMPU-CONST>
          <VT>Turbo off (state two)</VT>
        </COMPU-CONST>
      </COMPU-SCALE>
      <COMPU-SCALE>
        <LOWER-LIMIT INTERVAL-TYPE="CLOSED">3</LOWER-LIMIT>
        <UPPER-LIMIT INTERVAL-TYPE="CLOSED">3</UPPER-LIMIT>
        <COMPU-CONST>
          <VT>Turbo on (state three)</VT>
        </COMPU-CONST>
      </COMPU-SCALE>
    </COMPU-SCALES>
    <COMPU-DEFAULT-VALUE>
      <VT>undefined turbo state</VT>
    </COMPU-DEFAULT-VALUE>
  </COMPU-INTERNAL-TO-PHYS>
</COMPU-METHOD>
'''

class Creator:

    def __init__(self, session_obj):
        self.session_obj = session_obj
        self.root = self._toplevel_boilerplate()
        self.tree = ElementTree(self.root)


    def _toplevel_boilerplate(self):
        root = Element("COMPU-METHOD")

        sn = SubElement(root, "SHORT-NAME")
        sn.text = "TabNoIntpCompu"
        cat = SubElement(root, "CATEGORY")
        cat.text = "TAB-NOINTP"
        unit = SubElement(root, "UNIT-REF")
        unit.text = "ms"

        cpti = SubElement(root, "COMPU-PHYS-TO-INTERNAL")

        return root


cr = Creator(None)
print(tounicode(cr.tree, pretty_print = True))

