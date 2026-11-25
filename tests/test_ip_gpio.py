import pytest

from nanopynq.drivers.gpio import GPIOIn, GPIOOut
from nanopynq.ip import DefaultIP, driver_for
from tests.fakes import FakeTransport


def leds_desc(w=6):
    return {
        "name": "leds",
        "type": "nanopynq:gpio_out:1.0",
        "phys_addr": 0x1000,
        "addr_range": 0x1000,
        "parameters": {"width": w},
        "registers": {"data": {"offset": 0, "width": w, "access": "rw"}},
    }


def buttons_desc(w=2):
    return {
        "name": "buttons",
        "type": "nanopynq:gpio_in:1.0",
        "phys_addr": 0x2000,
        "addr_range": 0x1000,
        "parameters": {"width": w},
        "registers": {"data": {"offset": 0, "width": w, "access": "ro"}},
    }


def test_bindto_selects_gpio_out():
    assert driver_for("nanopynq:gpio_out:1.0") is GPIOOut
    assert driver_for("nanopynq:gpio_in:1.0") is GPIOIn
    assert driver_for("unknown:x:1.0") is DefaultIP


def test_pin_on_off_toggle_preserves_other_bits():
    t = FakeTransport({0x1000: 0b100})
    leds = GPIOOut(leds_desc(), t)
    leds[0].on()
    assert t.regs[0x1000] == 0b101
    leds[2].off()
    assert t.regs[0x1000] == 0b001
    leds[0].toggle()
    assert t.regs[0x1000] == 0
    assert len(leds) == 6


def test_gpio_out_read_and_write_all():
    t = FakeTransport({})
    leds = GPIOOut(leds_desc(), t)
    leds.write_all(0b010)
    assert t.regs[0x1000] == 0b010
    assert leds[1].read() == 1
    assert leds[0].read() == 0


def test_index_out_of_range():
    with pytest.raises(IndexError):
        GPIOOut(leds_desc(6), FakeTransport({}))[6]
    with pytest.raises(IndexError):
        GPIOOut(leds_desc(6), FakeTransport({}))[-1]


def test_gpio_in_read_bit():
    t = FakeTransport({0x2000: 0b10})
    buttons = GPIOIn(buttons_desc(), t)
    assert buttons[1].read() == 1
    assert buttons[0].read() == 0
    assert buttons.read_all() == 0b10
    assert len(buttons) == 2
    with pytest.raises(IndexError):
        buttons[2]


def test_register_map_reads_named_registers():
    desc = leds_desc()
    desc["registers"]["extra"] = {"offset": 4, "width": 32, "access": "ro"}
    t = FakeTransport({0x1000: 0b11, 0x1004: 0xDEAD})
    ip = DefaultIP(desc, t)
    assert ip.register_map == {"data": 0b11, "extra": 0xDEAD}
    ip.write(4, 7)
    assert t.regs[0x1004] == 7
    assert ip.read(4) == 7


def test_register_map_does_not_read_wo_or_read_effect_registers():
    desc = leds_desc()
    desc["registers"] |= {
        "cmd": {"offset": 4, "width": 8, "access": "wo"},
        "pop": {"offset": 8, "width": 8, "access": "ro", "read_effect": True},
    }

    class Recording(FakeTransport):
        def read(self, addr):
            reads.append(addr)
            return super().read(addr)

    reads = []
    assert DefaultIP(desc, Recording({0x1000: 1})).register_map == {"data": 1}
    assert reads == [0x1000]
