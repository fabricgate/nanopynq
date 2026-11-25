import pytest

from nanopynq.errors import TransportTimeout
from nanopynq.transport.uartbone import UARTBone
from tests.fakes import FakeUARTBoneDevice


def test_read_single_word_frames_and_decodes():
    dev = FakeUARTBoneDevice({0x1000 // 4: 0x12345678})
    ub = UARTBone(dev, baudrate=115200)
    assert ub.read(0x1000) == 0x12345678
    assert dev.received[:6] == bytes([0x02, 1, 0x00, 0x00, 0x04, 0x00])


def test_write_incr_burst_big_endian():
    dev = FakeUARTBoneDevice()
    UARTBone(dev, 115200).write(0x2000, [1, 2])
    assert dev.received == bytes([0x01, 2, 0, 0, 0x08, 0x00, 0, 0, 0, 1, 0, 0, 0, 2])
    assert dev.regs[0x2000 // 4] == 1 and dev.regs[0x2004 // 4] == 2


def test_fixed_burst_does_not_advance_address():
    dev = FakeUARTBoneDevice({0: 7})
    assert UARTBone(dev, 115200).read(0, 3, burst="fixed") == [7, 7, 7]


def test_max_write_burst_length_matches_litex_formula():
    assert UARTBone.max_write_burst_length(115200) == 142
    assert UARTBone.max_write_burst_length(9600) == 10
    assert UARTBone.max_write_burst_length(3_000_000) == 255


def test_long_write_is_split_into_frames():
    dev = FakeUARTBoneDevice()
    UARTBone(dev, 9600).write(0, list(range(25)))
    assert dev.frames == 3  # 10 + 10 + 5


def test_read_longer_than_255_is_split():
    dev = FakeUARTBoneDevice({i: i for i in range(300)})
    assert UARTBone(dev, 115200).read(0, 300) == list(range(300))


def test_unaligned_address_raises():
    with pytest.raises(ValueError):
        UARTBone(FakeUARTBoneDevice(), 115200).read(0x1002)


def test_truncated_response_raises_timeout_with_counts():  # Review Focus 2
    dev = FakeUARTBoneDevice({0: 1}, truncate_after=2)
    with pytest.raises(TransportTimeout) as e:
        UARTBone(dev, 115200).read(0, 1)
    assert (e.value.expected, e.value.received) == (4, 2)
