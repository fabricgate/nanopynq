"""Fake UARTBone device: a serial.Serial-compatible port that speaks the protocol."""


class FakeUARTBoneDevice:
    def __init__(self, regs: dict[int, int] | None = None, truncate_after: int | None = None):
        self.regs = {} if regs is None else regs  # keyed by word address (byte addr // 4)
        self.truncate_after = truncate_after  # bytes of response to serve before going silent
        self.received = b""
        self.frames = 0
        self.accesses = []  # ("r" | "w", word address), in order
        self._tx = bytearray()
        self._pending = bytearray()  # incomplete request bytes
        self._served = 0

    def reset_input_buffer(self) -> None:
        self._tx.clear()

    def write(self, b: bytes) -> int:
        self.received += bytes(b)
        self._pending += b
        while self._consume_frame():
            pass
        return len(b)

    def _consume_frame(self) -> bool:
        p = self._pending
        if len(p) < 6:
            return False
        cmd, n = p[0], p[1]
        addr = int.from_bytes(p[2:6], "big")
        is_write = cmd in (0x01, 0x03)
        size = 6 + (4 * n if is_write else 0)
        if len(p) < size:
            return False
        step = 0 if cmd in (0x03, 0x04) else 1
        for i in range(n):
            a = addr + i * step
            self.accesses.append(("w" if is_write else "r", a))
            if is_write:
                self.regs[a] = int.from_bytes(p[6 + 4 * i : 10 + 4 * i], "big")
            else:
                self._tx += self.regs.get(a, 0).to_bytes(4, "big")
        self.frames += 1
        del p[:size]
        return True

    def read(self, n: int) -> bytes:
        if self.truncate_after is not None:
            n = min(n, max(0, self.truncate_after - self._served))
        out = bytes(self._tx[:n])
        del self._tx[:n]
        self._served += len(out)
        return out


class FakeTransport:
    """Register-level transport stub: `regs` is keyed by BYTE address."""

    def __init__(self, regs: dict[int, int] | None = None):
        self.regs = {} if regs is None else regs

    def read(self, addr: int) -> int:
        return self.regs.get(addr, 0)

    def write(self, addr: int, value: int) -> None:
        self.regs[addr] = value


# IEEE 1149.1 TAP: state -> (next on TMS=0, next on TMS=1)
_TAP = {
    "TLR": ("RTI", "TLR"),
    "RTI": ("RTI", "SELDR"),
    "SELDR": ("CAPDR", "SELIR"),
    "CAPDR": ("SHDR", "EX1DR"),
    "SHDR": ("SHDR", "EX1DR"),
    "EX1DR": ("PADR", "UPDR"),
    "PADR": ("PADR", "EX2DR"),
    "EX2DR": ("SHDR", "UPDR"),
    "UPDR": ("RTI", "SELDR"),
    "SELIR": ("CAPIR", "TLR"),
    "CAPIR": ("SHIR", "EX1IR"),
    "SHIR": ("SHIR", "EX1IR"),
    "EX1IR": ("PAIR", "UPIR"),
    "PAIR": ("PAIR", "EX2IR"),
    "EX2IR": ("SHIR", "UPIR"),
    "UPIR": ("RTI", "SELDR"),
}


class FakeJtagBridgeDevice:
    """tms/shift/flush/close port (like transport.mpsse.Mpsse) with a TAP whose IR 0x42 DR is the
    nanopynq JTAG bridge (src/nanopynq/rtl/jtag_bridge.v). `regs` is keyed by WORD address."""

    def __init__(
        self, regs: dict[int, int] | None = None, ignore_ir: bool = False, silent: bool = False, max_read: int = 4096
    ):
        self.max_read = max_read
        self.regs = {} if regs is None else regs
        self.ignore_ir = ignore_ir
        self.silent = silent
        self.state = "TLR"
        self.ir = None
        self._ir_in = 0
        self._dr_in = 0
        self.response = 0
        self.flushes = 0
        self.closed = 0
        self._queue: list[int] = []

    def _step(self, tms: int) -> None:
        self.state = _TAP[self.state][tms]
        if self.state == "TLR":
            self.ir = None
        elif self.state == "UPIR" and not self.ignore_ir:
            self.ir = self._ir_in
        elif self.state == "UPDR" and self.ir == 0x42:
            self._execute(self._dr_in)

    def _execute(self, v: int) -> None:
        if not v >> 63:
            self.response = 0
            return
        addr = (v >> 32) & 0x3FFF_FFFF
        if (v >> 62) & 1:
            self.regs[addr] = v & 0xFFFF_FFFF
            self.response = 1 << 63
        else:
            self.response = (1 << 63) | self.regs.get(addr, 0)

    def tms(self, bits: str) -> None:
        for b in bits:
            self._step(int(b))

    def shift(self, value: int, nbits: int) -> None:
        mask = (1 << nbits) - 1
        if self.state == "SHIR":
            self._ir_in = value & mask
            out = mask
        elif self.state == "SHDR" and self.ir == 0x42:
            out = self.response & mask
            self._dr_in = value & mask
        else:
            out = mask
        self._queue.append(out)
        self._step(1)  # the last bit goes out with TMS=1

    def flush(self) -> list[int]:
        from nanopynq.errors import TransportTimeout

        self.flushes += 1
        out, self._queue = self._queue, []
        if self.silent:
            raise TransportTimeout(9 * len(out), 0)
        return out

    def close(self) -> None:
        self.closed += 1


