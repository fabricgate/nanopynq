import pytest

from nanopynq.drivers.capture import Capture
from nanopynq.drivers.dvp import DVP
from nanopynq.errors import CaptureOverflow
from tests.fakes import FakeCameraBus

CAP = {"phys_addr": 0x10000, "registers": {}, "parameters": {"capacity": 20480}}


def test_wait_returns_length_and_data_reads_window_in_one_burst():
    bus = FakeCameraBus(frame=bytes(range(10)))
    cap = Capture(CAP, bus)
    cap.arm()
    assert cap.wait() == 10
    assert cap.data(10) == bytes(range(10))
    assert bus.window_reads == [(0x18000, 3)]


def test_capacity_register():
    assert Capture(CAP, FakeCameraBus(capacity=256)).capacity == 256


def test_overflow_raises():  # Review Focus 3
    cap = Capture(CAP, FakeCameraBus(frame=bytes(300), capacity=256, overflow=True))
    cap.arm()
    with pytest.raises(CaptureOverflow, match="256"):
        cap.wait()


def test_not_done_times_out_with_xclk_hint():  # Review Focus 1
    cap = Capture(CAP, FakeCameraBus(never_done=True))
    cap.arm()
    with pytest.raises(TimeoutError, match="XCLK"):
        cap.wait(timeout=0.05)


def test_dvp_frame_level_and_other_bits_are_kept():
    bus = FakeCameraBus()
    dvp = DVP({"phys_addr": 0x4000, "registers": {}, "parameters": {}}, bus)
    dvp.frame_level(high=True)
    dvp.xclk(True)
    dvp.keep("even")
    assert bus.dvp_ctrl == 0b1011
    dvp.frame_level(high=False)
    assert bus.dvp_ctrl == 0b0011


def test_dvp_ctrl_bits():
    bus = FakeCameraBus()
    dvp = DVP({"phys_addr": 0x4000, "registers": {}, "parameters": {}}, bus)
    dvp.xclk(True)
    dvp.keep("odd")
    assert bus.dvp_ctrl == 0b101
    dvp.xclk(False)
    assert bus.dvp_ctrl == 0b100 and dvp.frames == 7
    with pytest.raises(ValueError):
        dvp.keep("middle")


def test_dvp_pclks_lines():
    dvp = DVP({"phys_addr": 0x4000, "registers": {}, "parameters": {}}, FakeCameraBus(pclks=123456, lines=120))
    assert (dvp.pclks, dvp.lines) == (123456, 120)
