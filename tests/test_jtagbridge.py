import pytest

from nanopynq.errors import BridgeError, TransportTimeout
from nanopynq.transport.jtagbridge import JTAGBridge
from tests.fakes import FakeJtagBridgeDevice


def test_read_id():
    assert JTAGBridge(FakeJtagBridgeDevice({0: 0x4E505131})).read(0x0) == 0x4E505131


def test_write_then_read_scratch():
    dev = FakeJtagBridgeDevice()
    jb = JTAGBridge(dev)
    jb.write(0x8, 0xDEADBEEF)
    assert dev.regs[2] == 0xDEADBEEF and jb.read(0x8) == 0xDEADBEEF


def test_two_words_go_in_one_flush():
    dev = FakeJtagBridgeDevice({0: 1, 1: 2})
    jb = JTAGBridge(dev)
    n = dev.flushes
    assert jb.read(0x0, 2) == [1, 2] and dev.flushes - n == 1


def test_read_burst_uses_one_flush_per_100_words():
    dev = FakeJtagBridgeDevice({i: i for i in range(250)})
    jb = JTAGBridge(dev)
    n = dev.flushes
    assert jb.read(0x0, 250) == list(range(250))
    assert dev.flushes - n == 3  # 100 + 100 + 50


def test_write_burst_batches_and_checks_every_response():
    dev = FakeJtagBridgeDevice()
    jb = JTAGBridge(dev)
    n = dev.flushes
    jb.write(0x0, list(range(150)))
    assert [dev.regs[i] for i in range(150)] == list(range(150)) and dev.flushes - n == 2


def test_bad_response_inside_a_batch_raises():  # Review Focus 4
    dev = FakeJtagBridgeDevice({0: 1})
    jb = JTAGBridge(dev)
    dev.ignore_ir = True
    jb.reset()  # IR lost before the batch
    with pytest.raises(BridgeError):
        jb.read(0x0, 10)


def test_incr_write_burst():
    dev = FakeJtagBridgeDevice()
    JTAGBridge(dev).write(0x1000, [5, 6])
    assert (dev.regs[0x400], dev.regs[0x401]) == (5, 6)


def test_fixed_burst_and_alignment_match_uartbone():
    jb = JTAGBridge(FakeJtagBridgeDevice({0: 7}))
    assert jb.read(0, 3, burst="fixed") == [7, 7, 7]
    with pytest.raises(ValueError, match="aligned"):
        jb.read(0x2)
    with pytest.raises(ValueError, match="burst"):
        jb.read(0x0, burst="wrap")
    with pytest.raises(ValueError, match="length"):
        jb.read(0x0, 0)


def test_reset_loads_ir_0x42():
    dev = FakeJtagBridgeDevice()
    JTAGBridge(dev)
    assert dev.ir == 0x42 and dev.state == "RTI"


def test_lost_ir_raises_bridge_error():  # Review Focus 4
    with pytest.raises(BridgeError) as e:
        JTAGBridge(FakeJtagBridgeDevice({0: 0x4E505131}, ignore_ir=True)).read(0x0)
    assert e.value.response == (1 << 64) - 1


def test_silent_device_raises_timeout():  # Review Focus 1
    with pytest.raises(TransportTimeout):
        JTAGBridge(FakeJtagBridgeDevice(silent=True))


def test_close_closes_port():
    dev = FakeJtagBridgeDevice()
    JTAGBridge(dev).close()
    assert dev.closed == 1


@pytest.mark.parametrize("addr,length", [(1 << 32, None), (-4, None), ((1 << 32) - 4, 2)])
def test_address_out_of_range_rejected_before_any_scan(addr, length):
    dev = FakeJtagBridgeDevice()
    jb = JTAGBridge(dev)
    n = dev.flushes
    with pytest.raises(ValueError, match="range"):
        jb.read(addr, length)
    with pytest.raises(ValueError, match="range"):
        jb.write(addr, [1] * (length or 1))
    assert dev.flushes == n and dev.regs == {}


def test_chunk_is_capped_by_max_read():
    # 450 TDO bytes per flush -> 450 // 9 - 1 = 49 words per flush (the closing no-op scan is the 50th)
    dev = FakeJtagBridgeDevice({i: i for i in range(250)}, max_read=450)
    jb = JTAGBridge(dev)
    n = dev.flushes
    assert jb.read(0x0, 250) == list(range(250))
    assert dev.flushes - n == 6
