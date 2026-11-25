"""cocotb stand-in for the SiP HyperRAM, driven from hyperram_ctrl's pin-side ports (dq_o/dq_oe,
rwds_o/rwds_oe, ck, cs_n; it drives dq_i and rwds_i).

Sampled once per clk: a change of ck is a CK edge. Edges 0-5 carry the 48-bit CA (table 4-2 of the
HyperBus datasheets). A write takes byte j at edge 6 + 2*wlat + j when RWDS is driven low (high =
masked). A read puts byte j on DQ at edge 6 + 2*rlat + j with an RWDS transition (RWDS is high during
the CA, low until the data). rlat = wlat + 1 is the plan's reading of the P0 board against a write
latency of 13. Words are 16 bits, first byte in [15:8]. Every transaction is logged with its length.
"""

import cocotb
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge


class HyperRAMModel:
    def __init__(self, dut, wlat=13, rlat=14):
        self.dut, self.wlat, self.rlat = dut, wlat, rlat
        self.mem: dict[int, int] = {}
        self.log: list[
            dict
        ] = []  # per transaction: write, addr, edges, clks (CS# low), gap (clks CS# high before), bytes
        self.errors: list[str] = []
        self.mute_reads = 0  # this many next reads never toggle RWDS (a device that does not answer)
        cocotb.start_soon(self._run())

    def _write_byte(self, word, j, value):
        old = self.mem.get(word, 0)
        self.mem[word] = (old & 0x00FF) | value << 8 if j % 2 == 0 else (old & 0xFF00) | value

    async def _run(self):
        d = self.dut
        d.dq_i.value = 0
        d.rwds_i.value = 0
        prev_ck, low, high, edges, ca, t = 0, False, 0, 0, 0, None
        while True:
            await RisingEdge(d.clk)
            await ReadOnly()
            cs_n, ck = int(d.cs_n.value), int(d.ck.value)
            dq_oe, dq = int(d.dq_oe.value), int(d.dq_o.value)
            rwds_oe, rwds = int(d.rwds_oe.value), int(d.rwds_o.value)
            drive = None
            if cs_n:
                if low:
                    self.log.append(t)
                    if ck:
                        self.errors.append("CS# went high with CK high")
                low, high = False, high + 1
            else:
                if not low:
                    low, edges, ca = True, 0, 0
                    t = {"write": None, "addr": None, "edges": 0, "clks": 0, "gap": high, "bytes": 0}
                    high = 0
                    drive = (0, 1)  # RWDS high during the CA: fixed 2x latency
                t["clks"] += 1
                if ck != prev_ck:
                    e, edges = edges, edges + 1
                    t["edges"] = edges
                    if e < 6:
                        if not dq_oe:
                            self.errors.append(f"CA byte {e} not driven")
                        if rwds_oe:
                            self.errors.append("RWDS driven during the CA")
                        ca = ca << 8 | dq
                        if e == 5:
                            t["write"] = not ca >> 47 & 1
                            t["addr"] = ((ca >> 16) & 0x1FFF_FFFF) << 3 | (ca & 7)
                            drive = (0, 0)
                            t["mute"] = not t["write"] and self.mute_reads > 0
                            self.mute_reads -= int(t["mute"])
                    elif t["write"]:
                        j = e - (6 + 2 * self.wlat)
                        if j >= 0 and dq_oe and rwds_oe and not rwds:
                            self._write_byte(t["addr"] + j // 2, j, dq)
                            t["bytes"] += 1
                        elif j < 0 and dq_oe:
                            self.errors.append(f"DQ driven during the write latency (edge {e})")
                    else:
                        if dq_oe or rwds_oe:
                            self.errors.append(f"controller drives the bus during a read (edge {e})")
                        j = e - (6 + 2 * self.rlat)
                        if j >= 0 and not t.get("mute"):
                            w = self.mem.get(t["addr"] + j // 2, 0)
                            drive = ((w >> 8) if j % 2 == 0 else w) & 0xFF, 1 - j % 2
            prev_ck = ck
            if drive is not None:
                await FallingEdge(d.clk)
                d.dq_i.value, d.rwds_i.value = drive
