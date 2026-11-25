"""Driver for nanopynq:dvp:1.0 (src/nanopynq/rtl/dvp_frontend.v): XCLK, which bytes of a line to keep,
and which VSYNC level marks the frame."""

from nanopynq.ip import DefaultIP

_KEEP = {"all": 0, "even": 1, "odd": 2}


class DVP(DefaultIP):
    bindto = ["nanopynq:dvp:1.0"]

    def _set(self, mask: int, value: int) -> None:
        self.write(0x0, (self.read(0x0) & ~mask) | value)

    def xclk(self, on: bool) -> None:
        self._set(0b0001, int(on))

    def keep(self, mode: str) -> None:
        if mode not in _KEEP:
            raise ValueError(f"keep must be one of {sorted(_KEEP)}, not {mode!r}")
        self._set(0b0110, _KEEP[mode] << 1)

    def frame_level(self, high: bool) -> None:
        """True: the frame is while VSYNC is high; False: while it is low."""
        self._set(0b1000, int(high) << 3)

    @property
    def frames(self) -> int:
        """VSYNC pulses seen so far (changes while the sensor is running)."""
        return self.read(0x4)

    @property
    def pclks(self) -> int:
        """PCLK periods while VSYNC was at the frame level, in the last whole frame."""
        return self.read(0x8)

    @property
    def lines(self) -> int:
        """HREF pulses in the last whole frame."""
        return self.read(0xC)
