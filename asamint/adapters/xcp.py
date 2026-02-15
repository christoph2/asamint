from __future__ import annotations

from typing import Any


def create_master(xcp_config: Any) -> Any:
    """Instantiate a pyXCP Master using the provided configuration."""

    from pyxcp.master import Master

    return Master(xcp_config.transport.layer, config=xcp_config)
