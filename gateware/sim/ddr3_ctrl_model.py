"""The user side of e-karge's ddr3_ctrl (src/nanopynq/rtl/ddr3/ddr3_ctrl.sv) for cocotb: while busy is low, a
one-clock pulse on rd, wr or refresh is taken at the clock edge; busy is high from the next clock until the access
is done (a random 10..20 clocks here); a read ends with data_ready high for one clock with dout. busy stays high
until calib_done. Words live in `mem` (word address -> 32-bit value); byte enables are applied on writes. A write
with burst high writes the 8 words of the aligned burst that holds addr from din_burst under be_burst (4 bits per
word); a read also gives those 8 words on dout_burst. `log` lists (clock, op, addr, burst) of every request taken, op
in "rd", "wr", "ref"."""

import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge


class Ddr3CtrlModel:
    def __init__(self, dut, prefix: str = "", seed: int = 1):
        self.dut, self.p = dut, prefix
        self.mem: dict[int, int] = {}
        self.log: list[tuple[int, str, int]] = []
        self.calib_done = True
        self.rng = random.Random(seed)
        self.clock = 0
        self._sig("busy").value = 1
        self._sig("data_ready").value = 0
        self._sig("dout").value = 0
        self._sig("dout_burst").value = 0
        cocotb.start_soon(self._run())

    def _sig(self, name):
        return getattr(self.dut, self.p + name)

    async def _run(self):
        busy_left, op, addr = 0, None, 0
        while True:
            await RisingEdge(self.dut.clk)
            self.clock += 1
            rd, wr, ref = (int(self._sig(n).value) for n in ("rd", "wr", "refresh"))
            busy = int(self._sig("busy").value)
            data_ready = 0
            if not busy and (rd or wr or ref):
                assert rd + wr + ref == 1, f"clock {self.clock}: more than one request ({rd=} {wr=} {ref=})"
                a, din, be = int(self._sig("addr").value), int(self._sig("din").value), int(self._sig("be").value)
                burst = int(self._sig("burst").value)
                op = "rd" if rd else "wr" if wr else "ref"
                addr = a
                self.log.append((self.clock, op, a, burst))
                if wr and burst:
                    data, be8 = int(self._sig("din_burst").value), int(self._sig("be_burst").value)
                    for j in range(8):
                        self._write(a & ~7 | j, data >> 32 * j & 0xFFFF_FFFF, be8 >> 4 * j & 0xF)
                elif wr:
                    self._write(a, din, be)
                busy_left = self.rng.randint(10, 20)
                busy = 1
            elif busy and busy_left:
                busy_left -= 1
                if not busy_left:
                    busy = 0
                    if op == "rd":
                        data_ready = 1
                        self._sig("dout").value = self.mem.get(addr, 0)
                        self._sig("dout_burst").value = sum(self.mem.get(addr & ~7 | j, 0) << 32 * j for j in range(8))
            elif busy and op is None and self.calib_done:
                busy = 0  # init/calibration done
            self._sig("busy").value = busy
            self._sig("data_ready").value = data_ready
            await ReadOnly()

    def _write(self, a, din, be):
        if be:
            mask = sum(0xFF << 8 * i for i in range(4) if be >> i & 1)
            self.mem[a] = (self.mem.get(a, 0) & ~mask) | (din & mask)
