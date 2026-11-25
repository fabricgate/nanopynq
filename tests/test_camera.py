import struct
import zlib

import pytest

from nanopynq.camera import Camera, Frame
from nanopynq.drivers.capture import Capture
from nanopynq.drivers.dvp import DVP
from nanopynq.drivers.frame_ring import FrameRing
from nanopynq.drivers.i2c import I2C
from nanopynq.errors import I2CError
from tests.fakes import FakeCameraBus, FakeRingBus


def parts(bus):
    def d(a):
        return {"phys_addr": a, "registers": {}, "parameters": {}}

    return I2C(d(0x3000), bus), Capture(d(0x10000), bus), DVP(d(0x4000), bus)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def test_frame_png_is_valid_grayscale():
    png = Frame(3, 2, bytes([0, 128, 255, 1, 2, 3]))._repr_png_()
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h, depth, color = struct.unpack(">IIBB", png[16:26])
    assert (w, h, depth, color) == (3, 2, 8, 0)
    idat = png.index(b"IDAT")
    n = struct.unpack(">I", png[idat - 4 : idat])[0]
    assert zlib.decompress(png[idat + 4 : idat + 4 + n]) == b"\x00\x00\x80\xff\x00\x01\x02\x03"


def test_start_then_snapshot():
    bus = FakeCameraBus(frame=bytes(range(256)) * 75)
    cam = Camera(*parts(bus))
    cam.start()
    assert bus.dvp_ctrl == 0b1011  # frame while VSYNC high (OV2640), keep even bytes, XCLK on
    f = cam.snapshot()
    assert (f.width, f.height, len(f.data)) == (160, 120, 19200)


def test_snapshot_checks_length():
    cam = Camera(*parts(FakeCameraBus(frame=bytes(100))))
    cam.start()
    with pytest.raises(RuntimeError, match=r"100.*19200"):
        cam.snapshot()


def test_snapshot_before_start_says_so():
    with pytest.raises(RuntimeError, match="start"):
        Camera(*parts(FakeCameraBus())).snapshot()


def ring_camera(bus):
    i2c, _, dvp = parts(bus)
    cam = Camera(i2c, None, dvp, ring=FrameRing({"phys_addr": 0x20000, "registers": {}, "parameters": {}}, bus))
    cam.start()
    return cam


def test_stream_skips_bad_frames():
    bus = FakeRingBus(incoming=[(bytes([k]) * 19200, k == 2) for k in (1, 2, 3, 4)])
    cam = ring_camera(bus)
    frames = list(cam.stream(3))
    assert [(f.seq, f.data[0]) for f in frames] == [(0, 1), (2, 3), (3, 4)]
    assert cam.bad == 1
    assert bus.ctrl_writes == [0b10, 1, 0]  # counters to 0, on, then off when the stream ends


def test_stream_rejects_frames_of_the_wrong_size():
    cam = ring_camera(FakeRingBus(incoming=[(bytes(100), False)]))
    with pytest.raises(RuntimeError, match=r"100.*19200"):
        next(cam.stream())


def test_record_waits_for_n():
    bus = FakeRingBus(incoming=[(bytes([k]) * 19200, False) for k in range(5)])
    cam = ring_camera(bus)
    frames = cam.record(3)
    assert [(f.seq, f.data[0]) for f in frames] == [(0, 0), (1, 1), (2, 2)]
    assert bus.fetches and not any(on for _, _, on in bus.fetches)  # read after the ring was turned off


def test_stream_needs_a_ring():
    cam = Camera(*parts(FakeCameraBus()))
    cam.start()
    with pytest.raises(RuntimeError, match="ring"):
        next(cam.stream())


def test_start_rejects_wrong_chip_id():
    with pytest.raises(I2CError, match="0x7FA2"):
        Camera(*parts(FakeCameraBus(chip_id=0x7FA2))).start()
