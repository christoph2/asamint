from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from asamint import calibration as calibration_module


class _RecordingXcpMaster:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def setCalPage(self, mode: int, logical_segment: int, logical_page: int) -> None:
        self.calls.append(("setCalPage", (mode, logical_segment, logical_page)))

    def setMta(self, address: int) -> None:
        self.calls.append(("setMta", (address,)))

    def pull(self, size: int) -> bytes:
        self.calls.append(("pull", (size,)))
        return bytes([0xAA]) * size

    def push(self, data: bytes) -> None:
        self.calls.append(("push", (data,)))


def _make_segment(
    *,
    name: str = "MemorySegment",
    memory_type_name: str = "FLASH",
    address: int = 0x16000,
    size: int = 8,
    pages: list[list[Any]] | None = None,
) -> SimpleNamespace:
    if_data = []
    if pages is not None:
        if_data = [{"XCP": [{"SEGMENT": [0, 2, 0, 0, 0, {"PAGE": pages}]}]}]
    return SimpleNamespace(
        name=name,
        memoryType=SimpleNamespace(name=memory_type_name),
        address=address,
        size=size,
        if_data=if_data,
    )


def _make_calibration_data(tmp_path: Path) -> calibration_module.CalibrationData:
    instance = calibration_module.CalibrationData.__new__(
        calibration_module.CalibrationData
    )
    instance.asam_mc = SimpleNamespace(
        mod_par=None,
        session=object(),
        sub_dir=lambda _name: tmp_path,
    )
    instance.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    instance.check_epk_xcp = lambda xcp_master: None
    return instance


def test_upload_calram_uses_if_data_page_selection(tmp_path: Path, monkeypatch) -> None:
    calibration_data = _make_calibration_data(tmp_path)
    paged_segment = _make_segment(
        pages=[
            [
                0,
                "ECU_ACCESS_DONT_CARE",
                "XCP_READ_ACCESS_WITH_ECU_ONLY",
                "XCP_WRITE_ACCESS_NOT_ALLOWED",
            ],
            [
                1,
                "ECU_ACCESS_DONT_CARE",
                "XCP_READ_ACCESS_WITH_ECU_ONLY",
                "XCP_WRITE_ACCESS_WITH_ECU_ONLY",
            ],
        ]
    )
    calibration_data.asam_mc.mod_par = SimpleNamespace(memorySegments=[paged_segment])
    xcp_master = _RecordingXcpMaster()
    written: dict[str, Any] = {}

    monkeypatch.setattr(
        calibration_module,
        "current_timestamp",
        lambda: "20260326_131800",
    )

    def _fake_dump(
        file_type: str, outf: Any, image: Any, row_length: int = 0, **_kwargs: Any
    ) -> None:
        written["file_type"] = file_type
        written["row_length"] = row_length
        written["sections"] = list(image.sections)
        outf.write(b"ok")

    monkeypatch.setattr(calibration_module, "dump", _fake_dump)

    image = calibration_module.CalibrationData.upload_calram(
        calibration_data,
        xcp_master,
    )

    assert image is not None
    assert xcp_master.calls[:3] == [
        ("setCalPage", (0x83, 2, 1)),
        ("setMta", (0x16000,)),
        ("pull", (8,)),
    ]
    assert written["file_type"] == "ihex"
    assert written["row_length"] == 32
    assert len(written["sections"]) == 1
    assert (tmp_path / "CalRAM20260326_131800_P1.hex").exists()


def test_download_calram_uses_if_data_writable_page(
    tmp_path: Path, monkeypatch
) -> None:
    calibration_data = _make_calibration_data(tmp_path)
    paged_segment = _make_segment(
        pages=[
            [
                0,
                "ECU_ACCESS_DONT_CARE",
                "XCP_READ_ACCESS_WITH_ECU_ONLY",
                "XCP_WRITE_ACCESS_NOT_ALLOWED",
            ],
            [
                1,
                "ECU_ACCESS_DONT_CARE",
                "XCP_READ_ACCESS_WITH_ECU_ONLY",
                "XCP_WRITE_ACCESS_WITH_ECU_ONLY",
            ],
        ]
    )
    xcp_master = _RecordingXcpMaster()

    monkeypatch.setattr(
        calibration_module,
        "ModPar",
        lambda session, module_name=None: SimpleNamespace(
            memorySegments=[paged_segment]
        ),
    )

    calibration_module.CalibrationData.download_calram(
        calibration_data,
        xcp_master,
        data=b"\x01\x02\x03",
    )

    assert xcp_master.calls == [
        ("setCalPage", (0x83, 2, 1)),
        ("setMta", (0x16000,)),
        ("push", (b"\x01\x02\x03",)),
    ]
