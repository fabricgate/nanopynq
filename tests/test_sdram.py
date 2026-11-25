import pytest

from nanopynq.drivers.sdram import Sdram, SdramTest, SdramTestResult
from tests.fakes import FakeSdramBus

MEM = {"phys_addr": 0x80_0000, "registers": {}, "parameters": {}}
TEST = {"phys_addr": 0x3000, "registers": {}, "parameters": {}}
SIZE = Sdram.SIZE


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_read_write_burst():
    s = Sdram(MEM, FakeSdramBus())
    s.write(0x10, [1, 2, 3])
    assert s.read(0x10, 3) == [1, 2, 3]
    assert s.read(0x14) == 2


def test_bounds():
    bus = FakeSdramBus()
    log = []
    bus.write, bus.read = (lambda *a, **k: log.append(a)), (lambda *a, **k: log.append(a))
    s = Sdram(MEM, bus)
    for call in (
        lambda: s.read(2),
        lambda: s.read(SIZE),
        lambda: s.read(SIZE - 4, 2),
        lambda: s.write(SIZE - 4, [1, 2]),
        lambda: s.write(SIZE - 4, (1, 2)),
        lambda: s.write(SIZE, 1),
    ):
        with pytest.raises(ValueError):
            call()
    assert log == []  # nothing reached the bus
    del bus.write, bus.read
    s.write(SIZE - 4, 7)
    assert s.read(SIZE - 4) == 7


def test_run_ok():
    bus = FakeSdramBus(result=(3, 0, None))
    assert SdramTest(TEST, bus).run(passes=3, start=0x100, length=0x400) == SdramTestResult(3, 0, None)
    assert (bus.regs[0x08], bus.regs[0x0C], bus.regs[0x10]) == (3, 0x40, 0x100)
    assert bus.ctrl_writes == [1]


def test_run_default_length_and_inject():
    bus = FakeSdramBus()
    SdramTest(TEST, bus).run(start=0x1000, inject=True)
    assert bus.regs[0x10] == (SIZE - 0x1000) // 4 and bus.ctrl_writes == [0b101]


def test_run_reports_first_error():
    bus = FakeSdramBus(result=(2, 2, (0x123, 0xAA, 0xBB)))
    assert SdramTest(TEST, bus).run(passes=2) == SdramTestResult(2, 2, (4 * 0x123, 0xAA, 0xBB))


def test_run_bounds():
    t = SdramTest(TEST, FakeSdramBus(result=(65535, 0, None)))
    for kw in (
        {"length": 0},
        {"start": 2},
        {"length": 6},
        {"start": SIZE},
        {"start": 4, "length": SIZE},
        {"passes": 0},
        {"passes": 65536},
    ):
        with pytest.raises(ValueError):
            t.run(**kw)
    t.run(passes=65535, start=SIZE - 4, length=4)


def test_run_timeout_stops():
    bus = FakeSdramBus(never_done=True)
    with pytest.raises(TimeoutError):
        SdramTest(TEST, bus).run(timeout=0.05)
    assert bus.ctrl_writes[-1] == 0b10


def test_rd_lat_property():
    bus = FakeSdramBus()
    t = SdramTest(TEST, bus)
    assert t.rd_lat == 2
    t.rd_lat = 3
    assert bus.regs[0x24] == 3 and t.rd_lat == 3
    for v in (-1, 8):
        with pytest.raises(ValueError):
            t.rd_lat = v


def test_run_refuses_while_running():
    bus = FakeSdramBus(busy=True)
    with pytest.raises(RuntimeError):
        SdramTest(TEST, bus).run()
    assert bus.ctrl_writes == [] and set(bus.regs) == {0x24}
