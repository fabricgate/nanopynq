"""Drivers for the 8 MB SDRAM window (nanopynq:sdram:1.0) and its self-test registers
(nanopynq:sdram_test:1.0, src/nanopynq/rtl/sdram_test.v). Offsets and lengths are in bytes."""

import time
from typing import NamedTuple

from nanopynq.ip import DefaultIP

CTRL, STATUS, PASSES, START, LENGTH, ERRORS, ERR_ADDR, ERR_DATA, ERR_EXP, RD_LAT = range(0x0, 0x28, 0x4)
SIZE = 8 << 20


class SdramTestResult(NamedTuple):
    passes: int
    errors: int
    first_error: tuple[int, int, int] | None  # (byte offset, value read, value expected)


class Sdram(DefaultIP):
    bindto = ["nanopynq:sdram:1.0"]
    SIZE = SIZE

    def _check(self, offset: int, words: int) -> None:
        if offset % 4 or offset < 0 or words < 1 or offset + 4 * words > self.SIZE:
            raise ValueError(f"{words} word(s) at byte offset {offset}: must be word aligned inside 0..{self.SIZE}")

    def read(self, offset: int = 0, length: int | None = None) -> int | list[int]:  # type: ignore[override]
        """One 32-bit word at byte `offset`, or (length given) a list of `length` words."""
        self._check(offset, 1 if length is None else length)
        return self._transport.read(self.description["phys_addr"] + offset, length)

    def write(self, offset: int, data: int | list[int]) -> None:
        """Write one word, or a list of words, from byte `offset`."""
        self._check(offset, len(data) if not isinstance(data, int) else 1)
        self._transport.write(self.description["phys_addr"] + offset, data)


class _MemTest(DefaultIP):
    """The self-test registers shared by sdram_test.v and ddr3_test.v (CTRL..FIRST_ERR_EXP). Subclasses set the size,
    the word-address mask of FIRST_ERR_ADDR, the names the messages use, and may refuse a start in _check_ready."""

    SIZE, ADDR_MASK, NAME, LABEL = SIZE, 0x1F_FFFF, "sdram_test", "SDRAM"

    def _check_ready(self) -> None:
        pass

    def run(
        self, passes: int = 1, start: int = 0, length: int | None = None, inject: bool = False, timeout: float = 30.0
    ) -> SdramTestResult:
        """Write, read back and compare `length` bytes from byte `start`, `passes` times (inject: one
        inverted word per pass, so the test must report errors). On timeout the run is stopped. The default
        timeout (30 s) is too short for about 40 or more full 8 MB passes (0.72 s each): pass a larger
        `timeout=`, e.g. `run(passes=100, timeout=120)`."""
        size = self.SIZE
        length = size - start if length is None else length
        if not 1 <= passes <= 0xFFFF:
            raise ValueError(f"passes {passes} out of range 1..65535")
        if start % 4 or length % 4 or start < 0 or length < 1 or start + length > size:
            raise ValueError(f"start {start} / length {length}: must be word aligned and inside 0..{size}")
        if self.read(STATUS) & 1:  # the hardware would ignore our start
            raise RuntimeError(f"test already running; stop it with ol.{self.NAME}.write(0, 2)")
        self._check_ready()
        self.write(PASSES, passes)
        self.write(START, start // 4)
        self.write(LENGTH, length // 4)
        self.write(CTRL, 1 | inject << 2)
        t_end = time.monotonic() + timeout
        # a start is ignored while a run is active, so do not wait for `running` to rise
        while (status := self.read(STATUS)) & 1 or status >> 16 != passes:
            if time.monotonic() > t_end:
                self.write(CTRL, 0b10)
                raise TimeoutError(f"the {self.LABEL} test did not finish within {timeout} s")
            time.sleep(0.05)
        addr = self.read(ERR_ADDR)
        first = None
        if addr >> 31:
            first = (4 * (addr & self.ADDR_MASK), self.read(ERR_DATA), self.read(ERR_EXP))
        return SdramTestResult(passes, self.read(ERRORS), first)


class SdramTest(_MemTest):
    bindto = ["nanopynq:sdram_test:1.0"]

    @property
    def rd_lat(self) -> int:
        return self.read(RD_LAT)

    @rd_lat.setter
    def rd_lat(self, value: int) -> None:
        if not 0 <= value <= 7:
            raise ValueError(f"rd_lat {value} out of range 0..7")
        self.write(RD_LAT, value)
