"""transport/d2xx.py: the debugger's JTAG through FTDI's D2XX, on a fake D2XX (tests/fakes.py FakeD2xx)."""

import pytest

from nanopynq.errors import PortNotFound, PortOpenError, TransportTimeout
from nanopynq.transport import d2xx as d2xx_mod
from nanopynq.transport.d2xx import D2xxMpsse
from tests.fakes import FakeD2xx, d2xx_device


def opened(fake):
    return D2xxMpsse.open(0x0403, 0x6010, d2xx=fake)


def test_picks_interface_a_by_description():  # Review Focus 1
    # The 9K's debugger lists interface B first (#50), so the order says nothing.
    fake = FakeD2xx([d2xx_device(0, "B", flags=0), d2xx_device(1, "A", flags=0)])
    m = opened(fake)
    assert fake.opened == [1] and fake.setups == 1
    m.close()
    assert fake.closed == 1


@pytest.mark.parametrize("flags, max_read", [(2, 4096), (0, 1024)])  # bit 1: high speed (BL616) or not (BL702)
def test_high_speed_flag_sets_packet_size(flags, max_read):
    assert opened(FakeD2xx([d2xx_device(0, flags=flags)])).max_read == max_read


def test_no_board_is_port_not_found():
    with pytest.raises(PortNotFound, match="0403:6010"):
        opened(FakeD2xx([d2xx_device(0, usb_id=0x04036001)]))


def test_two_boards_is_port_not_found_with_serials():
    fake = FakeD2xx([d2xx_device(0, serial="AAA"), d2xx_device(1, serial="BBB")])
    with pytest.raises(PortNotFound, match=r"AAAA.*BBBA"):
        opened(fake)
    assert fake.opened == []


def test_interface_a_open_elsewhere_is_port_open_error():  # Review Focus 4
    fake = FakeD2xx([d2xx_device(0, "B"), d2xx_device(1, "A", flags=2 | 1)])
    with pytest.raises(PortOpenError, match="another program"):
        opened(fake)
    assert fake.opened == []


def test_an_unidentified_open_device_is_not_called_our_jtag():
    # An entry that is open elsewhere (or unreadable) lists flags bit 0 and no ID or name (#50). On the 9K with
    # Interface 0 on WinUSB, the only entry was interface B looking like that, and COM3 opened fine: saying
    # "the JTAG interface is open in another program" was wrong. Not found, so open_jtag shows libusb's error.
    unknown = {"index": 0, "flags": 1, "id": 0, "serial": "", "description": ""}
    fake = FakeD2xx([unknown])
    with pytest.raises(PortNotFound, match="open in another program or unreadable"):
        opened(fake)
    assert fake.opened == []


def test_missing_dll_is_port_not_found(monkeypatch):
    def no_dll():
        raise OSError("ftd2xx.dll not found")

    monkeypatch.setattr(d2xx_mod, "D2xx", no_dll)
    with pytest.raises(PortNotFound, match="D2XX"):
        D2xxMpsse.open(0x0403, 0x6010)


def test_shift_bytes_waits_per_chunk_over_d2xx():
    # The BL702 (no high-speed flag) takes 1024 bytes per write, and the host waits after each chunk (PR #66).
    fake = FakeD2xx([d2xx_device(0, flags=0)])
    m = opened(fake)
    fake.out.clear()
    m.shift_bytes(bytes(3000))
    out = bytes(fake.out)
    assert out.count(bytes([0x39, 0, 0])) == 3  # 2999 bytes before the last one: chunks of 1024, 1024, 951
    assert out.startswith(bytes([0x19, 0xFE, 0x03]))  # 1023 bytes write-only, then the chunk's last byte read back


def test_stale_flush_purges_with_d2xx():  # Review Focus 5
    fake = FakeD2xx([d2xx_device(0)])
    m = opened(fake)
    m.shift(0x42, 8)
    with pytest.raises(TransportTimeout):
        m.flush()  # nothing answers
    fake.pending += b"late"  # the answer arrives after all
    m.shift(0x42, 8)
    fake.next_reply = bytes([0x42 << 1, 0x00])  # bit-mode TDO comes MSB-aligned (mpsse.decode_shift)
    purges = fake.purges
    assert m.flush() == [0x42]
    assert fake.purges == purges + 1


def test_high_speed_debugger_writes_16_kib_chunks():
    # The BL616 (high-speed flag) took 16 KiB writes on the 20K; the BL702 gets 1024 (test above).
    fake = FakeD2xx([d2xx_device(0, flags=2)])
    m = opened(fake)
    fake.out.clear()
    m.shift_bytes(bytes(40000))
    assert bytes(fake.out).startswith(bytes([0x19, 0xFE, 0x3F]))  # 16383 bytes write-only, then 1 read back
