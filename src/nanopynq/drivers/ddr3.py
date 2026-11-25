"""Drivers for the Tang Mega 138K Pro's 1 GiB DDR3 window (nanopynq:ddr3:1.0, src/nanopynq/rtl/ddr3_port.v) and its
self-test registers (nanopynq:ddr3_test:1.0, src/nanopynq/rtl/ddr3_test.v). Offsets and lengths are in bytes.
The DDR3 runs in DLL-off mode at CK 50 MHz (e-karge's 2to1 PHY). The host window moves one word per access (and the
UART is slower still); the self-test moves 8 words (one 32-byte burst) per access, as a circuit on ddr3_arb's
master b does: about 69 MB/s writing and 57 MB/s reading, so one pass over the whole 1 GiB takes about 35 s."""

from typing import NamedTuple, cast

from nanopynq.drivers.sdram import LENGTH, PASSES, Sdram, SdramTestResult, _MemTest

CALIB, WR_CYCLES, RD_CYCLES = 0x24, 0x28, 0x2C
CLK_HZ = 50_000_000  # the design's clock, which WR_CYCLES and RD_CYCLES count
BURST = 32  # bytes per access of the self-test


class Ddr3Calib(NamedTuple):
    init_done: bool
    calib_done: bool
    calib_fail: bool
    delays: tuple[int, int, int, int]  # read delay of byte lanes 0..3, chosen by the calibration


class Ddr3(Sdram):
    bindto = ["nanopynq:ddr3:1.0"]
    SIZE = 1 << 30


class Ddr3Test(_MemTest):
    bindto = ["nanopynq:ddr3_test:1.0"]
    SIZE, ADDR_MASK, NAME, LABEL = 1 << 30, 0xFFF_FFFF, "ddr3_test", "DDR3"

    @property
    def calib(self) -> Ddr3Calib:
        v = self.read(CALIB)
        return Ddr3Calib(
            bool(v & 1),
            bool(v >> 1 & 1),
            bool(v >> 2 & 1),
            cast("tuple[int, int, int, int]", tuple(v >> (8 + 6 * lane) & 63 for lane in range(4))),
        )

    def _check_ready(self) -> None:
        c = self.calib
        if c.calib_fail:
            raise RuntimeError(f"the DDR3 calibration failed ({c}); power-cycle the board and load the design again")
        if not c.calib_done:
            raise RuntimeError(f"the DDR3 calibration has not finished ({c}); the hardware would ignore the start")

    def run(
        self, passes: int = 1, start: int = 0, length: int | None = None, inject: bool = False, timeout: float = 900.0
    ) -> SdramTestResult:
        """As SdramTest.run, over the 1 GiB; start and length are multiples of 32 bytes (whole bursts). A full pass
        takes about 35 s, so the default timeout (900 s) covers about 25 of them: pass a larger `timeout=` for more,
        e.g. `run(passes=30, timeout=1800)`."""
        n = self.SIZE - start if length is None else length
        if start % BURST or n % BURST:
            raise ValueError(f"start {start} / length {n}: must be multiples of {BURST} bytes (whole bursts)")
        return super().run(passes, start, length, inject, timeout)

    @property
    def speeds(self) -> tuple[float, float]:
        """(write, read) speed of the last run in MB/s (10^6 bytes per second), from the clocks it spent writing and
        reading and the PASSES x LENGTH it moved each way. The counts saturate after 2^32 clocks (about 86 s, four
        passes over the whole 1 GiB): measure with fewer passes or a shorter length."""
        wr, rd = self.read(WR_CYCLES), self.read(RD_CYCLES)
        if not wr or not rd:
            raise RuntimeError("no cycle counts yet: run the self-test first")
        if 0xFFFF_FFFF in (wr, rd):
            raise RuntimeError("the cycle counts saturated (over about 86 s): run fewer passes or a shorter length")
        n = self.read(PASSES) * self.read(LENGTH) * 4
        return n / (wr / CLK_HZ) / 1e6, n / (rd / CLK_HZ) / 1e6
