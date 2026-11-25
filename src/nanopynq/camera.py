"""Camera: an I2C master, a DVP front end and a capture buffer (snapshots) or a frame ring in PSRAM
(streams) put together with a sensor driver.

Built in the notebook from the overlay's IPs, e.g.
    cam = Camera(ol.cam_i2c, ol.cam_capture, ol.cam_dvp)              # camera overlay: snapshot()
    cam = Camera(ol.cam_i2c, None, ol.cam_dvp, ring=ol.cam_ring)      # camstream overlay: stream(), record()
"""

import struct
import time
import zlib

from nanopynq.errors import I2CError
from nanopynq.sensors.ov2640 import OV2640


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


class Frame:
    """A grayscale image; Jupyter shows it through _repr_png_. seq: the frame ring's number, if any."""

    def __init__(self, width: int, height: int, data: bytes, seq: int | None = None):
        self.width, self.height, self.data, self.seq = width, height, bytes(data), seq

    def _repr_png_(self) -> bytes:
        w = self.width
        rows = b"".join(b"\x00" + self.data[y * w : (y + 1) * w] for y in range(self.height))
        return (
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, self.height, 8, 0, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(rows))
            + _png_chunk(b"IEND", b"")
        )


class Camera:
    def __init__(self, i2c, capture, dvp, sensor_cls=OV2640, y_phase: str = "even", ring=None):
        self.capture, self.dvp, self.y_phase, self.ring = capture, dvp, y_phase, ring
        self.sensor = sensor_cls(i2c)
        self.width: int | None = None
        self.height: int | None = None
        self.bad = 0  # frames stream()/record() skipped because the ring marked them bad

    def start(self, width: int = 160, height: int = 120) -> None:
        """XCLK on, check the sensor, configure it for grayscale (YUV422, keep the Y bytes)."""
        self.dvp.xclk(True)
        time.sleep(0.1)  # the sensor answers SCCB only with XCLK running
        cid = self.sensor.chip_id()
        if cid != self.sensor.CHIP_ID:
            raise I2CError(self.sensor.addr7, f"chip id 0x{cid:04X}, expected 0x{self.sensor.CHIP_ID:04X}")
        self.sensor.init()
        self.sensor.set_size(width, height)
        self.sensor.set_format("yuv422")
        self.dvp.frame_level(self.sensor.VSYNC_FRAME_HIGH)
        self.dvp.keep(self.y_phase)
        self.width, self.height = width, height

    def snapshot(self, timeout: float = 3.0) -> Frame:
        if self.width is None or self.height is None:  # start() sets both
            raise RuntimeError("call cam.start() first")
        self.capture.arm()
        n = self.capture.wait(timeout)
        want = self.width * self.height
        if n != want:
            raise RuntimeError(f"captured {n} bytes, expected {want} ({self.width}x{self.height})")
        return Frame(self.width, self.height, self.capture.data(n))

    def _ring_frame(self, seq: int, data: bytes) -> Frame:
        assert self.width is not None and self.height is not None  # _ring_start() checked
        want = self.width * self.height
        if len(data) != want:
            raise RuntimeError(f"frame {seq} has {len(data)} bytes, expected {want} ({self.width}x{self.height})")
        return Frame(self.width, self.height, data, seq=seq)

    def _ring_start(self) -> None:
        if self.width is None:
            raise RuntimeError("call cam.start() first")
        if self.ring is None:
            raise RuntimeError("stream() and record() need the frame ring: Camera(..., ring=ol.cam_ring)")
        self.bad = 0
        self.ring.reset()
        self.ring.enable()

    def stream(self, n: int | None = None, timeout: float = 3.0):
        """Frames as the host can read them (n of them, or until the loop stops), oldest first. The ring
        keeps taking frames at the sensor's rate meanwhile and drops them when it is full (ring.dropped)."""
        self._ring_start()
        got = 0
        try:
            while n is None or got < n:
                seq, data, bad = self.ring.next_frame(timeout)
                if bad:
                    self.bad += 1
                    continue
                yield self._ring_frame(seq, data)
                got += 1
        finally:
            self.ring.enable(False)

    def record(self, n: int, timeout: float | None = None) -> list[Frame]:
        """Take n frames at the sensor's rate into the ring, then read them all (bad ones left out)."""
        self._ring_start()
        t_end = time.monotonic() + (3.0 + n if timeout is None else timeout)
        try:
            while self.ring.available() < n:
                if time.monotonic() > t_end:
                    raise TimeoutError(f"only {self.ring.available()} of {n} frames within the timeout")
                time.sleep(0.05)
        finally:
            self.ring.enable(False)
        frames = []
        for _ in range(n):
            seq, data, bad = self.ring.next_frame()
            if bad:
                self.bad += 1
            else:
                frames.append(self._ring_frame(seq, data))
        return frames
