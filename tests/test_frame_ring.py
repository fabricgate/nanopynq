import pytest

from nanopynq.drivers.frame_ring import FrameRing
from tests.fakes import FakeRingBus

RING = {"phys_addr": 0x20000, "registers": {}, "parameters": {}}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_next_frame_reads_slot_in_window_chunks_and_advances_rseq():
    data = bytes(i * 7 & 0xFF for i in range(2500))
    bus = FakeRingBus(incoming=[(b"x" * 10, False), (data, False)])
    ring = FrameRing(RING, bus)
    ring.enable()
    assert ring.next_frame() == (0, b"x" * 10, False)
    assert ring.next_frame() == (1, data, False)
    assert bus.rseq == 2
    s1 = 16384  # slot 1: 4 + 2500 bytes = two whole windows and 456 bytes (29 units of 16)
    assert bus.fetches[1:] == [(s1, 64, True), (s1 + 512, 64, True), (s1 + 1024, 29, True)]
    assert bus.window_reads[1:] == [(0x21000, 256), (0x21000, 256), (0x21000, 116)]


def test_dropped_and_bad_frames():
    bus = FakeRingBus(incoming=[(b"a", False), (b"b", True), (b"c", False)], nslots=2)
    ring = FrameRing(RING, bus)
    ring.enable()
    for _ in range(3):
        ring.available()
    assert ring.available() == 2 and ring.dropped == 1
    assert ring.next_frame() == (0, b"a", False)
    assert ring.next_frame() == (1, b"b", True)


def test_available_across_the_32_bit_wrap():
    bus = FakeRingBus()
    bus.wseq, bus.rseq = 2, 0xFFFF_FFFF
    assert FrameRing(RING, bus).available() == 3


def test_next_frame_times_out_when_nothing_arrives():
    with pytest.raises(TimeoutError, match="no frame"):
        FrameRing(RING, FakeRingBus()).next_frame(timeout=0.0)


def test_reset_turns_off_and_clears():
    bus = FakeRingBus()
    ring = FrameRing(RING, bus)
    ring.enable()
    ring.reset()
    assert bus.ctrl_writes == [1, 0b10] and not bus.on


def test_short_psram_read_raises_instead_of_returning_the_window():
    bus = FakeRingBus(incoming=[(b"x" * 10, False)])
    bus.fetch_error = True
    ring = FrameRing(RING, bus)
    ring.enable()
    with pytest.raises(RuntimeError, match="PSRAM"):
        ring.next_frame()
    assert bus.rseq == 0  # the frame stays unread
