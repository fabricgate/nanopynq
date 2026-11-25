"""cocotb stand-in for the Tang Nano 20K's 64 Mbit SDRAM (2K rows x 256 cols x 4 banks x 32 bit), driven
from sdram_ctrl's pin-side ports (sdram_*, dq_o/dq_oe; it drives dq_i).

A command is taken at every rising edge of sdram_clk (CS# low, not NOP). Every violation of the plan's
timing limits is appended to `errors`: 200 us after power-up (the model's creation) before the first
command, then PRECHARGE ALL, REFRESH at least twice, MODE REGISTER SET (CAS 2, burst length 1) and tMRD
(2 clocks) before anything else; tRCD, tRAS, tRC, tRP; READ and WRITE with auto precharge (A10 = 1); a
REFRESH at least every 15.6 us once initialised. Auto precharge closes the row one clock after a READ
(CAS 2, burst length 1) and max(tWR, 2 clocks) after a WRITE (write recovery: ESMT parts give tRDL =
2 CLK); tRAS is checked back from there to the ACTIVE, tRP forward to the next ACTIVE or REFRESH. A
REFRESH keeps the device busy for tRC.

`mem` maps the word address {bank, row, col} (as cmd_addr) to its 32-bit value. A WRITE stores dq_o
(driven) at its edge, bytes whose DQM bit is 0 only. A READ taken at edge n puts the word on dq_i from
6 ns after edge n+1 to 2.5 ns after edge n+2 (bytes masked by DQM at edge n stay garbage); dq_i holds
random garbage at every other time, so a controller that samples outside this window reads wrong data.
With rd_window=False the word stays on dq_i until the next READ's word replaces it.
`log` lists every command as (ns since power-up, name).
"""

import random

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

T_RCD, T_RP, T_RC, T_RAS, T_WR = 18, 18, 60, 42, 12  # ns
T_MRD, T_RDL = 2, 2  # clocks
T_POWERUP, T_REFI = 200_000, 15_600  # ns
NAMES = {
    0b011: "ACTIVE",
    0b101: "READ",
    0b100: "WRITE",
    0b010: "PRECHARGE",
    0b001: "REFRESH",
    0b000: "MRS",
    0b110: "BURST STOP",
}


