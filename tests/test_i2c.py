import pytest

from nanopynq.drivers.i2c import I2C
from nanopynq.errors import I2CError
from tests.fakes import FakeCameraBus

DESC = {"phys_addr": 0x3000, "registers": {}, "parameters": {}}


def test_write_reg8_reaches_the_device():
    bus = FakeCameraBus()
    I2C(DESC, bus).write_reg8(0x30, 0x12, 0x80)
    assert bus.writes == [(0, 0x12, 0x80)]


def test_read_reg8_uses_sccb_sequence():
    bus = FakeCameraBus(chip_id=0x2642)
    i2c = I2C(DESC, bus)
    i2c.write_reg8(0x30, 0xFF, 0x01)
    assert (i2c.read_reg8(0x30, 0x0A), i2c.read_reg8(0x30, 0x0B)) == (0x26, 0x42)


def test_nack_raises_i2c_error_with_address():  # Review Focus 2
    with pytest.raises(I2CError, match="0x31") as e:
        I2C(DESC, FakeCameraBus()).write_reg8(0x31, 0, 0)
    assert e.value.addr == 0x31


def test_busy_forever_times_out(monkeypatch):  # Review Focus 2
    monkeypatch.setattr(I2C, "TIMEOUT", 0.01)
    with pytest.raises(TimeoutError, match="busy"):
        I2C(DESC, FakeCameraBus(stuck_busy=True)).write_reg8(0x30, 0, 0)
