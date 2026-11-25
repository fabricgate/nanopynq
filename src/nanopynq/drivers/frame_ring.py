"""Driver for nanopynq:frame_ring:1.0 (src/nanopynq/rtl/frame_ring.v): whole frames in PSRAM slots, read
slot by slot through a 1 KB window. WSEQ counts the frames written, RSEQ the frames read (the host
writes it); WSEQ - RSEQ (32 bits) are waiting."""

import time

from nanopynq.ip import DefaultIP

CTRL, WSEQ, RSEQ, DROPPED, FETCH, STATUS, SLOT_LEN, SLOT_INFO = range(0x0, 0x20, 0x4)
WINDOW, WINDOW_BYTES = 0x1000, 1024
MASK = 0xFFFF_FFFF


class FrameRing(DefaultIP):
    bindto = ["nanopynq:frame_ring:1.0"]

    def enable(self, on: bool = True) -> None:
        """Take the frames that start from now on (False: stop after the frame in progress)."""
        self.write(CTRL, int(on))

    def reset(self) -> None:
        """Off, and WSEQ, RSEQ, DROPPED and the overflow flag back to 0."""
        self.write(CTRL, 0b10)

    def available(self) -> int:
        """Frames written and not read yet."""
        return (self.read(WSEQ) - self.read(RSEQ)) & MASK

    @property
    def dropped(self) -> int:
        """Frames thrown away because the ring was full."""
        return self.read(DROPPED)

    def _fetch(self, word: int, nbytes: int) -> bytes:
        """Copy nbytes (a multiple of 16, at most 1 KB) from PSRAM word `word` into the window; read it."""
        self.write(FETCH, word | (nbytes // 16) << 24)
        t_end = time.monotonic() + 1.0
        while (status := self.read(STATUS)) & 1:
            if time.monotonic() > t_end:
                raise TimeoutError("the PSRAM fetch did not finish")
        if status & 4:
            raise RuntimeError(f"a PSRAM read of the fetch at word 0x{word:06X} came back short")
        words = self._transport.read(self.description["phys_addr"] + WINDOW, nbytes // 4)
        return b"".join(w.to_bytes(4, "little") for w in words)

    def next_frame(self, timeout: float = 3.0) -> tuple[int, bytes, bool]:
        """Wait for the oldest unread frame; return (its WSEQ number, its bytes, bad) and free its slot.
        bad: the write FIFO overflowed or the frame did not fit in the slot (the bytes are incomplete)."""
        t_end = time.monotonic() + timeout
        while not self.available():
            if time.monotonic() > t_end:
                raise TimeoutError(f"no frame within {timeout} s: is the ring on and the sensor running?")
            time.sleep(0.01)
        rseq, info = self.read(RSEQ), self.read(SLOT_INFO)
        slot_words, nslots = info & 0xFFFF, info >> 16
        base = (rseq % nslots) * slot_words
        raw = self._fetch(base, min(WINDOW_BYTES, 2 * slot_words))
        hdr = int.from_bytes(raw[:4], "little")
        length = hdr & 0xFFFF
        bad = bool(hdr >> 31) or (hdr >> 16) & 0x7FFF != rseq & 0x7FFF
        end = min(4 + length, 2 * slot_words)
        while len(raw) < end:
            n = min(WINDOW_BYTES, -(-(end - len(raw)) // 16) * 16)
            raw += self._fetch(base + len(raw) // 2, n)
        self.write(RSEQ, (rseq + 1) & MASK)
        return rseq, raw[4 : 4 + length], bad
