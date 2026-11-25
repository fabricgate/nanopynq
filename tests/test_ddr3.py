import inspect

import pytest

from nanopynq.drivers.ddr3 import Ddr3, Ddr3Calib, Ddr3Test
from nanopynq.drivers.sdram import SdramTestResult
from tests.fakes import FakeSdramBus

MEM = {"phys_addr": 0x4000_0000, "registers": {}, "parameters": {}}
TEST = {"phys_addr": 0x3000, "registers": {}, "parameters": {}}
GIB = 1 << 30
CALIB_OK = (63 | 5 << 6 | 40 << 12 | 1 << 18) << 8 | 0b011  # init_done, calib_done; lanes 0..3 = 63, 5, 40, 1


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def bus_with(calib=CALIB_OK, **kw):
    bus = FakeSdramBus(**kw)
    bus.regs[0x24] = calib
    return bus


def test_ddr3_bounds_are_one_gigabyte():
    d = Ddr3(MEM, FakeSdramBus())
    d.write(GIB - 4, 7)
    assert d.read(GIB - 4) == 7
    for call in (lambda: d.write(GIB, 1), lambda: d.read(GIB - 4, 2)):
        with pytest.raises(ValueError):
            call()


def test_ddr3_test_default_length_is_the_rest_of_the_gigabyte():
    bus = bus_with()
    Ddr3Test(TEST, bus).run(start=0x1000)
    assert bus.regs[0x10] == (GIB - 0x1000) // 4 and bus.ctrl_writes == [1]


def test_ddr3_test_reports_28_bit_error_address():
    bus = bus_with(result=(1, 1, (0xFFF_FFFF, 0xAA, 0xBB)))
    assert Ddr3Test(TEST, bus).run() == SdramTestResult(1, 1, (4 * 0xFFF_FFFF, 0xAA, 0xBB))


def test_ddr3_test_refuses_before_calibration():
    bus = bus_with(calib=0b001)  # init done, calibration not (yet)
    with pytest.raises(RuntimeError, match="calibration"):
        Ddr3Test(TEST, bus).run()
    assert bus.ctrl_writes == []
    bus = bus_with(calib=0b111)  # calibration failed: e-karge's ddr3_ctrl sets done and fail
    with pytest.raises(RuntimeError, match="failed"):
        Ddr3Test(TEST, bus).run()


def test_ddr3_calib_property():
    assert Ddr3Test(TEST, bus_with()).calib == Ddr3Calib(True, True, False, (63, 5, 40, 1))
    assert Ddr3Test(TEST, bus_with(calib=0b111)).calib == Ddr3Calib(True, True, True, (0, 0, 0, 0))


def test_ddr3_default_timeout_covers_a_full_pass():
    assert inspect.signature(Ddr3Test.run).parameters["timeout"].default >= 900
    assert not hasattr(Ddr3Test, "rd_lat")


def test_ddr3_test_refuses_unaligned_ranges():  # the hardware ignores a start unless both are whole bursts
    bus = bus_with()
    for kw in ({"start": 16}, {"length": (1 << 20) | 4}):
        with pytest.raises(ValueError, match="32"):
            Ddr3Test(TEST, bus).run(**kw)
    assert bus.ctrl_writes == []


def test_ddr3_test_speeds():
    bus = bus_with()
    bus.regs.update({0x08: 2, 0x10: 0x0100_0000, 0x28: 50_000_000, 0x2C: 100_000_000})  # 2 x 64 MiB; 1 s, 2 s
    mb = 2 * (64 << 20) / 1e6
    assert Ddr3Test(TEST, bus).speeds == pytest.approx((mb, mb / 2))


def test_ddr3_test_speeds_before_a_run():
    bus = bus_with()
    bus.regs.update({0x28: 0, 0x2C: 0})
    with pytest.raises(RuntimeError, match="run"):
        _ = Ddr3Test(TEST, bus).speeds


def test_ddr3_test_speeds_refuse_saturated_counts():  # 2^32 clocks at 50 MHz: about 86 s, three 1 GiB passes
    for wr, rd in ((0xFFFF_FFFF, 100), (100, 0xFFFF_FFFF)):
        bus = bus_with()
        bus.regs.update({0x08: 10, 0x10: 0x1000_0000, 0x28: wr, 0x2C: rd})
        with pytest.raises(RuntimeError, match="saturated"):
            _ = Ddr3Test(TEST, bus).speeds