class SDRAMModel:
    def __init__(self, dut, rd_window=True):
        self.dut, self.rd_window = dut, rd_window
        self.mem: dict[int, int] = {}
        self.errors: list[str] = []
        self.log: list[tuple[float, str]] = []
        self.rng = random.Random(0)
        self.t0 = get_sim_time(unit="ns")
        dut.dq_i.value = self.rng.getrandbits(32)
        cocotb.start_soon(self._run())

    def _err(self, now, msg):
        self.errors.append(f"{now:.1f} ns: {msg}")

    async def _drive_read(self, word, mask):
        d = self.dut
        await RisingEdge(d.sdram_clk)
        await Timer(6, unit="ns")
        d.dq_i.value = word & ~mask | self.rng.getrandbits(32) & mask
        if self.rd_window:
            await RisingEdge(d.sdram_clk)
            await Timer(2.5, unit="ns")
            d.dq_i.value = self.rng.getrandbits(32)

    async def _run(self):
        d = self.dut
        init = "power"  # power -> precharged -> ready (MRS)
        refreshes = 0
        row = [None] * 4  # open row per bank
        act_at = [-1e9] * 4  # ns of the last ACTIVE per bank
        pre_at = [-1e9] * 4  # ns at which the bank's (auto) precharge starts
        busy_until = -1e9  # REFRESH in progress until then
        last_ref, ref_late = None, False
        mrs_edge, edge, prev = None, 0, None
        while True:
            await RisingEdge(d.sdram_clk)
            await ReadOnly()
            now = get_sim_time(unit="ns") - self.t0
            period = now - prev if prev is not None else 0
            prev, edge = now, edge + 1
            if init == "ready" and not ref_late and now - last_ref > T_REFI:
                self._err(now, f"no REFRESH for more than {T_REFI} ns")
                ref_late = True
            if int(d.sdram_cs_n.value):
                continue
            op = int(d.sdram_ras_n.value) << 2 | int(d.sdram_cas_n.value) << 1 | int(d.sdram_we_n.value)
            if op == 0b111:
                continue
            name, ba, a = NAMES[op], int(d.sdram_ba.value), int(d.sdram_a.value)
            self.log.append((now, name))
            if now < T_POWERUP:
                self._err(now, f"{name} before the {T_POWERUP} ns power-up wait")
            if now < busy_until:
                self._err(now, f"{name} within tRC of a REFRESH")
            if mrs_edge is not None and edge - mrs_edge < T_MRD:
                self._err(now, f"{name} within tMRD of MRS")
            if init != "ready" and name not in ("PRECHARGE", "REFRESH", "MRS"):
                self._err(now, f"{name} before initialisation")
            if name == "PRECHARGE":
                if init == "power":
                    init = "precharged"
                    if not a >> 10 & 1:
                        self._err(now, "the first PRECHARGE is not PRECHARGE ALL")
                for b in range(4) if a >> 10 & 1 else (ba,):
                    if row[b] is not None and now - act_at[b] < T_RAS:
                        self._err(now, f"tRAS: PRECHARGE of bank {b}")
                    row[b], pre_at[b] = None, now
            elif name == "REFRESH":
                if init == "power":
                    self._err(now, "REFRESH before PRECHARGE ALL")
                refreshes += 1
                for b in range(4):
                    if row[b] is not None:
                        self._err(now, f"REFRESH with bank {b} open")
                    elif now - pre_at[b] < T_RP:
                        self._err(now, f"tRP: REFRESH after the precharge of bank {b}")
                busy_until, last_ref, ref_late = now + T_RC, now, False
            elif name == "MRS":
                if init != "precharged" or refreshes < 2:
                    self._err(now, f"MRS after {refreshes} REFRESH (state {init})")
                if ba != 0 or a & 0x7 != 0 or a >> 4 & 0x7 != 2 or a >> 7 & 0x3 != 0:
                    self._err(now, f"MRS value ba={ba} a={a:#05x}: want burst length 1, CAS 2")
                init, mrs_edge = "ready", edge
            elif name == "ACTIVE":
                if row[ba] is not None:
                    self._err(now, f"ACTIVE on bank {ba} with row {row[ba]} open")
                if now - pre_at[ba] < T_RP:
                    self._err(now, f"tRP: ACTIVE on bank {ba}")
                if now - act_at[ba] < T_RC:
                    self._err(now, f"tRC: ACTIVE on bank {ba}")
                row[ba], act_at[ba] = a, now
            elif name in ("READ", "WRITE"):
                if row[ba] is None:
                    self._err(now, f"{name} on bank {ba} with no row open")
                    continue
                if now - act_at[ba] < T_RCD:
                    self._err(now, f"tRCD: {name} on bank {ba}")
                if not a >> 10 & 1:
                    self._err(now, f"{name} without auto precharge")
                addr = ba << 19 | row[ba] << 8 | a & 0xFF
                mask = 0
                for j in range(4):
                    mask |= 0xFF << 8 * j if int(d.sdram_dqm.value) >> j & 1 else 0
                if name == "WRITE":
                    if not int(d.dq_oe.value):
                        self._err(now, "WRITE with dq_oe low")
                    self.mem[addr] = self.mem.get(addr, 0) & mask | int(d.dq_o.value) & ~mask
                    start = now + max(T_WR, T_RDL * period)
                else:
                    cocotb.start_soon(self._drive_read(self.mem.get(addr, 0), mask))
                    start = now + period
                if start - act_at[ba] < T_RAS:
                    self._err(now, f"tRAS: auto precharge of bank {ba}")
                row[ba], pre_at[ba] = None, start
            else:
                self._err(now, f"unexpected {name}")