class FakeCameraBus:
    """Register-level transport (byte addresses) with the camera overlay's add-on IPs:
    i2c_master @0x3000 talking to an OV2640-like device (7-bit 0x30, banks via 0xFF), dvp @0x4000,
    capture @0x10000 (window at +0x8000). `frame` is what the next capture returns."""

    I2C, DVP, CAP = 0x3000, 0x4000, 0x10000

    def __init__(
        self,
        chip_id=0x2642,
        frame=b"",
        capacity=20480,
        overflow=False,
        never_done=False,
        stuck_busy=False,
        i2c_addr=0x30,
        pclks=0,
        lines=0,
    ):
        self.sensor = {0: {}, 1: {0x0A: chip_id >> 8, 0x0B: chip_id & 0xFF}}
        self.bank = 0
        self.writes = []  # (bank, reg, value) written to the sensor
        self.frame, self.capacity, self.overflow, self.never_done = frame, capacity, overflow, never_done
        self.stuck_busy, self.i2c_addr = stuck_busy, i2c_addr
        self.pclks, self.lines = pclks, lines
        self.dvp_ctrl, self.armed, self.done = 0, False, False
        self.window_reads = []  # (addr, length) of every window read
        self._i2c_status, self._i2c_seq, self._ptr = 0, [], 0

    def _i2c_cmd(self, value):
        op, data = value & 7, (value >> 8) & 0xFF
        nack, rdata = 0, (self._i2c_status >> 8) & 0xFF
        if op == 1:  # START
            self._i2c_seq = []
        elif op == 3:  # WRITE
            self._i2c_seq.append(data)
            if len(self._i2c_seq) == 1 and data >> 1 != self.i2c_addr:
                nack = 1
            elif len(self._i2c_seq) == 2 and not self._i2c_seq[0] & 1:
                self._ptr = data
            elif len(self._i2c_seq) == 3 and not self._i2c_seq[0] & 1:
                if self._ptr == 0xFF:
                    self.bank = data
                else:
                    self.writes.append((self.bank, self._ptr, data))
        elif op in (4, 5):  # READ
            rdata = self.sensor.get(self.bank, {}).get(self._ptr, 0)
        self._i2c_status = (rdata << 8) | (nack << 1) | int(self.stuck_busy)

    def write(self, addr, value, burst="incr"):
        if addr == self.I2C:
            self._i2c_cmd(value)
        elif addr == self.DVP:
            self.dvp_ctrl = value
        elif addr == self.CAP and value & 1:
            self.armed, self.done = True, False

    def _read1(self, addr):
        if addr == self.I2C + 4:
            return self._i2c_status
        if addr == self.DVP:
            return self.dvp_ctrl
        if addr == self.DVP + 4:
            return 7
        if addr == self.DVP + 8:
            return self.pclks
        if addr == self.DVP + 0xC:
            return self.lines
        if addr == self.CAP + 4:
            if self.armed and not self.never_done:
                self.armed, self.done = False, True
            return int(self.armed) | int(self.done) << 1 | int(self.overflow and self.done) << 2
        if addr == self.CAP + 8:
            return min(len(self.frame), self.capacity)
        if addr == self.CAP + 12:
            return self.capacity
        if addr >= self.CAP + 0x8000:
            i = addr - self.CAP - 0x8000
            return int.from_bytes(self.frame[i : i + 4].ljust(4, b"\0"), "little")
        return 0

    def read(self, addr, length=None, burst="incr"):
        if length is None:
            return self._read1(addr)
        if addr >= self.CAP + 0x8000:
            self.window_reads.append((addr, length))
        return [self._read1(addr + 4 * i) for i in range(length)]


