"""Adapter layer for external libraries."""

from asamint.adapters.a2l import open_a2l_database
from asamint.adapters.mdf import mdf_channels, open_mdf, save_mdf
from asamint.adapters.objutils import open_image
from asamint.adapters.xcp import McObject, compute_checksum
from asamint.adapters.xcp import create_master as create_xcp_master
from asamint.adapters.xcp import make_continuous_blocks

__all__ = [
    "create_xcp_master",
    "compute_checksum",
    "make_continuous_blocks",
    "McObject",
    "open_a2l_database",
    "open_image",
    "open_mdf",
    "save_mdf",
    "mdf_channels",
]
