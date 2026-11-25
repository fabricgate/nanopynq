"""Driver for nanopynq:capture:1.0 (src/nanopynq/rtl/capture.v): one frame into block RAM, read through a window."""

import time

from nanopynq.errors import CaptureOverflow
from nanopynq.ip import DefaultIP

WINDOW = 0x8000


class Capture(DefaultIP):
    bindto = ["nanopynq:capture:1.0"]

    @property
    def capacity(self) -> int:
        return self.read(0xC)

    def arm(self) -> None:
        """Capture the next whole frame."""
        self.write(0x0, 1)

    def wait(self, timeout: float = 3.0) -> int:
        """Wait for the armed capture; return its length in bytes."""
        t_end = time.monotonic() + timeout
        while True:
            status = self.read(0x4)
            if status & 0b10:
                if status & 0b100:
                    raise CaptureOverflow(f"the frame did not fit in the {self.capacity}-byte capture buffer")
                return self.read(0x8)
            if time.monotonic() > t_end:
                raise TimeoutError(
                    f"no frame captured within {timeout} s: is XCLK on and the sensor initialised (Camera.start())?"
                )
            time.sleep(0.01)

    def data(self, length: int) -> bytes:
        words = self._transport.read(self.description["phys_addr"] + WINDOW, (length + 3) // 4)
        return b"".join(w.to_bytes(4, "little") for w in words)[:length]
