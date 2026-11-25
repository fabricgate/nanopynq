"""Host client for the nanopynq JTAG bridge (src/nanopynq/rtl/jtag_bridge.v) behind GW_JTAG's ER1 (IR 0x42).

One 64-bit DR scan carries one command ([63] valid, [62] write, [61:32] word address, [31:0] data);
the next scan returns its response ([63] done, [62:32] 0, [31:0] read data). Same read/write shape
as UARTBone, so Overlay and the IP drivers do not care which link is used.
"""

from nanopynq.errors import BridgeError

_DONE = 1 << 31  # response >> 32 for a good response
CHUNK = 100  # words per USB transfer: the BL702 returns about 1 KB per transfer, 9 bytes per scan


def _command(addr: int, write: bool = False, data: int = 0) -> int:
    return (1 << 63) | (int(write) << 62) | ((addr // 4) << 32) | (data & 0xFFFF_FFFF)


def _check(addr: int, burst: str, n: int = 1) -> int:
    if addr % 4:
        raise ValueError(f"address 0x{addr:x} is not 4-byte aligned")
    if burst not in ("incr", "fixed"):
        raise ValueError(f"burst must be 'incr' or 'fixed', not {burst!r}")
    step = 4 if burst == "incr" else 0
    if not 0 <= addr <= addr + step * (n - 1) < 1 << 32:  # a wider word address would spill into the write bit
        raise ValueError(f"address 0x{addr:x} (+{n} words) is out of the 32-bit range")
    return step


class JTAGBridge:
    IR_USER = 0x42

    def __init__(self, jtag):
        self.jtag = jtag  # a transport.jtag.Jtag
        self.reset()

    @classmethod
    def open(cls, host_link: dict, find=None) -> "JTAGBridge":
        from nanopynq.transport.jtag import open_jtag

        m = open_jtag(host_link["usb_vid"], host_link["usb_pid"], find)
        try:
            return cls(m)
        except BaseException:
            m.close()  # never leave the interface claimed: openFPGALoader needs it next time
            raise

    def reset(self) -> None:
        """Test-Logic-Reset -> load IR 0x42 -> one no-op DR scan, ending in Run-Test/Idle."""
        self.jtag.tms("11111")
        self.jtag.tms("01100")
        self.jtag.shift(self.IR_USER, 8)
        self.jtag.tms("10")
        self._dr(0)
        self.jtag.flush()

    def _dr(self, value: int) -> None:
        self.jtag.tms("100")
        self.jtag.shift(value, 64)
        self.jtag.tms("10")

    def _ops(self, commands: list[int]) -> list[int]:
        """Run commands, `chunk` per USB transfer: scan k returns the result of command k-1."""
        chunk = min(CHUNK, self.jtag.max_read // 9 - 1)  # 9 TDO bytes per scan, plus the closing scan
        out = []
        for i in range(0, len(commands), chunk):
            for c in commands[i : i + chunk]:
                self._dr(c)
            self._dr(0)
            for resp in self.jtag.flush()[1:]:
                if resp >> 32 != _DONE:
                    raise BridgeError(resp)
                out.append(resp & 0xFFFF_FFFF)
        return out

    def read(self, addr: int, length: int | None = None, burst: str = "incr") -> int | list[int]:
        n = 1 if length is None else length
        if n < 1:
            raise ValueError("length must be >= 1")
        step = _check(addr, burst, n)
        words = self._ops([_command(addr + step * i) for i in range(n)])
        return words[0] if length is None else words

    def write(self, addr: int, data: int | list[int], burst: str = "incr") -> None:
        words = [data] if isinstance(data, int) else list(data)
        step = _check(addr, burst, len(words))
        self._ops([_command(addr + step * i, write=True, data=w) for i, w in enumerate(words)])

    def close(self) -> None:
        self.jtag.close()
