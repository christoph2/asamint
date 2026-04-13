import pytest
import numpy as np
import logging
from unittest.mock import MagicMock


def _bypass_init(self, *args, **kws):
    """Lightweight init that skips config/A2L/XCP setup."""
    self.config = MagicMock()
    self.logger = logging.getLogger("test_strict_mode")
    self.experiment_config = {}
    self.measurement_variables = []
    self._mdf_obj = MagicMock()


def _make_data_need_trim():
    # fast timestamps (ns) length 100, slow signal length 9 so requires trim (since 100/9 is not integer)
    data = {
        "timestamp0": np.arange(0, 100 * 10_000_000, 10_000_000, dtype=np.int64),
        "fast": np.linspace(0, 1, 100),
        "slow": np.linspace(0, 1, 9),
    }
    return data


def _make_data_need_synth():
    # signal with no matching timestamps at all
    data = {
        "some_sig": np.linspace(0, 1, 7),
    }
    return data


def test_strict_no_trim_raises(monkeypatch):
    from asamint.asam import AsamMC
    from asamint.mdf import MDFCreator

    monkeypatch.setattr(AsamMC, "__init__", _bypass_init)
    creator = MDFCreator()

    class Dummy:
        def __init__(self, name):
            self.name = name
            self.longIdentifier = name
            self.compuMethod = "NO_COMPU_METHOD"
            self.bitMask = None
            self.bitOperation = None

    creator.measurement_variables = [Dummy("fast"), Dummy("slow")]
    data = _make_data_need_trim()

    with pytest.raises(ValueError):
        creator.save_measurements("/tmp/strict_no_trim.mf4", data=data, strict_no_trim=True)


def test_strict_no_synth_raises(monkeypatch):
    from asamint.asam import AsamMC
    from asamint.mdf import MDFCreator

    monkeypatch.setattr(AsamMC, "__init__", _bypass_init)
    creator = MDFCreator()

    class Dummy:
        def __init__(self, name):
            self.name = name
            self.longIdentifier = name
            self.compuMethod = "NO_COMPU_METHOD"
            self.bitMask = None
            self.bitOperation = None

    creator.measurement_variables = [Dummy("some_sig")]
    data = _make_data_need_synth()

    with pytest.raises(ValueError):
        creator.save_measurements("/tmp/strict_no_synth.mf4", data=data, strict_no_synth=True)