class FakeRingBus(FakeCameraBus):
    """FakeCameraBus plus frame_ring @0x20000 (src/nanopynq/rtl/frame_ring.v): registers, slots in a fake
    PSRAM and the window at +0x1000 (its burst reads land in window_reads too). `incoming` holds
    (data, bad) frames from the sensor: while the ring is on, one arrives each time WSEQ is read
    (written to a slot, or dropped when the ring is full)."""

    RING = 0x20000

    def __init__(self, incoming=(), nslots=256, slot_words=16384, **kw):
        super().__init__(**kw)
        self.incoming = list(incoming)
        self.nslots, self.slot_words = nslots, slot_words
        self.on, self.wseq, self.rseq, self.dropped = False, 0, 0, 0
        self.psram = {}  # slot -> header + data
        self.window = b""
        self.fetches = []  # (first word, units of 8 words, ring on?)
        self.ctrl_writes = []
        self.fetch_error = False  # STATUS[2]: a read of the fetch came back short

    def _arrive(self):
        if not self.on or not self.incoming:
            return
        data, bad = self.incoming.pop(0)
        if (self.wseq - self.rseq) & 0xFFFF_FFFF >= self.nslots:
            self.dropped += 1
            return
        hdr = len(data) & 0xFFFF | (self.wseq & 0x7FFF) << 16 | int(bad) << 31
        self.psram[self.wseq % self.nslots] = hdr.to_bytes(4, "little") + bytes(data)
        self.wseq = (self.wseq + 1) & 0xFFFF_FFFF

    def write(self, addr, value, burst="incr"):
        r = addr - self.RING
        if r == 0x0:
            self.ctrl_writes.append(value)
            self.on = bool(value & 1)
            if value & 2:
                self.wseq = self.rseq = self.dropped = 0
        elif r == 0x8:
            self.rseq = value
        elif r == 0x10:
            word, units = value & 0x3F_FFFF, value >> 24
            slot, off = divmod(word, self.slot_words)
            self.window = self.psram.get(slot, b"")[2 * off : 2 * off + 16 * units].ljust(16 * units, b"\0")
            self.fetches.append((word, units, self.on))
        else:
            super().write(addr, value, burst)

    def _read1(self, addr):
        r = addr - self.RING
        if r == 0x4:
            self._arrive()
            return self.wseq
        if r in (0x8, 0xC, 0x14, 0x1C):
            return {
                0x8: self.rseq,
                0xC: self.dropped,
                0x14: 4 * self.fetch_error,
                0x1C: self.nslots << 16 | self.slot_words,
            }[r]
        if 0x1000 <= r < 0x1400:
            return int.from_bytes(self.window[r - 0x1000 : r - 0x1000 + 4].ljust(4, b"\0"), "little")
        return super()._read1(addr)


