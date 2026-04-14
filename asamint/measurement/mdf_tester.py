import numpy as np
import asammdf

FN = r"C:\Users\Public\Documents\Vector\CANape Examples 23\RaceTrackDemo\MeasurementFiles\SummitPoint_09637700.mf4"


def traverse(elem):
    if isinstance(elem, asammdf.mdf.MDF):
        for grp in elem.groups:
            traverse(grp)
    elif isinstance(elem, asammdf.blocks.mdf_common.Group):
        for chn in elem.channels:
            traverse(chn)
    elif isinstance(elem, asammdf.blocks.v4_blocks.Channel):
        pass


mf = asammdf.MDF(FN)
traverse(mf)

# busy_wait(std::chrono::microseconds(84));
