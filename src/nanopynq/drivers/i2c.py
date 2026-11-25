"""Driver for nanopynq:i2c_master:1.0 (src/nanopynq/rtl/i2c_master.v): byte-level commands, polled."""

import time

from nanopynq.errors import I2CError
from nanopynq.ip import DefaultIP

START, STOP, WRITE, READ_ACK, READ_NACK = 1, 2, 3, 4, 5


class I2C(DefaultIP):
    bindto = ["nanopynq:i2c_master:1.0"]
    TIMEOUT = 0.1  # seconds per command; a byte at 100 kHz takes 90 us

    def _cmd(self, op: int, data: int = 0) -> int:
        self.write(0x0, op | (data & 0xFF) << 8)
        t_end = time.monotonic() + self.TIMEOUT
        while True:
            status = self.read(0x4)
            if not status & 1:
                return status
            if time.monotonic() > t_end:
                raise TimeoutError("I2C master stayed busy (no clock on SCL?)")

    def _send(self, addr7: int, byte: int) -> None:
        if self._cmd(WRITE, byte) & 0b10:
            self._cmd(STOP)
            raise I2CError(addr7)

    def write_reg8(self, addr7: int, reg: int, value: int) -> None:
        self._cmd(START)
        for b in (addr7 << 1, reg, value):
            self._send(addr7, b)
        self._cmd(STOP)

    def read_reg8(self, addr7: int, reg: int) -> int:
        """SCCB-style read: write the register address, STOP, then read one byte."""
        self._cmd(START)
        self._send(addr7, addr7 << 1)
        self._send(addr7, reg)
        self._cmd(STOP)
        self._cmd(START)
        self._send(addr7, addr7 << 1 | 1)
        status = self._cmd(READ_NACK)
        self._cmd(STOP)
        return (status >> 8) & 0xFF