class FakeSdramBus:
    """Register-level transport (byte addresses): sdram window @0x80_0000 (word dict) and sdram_test
    @0x3000. A start (CTRL[0]) makes the test finish at once with `result` = (passes, errors, first)
    where first is (word address, got, exp) or None; never_done: it keeps running."""

    SDRAM, TEST = 0x80_0000, 0x3000

    def __init__(self, result=(1, 0, None), never_done=False, busy=False):
        self.busy = busy  # a run is already active and stays so
        self.mem, self.regs = {}, {0x24: 2}
        self.result, self.never_done = result, never_done
        self.ctrl_writes, self.done = [], False

    def write(self, addr, data, burst="incr"):
        if addr >= self.SDRAM:
            for i, v in enumerate(data if isinstance(data, list) else [data]):
                self.mem[addr + 4 * i] = v
            return
        r = addr - self.TEST
        if r == 0:
            self.ctrl_writes.append(data)
            self.done = bool(data & 1) and not self.never_done
        else:
            self.regs[r] = data

    def _read1(self, addr):
        if addr >= self.SDRAM:
            return self.mem.get(addr, 0)
        r = addr - self.TEST
        passes, errors, first = self.result
        if r == 4:
            if self.busy:
                return 1
            return passes << 16 if self.done else int(bool(self.ctrl_writes) and self.never_done)
        if r == 0x14:
            return errors
        if r in (0x18, 0x1C, 0x20):
            if first is None:
                return 0
            return (1 << 31 | first[0], first[1], first[2])[(r - 0x18) // 4]
        return self.regs.get(r, 0)

    def read(self, addr, length=None, burst="incr"):
        if length is None:
            return self._read1(addr)
        return [self._read1(addr + 4 * i) for i in range(length)]


_GOWIN_OPS = {
    0x11: "IDCODE",
    0x41: "STATUS",
    0x15: "CONFIG_ENABLE",
    0x05: "ERASE_SRAM",
    0x02: "NOOP",
    0x09: "XFER_DONE",
    0x3A: "CONFIG_DISABLE",
    0x12: "INIT_ADDR",
    0x17: "XFER_WRITE",
    0x3C: "RELOAD",
}


class FakeGowinDevice:
    """A transport.jtag.Jtag whose TAP is a Gowin FPGA's configuration port: IR 0x11 reads `idcode`,
    IR 0x41 the status register, and the configuration instructions move the status bits the way the
    GW1N / GW2A do (0x15 sets SYSTEM_EDIT_MODE bit 7, 0x05 MEMORY_ERASE bit 5, 0x3A clears bit 7 and,
    after a XFER_WRITE, sets DONE_FINAL bit 13 if `done`; 0x05 clears DONE_FINAL). Bits in `stuck` never get set,
    bits in `latched` never get cleared.
    `log` lists the instructions received by name; `data` collects what shift_bytes sent after XFER_WRITE."""

    max_read = 4096

    def __init__(self, idcode: int = 0x0000081B, status: int = 0, stuck: int = 0, done: bool = True, latched: int = 0):
        self.idcode, self.status, self.stuck, self.done, self.latched = idcode, status, stuck, done, latched
        self.state = "TLR"
        self._ir_in = 0
        self.ir = None
        self.log: list[str] = []
        self.data = b""
        self._writing = False
        self._queue: list[int] = []
        self.closed = 0

    def _set(self, bit: int) -> None:
        if not self.stuck & bit:
            self.status |= bit

    def _instruction(self, op: int) -> None:
        self.log.append(_GOWIN_OPS.get(op, f"0x{op:02x}"))
        if op == 0x15:
            self._set(1 << 7)
        elif op == 0x05:
            self._set(1 << 5)
            self.status &= ~(1 << 13) | self.latched
        elif op == 0x17:
            self._writing = True
        elif op == 0x3A:
            self.status &= ~(1 << 7)
            if self._writing and self.done:
                self._set(1 << 13)
            self._writing = False

    def _step(self, tms: int) -> None:
        self.state = _TAP[self.state][tms]
        if self.state == "TLR":
            self.ir = None
        elif self.state == "UPIR":
            self.ir = self._ir_in
            self._instruction(self.ir)

    def tms(self, bits: str) -> None:
        for b in bits:
            self._step(int(b))

    def shift(self, value: int, nbits: int) -> None:
        mask = (1 << nbits) - 1
        if self.state == "SHIR":
            self._ir_in = value & mask
            out = mask
        elif self.state == "SHDR":
            out = {0x11: self.idcode, 0x41: self.status}.get(self.ir, 0) & mask
        else:
            out = mask
        self._queue.append(out)
        self._step(1)  # the last bit goes out with TMS=1

    def idle(self, clocks: int) -> None:
        self.log.append(f"IDLE {clocks}")

    def shift_bytes(self, data: bytes) -> None:
        assert self.state == "SHDR" and self._writing, f"data sent in {self.state} (writing={self._writing})"
        self.data += bytes(data)
        self._step(1)

    def flush(self) -> list[int]:
        out, self._queue = self._queue, []
        return out

    def close(self) -> None:
        self.closed += 1


def pwm_netlist(names: bool = True) -> dict:
    """yosys' JSON of examples/tangnano9k_pwm after `hierarchy; proc` (nanopynq.build.collect.elaborate), cut to what
    collect() reads. names: the (* npq_name *) attributes of base_regs.v and the example's top.v."""

    def mod(hdlname, cells=None, **params):
        return {
            "attributes": {"hdlname": hdlname},
            "cells": cells or {},
            "parameter_default_values": {k: f"{v:032b}" for k, v in params.items()},
        }

    def inst(module, name=None):
        return {
            "type": module,
            "attributes": {"src": "top.v:33.5-37.6", **({"npq_name": name} if names and name else {})},
        }

    return {
        "modules": {
            "top": {
                "attributes": {"top": f"{1:032b}"},
                "parameter_default_values": {"DESIGN_ID": f"{0:032b}"},
                "cells": {
                    "bridge": inst("uartbone_bridge"),  # a module left at its defaults is not derived: no hdlname
                    "regs": inst("$paramod$05\\base_regs"),
                    "timer": inst("$paramod\\pwm_timer\\BASE=32'00000000000000000111000000000000", "pwm"),
                    "inv": {"type": "$not", "attributes": {}},
                },
            },  # a yosys cell, not an instance
            "uartbone_bridge": {"attributes": {}, "cells": {}, "parameter_default_values": {}},
            "$paramod$05\\base_regs": mod(
                "base_regs",
                {
                    "si": inst("$paramod\\sysinfo\\DESIGN_ID=32'00000000000000000000000000000000", "sys"),
                    "gpio_leds": inst("$paramod$6e\\regbus_gpio", "leds"),
                    "gpio_btns": inst("$paramod$4c\\regbus_gpio", "buttons"),
                },
                LED_WIDTH=5,
                BTN_WIDTH=2,
                DESIGN_ID=0,
            ),
            "$paramod\\sysinfo\\DESIGN_ID=32'00000000000000000000000000000000": mod("sysinfo", DESIGN_ID=0),
            "$paramod$6e\\regbus_gpio": mod("regbus_gpio", BASE=0x1000, WIDTH=5, IS_INPUT=0),
            "$paramod$4c\\regbus_gpio": mod("regbus_gpio", BASE=0x2000, WIDTH=2, IS_INPUT=1),
            "$paramod\\pwm_timer\\BASE=32'00000000000000000111000000000000": mod("pwm_timer", BASE=0x7000),
        }
    }


def own_netlist(module: str, **params) -> dict:
    """pwm_netlist() without npq_name, where `module` is the user's own module of that name, with these Verilog
    parameters."""
    n = pwm_netlist(names=False)
    for m in n["modules"].values():
        if m["attributes"].get("hdlname") == module:
            m["parameter_default_values"] = {k: f"{v:032b}" for k, v in params.items()}
    return n


def d2xx_device(
    index: int, interface: str = "A", serial: str = "2025030317", flags: int = 2, usb_id: int = 0x04036010
) -> dict:
    """One entry of FakeD2xx.devices(), as FT_GetDeviceInfoDetail gives it (flags bit 1 = high speed)."""
    return {
        "index": index,
        "flags": flags,
        "id": usb_id,
        "serial": serial + interface,
        "description": f"USB Debugger {interface}",
    }


class FakeD2xx:
    """transport.d2xx.D2xx with a debugger behind it: writes are recorded in `out`; a write that starts with
    0x19, 0x39 or 0x1B (a shift_bytes chunk or its closing write) gets its one TDO byte back, and `next_reply`
    is what arrives after the next write (like tests/test_mpsse.py's FakeUsb)."""

    def __init__(self, devices: list[dict]):
        self._devices = devices
        self.opened: list[int] = []
        self.setups = 0
        self.closed = 0
        self.purges = 0
        self.out = bytearray()
        self.next_reply = b""
        self.pending = bytearray()

    def devices(self) -> list[dict]:
        return list(self._devices)

    def open(self, index: int):
        self.opened.append(index)
        return ("handle", index)

    def setup(self, handle) -> None:
        self.setups += 1

    def write(self, handle, data: bytes) -> int:
        self.out += bytes(data)
        if bytes(data)[:1] in (bytes([0x19]), bytes([0x39]), bytes([0x1B])):
            self.pending += bytes([0])
        self.pending += self.next_reply
        self.next_reply = b""
        return len(data)

    def read(self, handle, n: int) -> bytes:
        out = bytes(self.pending[:n])
        del self.pending[:n]
        return out

    def queued(self, handle) -> int:
        return len(self.pending)

    def purge_rx(self, handle) -> None:
        self.purges += 1
        self.pending.clear()

    def close(self, handle) -> None:
        self.closed += 1
