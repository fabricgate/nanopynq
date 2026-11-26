import sys
import time
from types import SimpleNamespace

import pytest
import usb.core
import usb.util

from nanopynq.errors import PortNotFound, PortOpenError, TransportTimeout
from nanopynq.transport.jtagbridge import JTAGBridge
from nanopynq.transport.mpsse import Mpsse, decode_shift, encode_shift

# MPSSE command lengths, to split what the driver wrote back into commands.
_LEN = {0x85: 1, 0x87: 1, 0x80: 3, 0x86: 3, 0x4B: 3, 0x3B: 3, 0x6B: 3, 0x1B: 3}
_VARLEN = (0x39, 0x19, 0x11)  # byte shifts: 3 header bytes + (length + 1) data bytes


class FakeUsb:
    """The pyusb device calls Mpsse makes; IN reads carry 2 modem-status bytes per packet of pkt bytes
    (64 on the BL702, 512 on the Tang Nano 20K's BL616)."""

    def __init__(self, serial: str, claim_error: Exception | bool = False, pkt: int = 64, configured: bool = True):
        self._serial = serial
        self.pkt = pkt
        self.claim_error = claim_error
        self.configured = configured
        self.out = bytearray()
        self.ctrl = []
        self.released = False
        self.disposed = False
        self.read_error = None  # exception raised by read()
        self.write_error = None  # exception raised by write()
        self.next_reply = b""  # bytes that arrive after the next write
        self._in = bytearray()

    @property
    def serial_number(self):
        if isinstance(self._serial, Exception):
            raise self._serial
        return self._serial

    def is_kernel_driver_active(self, iface):
        return False

    def set_configuration(self):
        if self.configured:  # Linux usbfs refuses while ftdi_sio holds Interface 1 (the UART)
            raise usb.core.USBError("Resource busy", errno=16)
        self.configured = True

    def get_active_configuration(self):
        if not self.configured:
            raise usb.core.USBError("Configuration not set")
        eps = [SimpleNamespace(bEndpointAddress=a, wMaxPacketSize=self.pkt) for a in (0x81, 0x02)]
        return {(0, 0): eps}

    def ctrl_transfer(self, *args):
        self.ctrl.append(args)
        if args[1:3] == (0x00, 1):  # purge RX
            self._in.clear()

    def write(self, ep, data, timeout):
        if self.write_error:
            raise self.write_error
        self.out += bytes(data)
        self._in += self.next_reply
        self.next_reply = b""
        return len(data)

    def reply(self, data: bytes) -> None:
        self._in += data

    def read(self, ep, size, timeout):
        if self.read_error:
            raise self.read_error
        if not self._in:
            time.sleep(0.005)
            return bytes([0x31, 0x60])
        out = bytearray()  # as many whole packets as fit in size, like a real bulk read
        while self._in and len(out) + self.pkt <= size:
            n = self.pkt - 2
            out += bytes([0x31, 0x60]) + self._in[:n]
            self._in = self._in[n:]
        return bytes(out)

    def opcodes(self) -> list[int]:
        ops, i, b = [], 0, self.out
        while i < len(b):
            op = b[i]
            ops.append(op)
            i += 3 + (b[i + 1] | b[i + 2] << 8) + 1 if op in _VARLEN else _LEN[op]
        return ops


@pytest.fixture(autouse=True)
def fake_usb_util(monkeypatch):
    def claim(dev, iface):
        if isinstance(dev.claim_error, Exception):
            raise dev.claim_error
        if dev.claim_error:
            raise usb.core.USBError("Access denied (insufficient permissions)")

    def release(dev, iface):
        dev.released = True

    monkeypatch.setattr(usb.util, "claim_interface", claim)
    monkeypatch.setattr(usb.util, "release_interface", release)
    monkeypatch.setattr(usb.util, "dispose_resources", lambda dev: setattr(dev, "disposed", True))


def opened(dev):
    return Mpsse.open(0x0403, 0x6010, find=lambda **kw: [dev])


def test_encode_shift_64():
    assert encode_shift(0xFEDCBA9876543210, 64) == bytes.fromhex("39 06 00 10 32 54 76 98 ba dc 3b 06 7e 6b 00 81")


def test_decode_shift_64():
    resp = bytes([0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFC, 0x80])
    assert decode_shift(resp, 64) == 0xFEDCBA9876543210


def test_encode_shift_8_has_no_byte_part():
    assert encode_shift(0x42, 8) == bytes.fromhex("3b 06 42 6b 00 01")


def test_open_not_found_hints_zadig_or_udev():  # Review Focus 3
    with pytest.raises(PortNotFound, match="Zadig" if sys.platform == "win32" else "udev"):
        Mpsse.open(0x0403, 0x6010, find=lambda **kw: [])


def test_open_goes_on_when_something_else_detached_the_driver_first():
    """The udev rule unbinds ftdi_sio from Interface 0 right after it binds; Mpsse.open may see it bound, then find
    it gone when it detaches (after openFPGALoader, which re-attaches the driver when it closes)."""

    class Raced(FakeUsb):
        def is_kernel_driver_active(self, iface):
            return self.active.pop(0)

        def detach_kernel_driver(self, iface):
            raise usb.core.USBError("Entity not found", errno=2)  # what libusb said on the board

    dev = Raced("A1")
    dev.active = [True, False]  # bound when asked first; gone by the time the failed detach is checked
    Mpsse.open(0x0403, 0x6010, find=lambda **kw: [dev]).close()
    assert dev.released and dev.active == []

    still = Raced("A1")
    still.active = [True, True]  # really still bound: the failure stands
    with pytest.raises(PortOpenError):
        Mpsse.open(0x0403, 0x6010, find=lambda **kw: [still])


def test_open_two_boards_lists_serials():  # Review Focus 3
    with pytest.raises(PortNotFound, match=r"A1.*B2"):
        Mpsse.open(0x0403, 0x6010, find=lambda **kw: [FakeUsb("A1"), FakeUsb("B2")])


def test_open_claim_failure_is_port_open_error():  # Review Focus 2, 3
    with pytest.raises(PortOpenError, match=r"ol\.close\(\)") as e:
        opened(FakeUsb("A1", claim_error=True))
    if sys.platform == "win32":
        assert "Zadig" in str(e.value)


def test_open_keeps_the_active_configuration():
    opened(FakeUsb("A1"))  # set_configuration() would raise EBUSY, as on Linux with the UART bound


def test_open_sets_the_configuration_when_unconfigured():
    dev = FakeUsb("A1", configured=False)
    opened(dev)
    assert dev.configured


def test_open_sends_only_allowed_commands():
    dev = FakeUsb("A1")
    m = opened(dev)
    m.tms("11111")
    m.shift(0x42, 8)
    dev.reply(b"\x00\x00")
    m.flush()
    assert set(dev.opcodes()) <= {0x39, 0x3B, 0x4B, 0x6B, 0x80, 0x85, 0x86, 0x87}
    assert dev.opcodes()[-4:] == [0x4B, 0x3B, 0x6B, 0x87]


def test_idle_below_one_clock_is_a_value_error():
    with pytest.raises(ValueError, match="clocks"):
        opened(FakeUsb("A1")).idle(0)


def test_flush_decodes_each_shift_in_order():
    dev = FakeUsb("A1")
    m = opened(dev)
    m.shift(0, 8)
    m.tms("10")
    m.shift(0, 64)
    dev.reply(bytes([0x0A << 1, 0x80]) + bytes([0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFC, 0x80]))
    assert m.flush() == [0x8A, 0xFEDCBA9876543210]


def test_flush_times_out_when_device_is_silent():  # Review Focus 1
    m = opened(FakeUsb("A1"))
    m.shift(0, 64)
    t0 = time.perf_counter()
    with pytest.raises(TransportTimeout):
        m.flush()
    assert time.perf_counter() - t0 < 2.0


def test_close_releases_interface():
    dev = FakeUsb("A1")
    opened(dev).close()
    assert dev.released


def test_bridge_open_closes_usb_when_reset_fails():  # Review Focus 2
    dev = FakeUsb("A1")  # never answers
    with pytest.raises(TransportTimeout):
        JTAGBridge.open({"usb_vid": 0x0403, "usb_pid": 0x6010}, find=lambda **kw: [dev])
    assert dev.released


def test_open_not_supported_is_port_open_error():  # Review Focus 3 (libusb NOT_SUPPORTED)
    dev = FakeUsb("A1", claim_error=NotImplementedError("Operation not supported"))
    with pytest.raises(PortOpenError, match=r"ol\.close\(\)"):
        opened(dev)
    assert dev.disposed


def test_open_setup_usb_error_is_port_open_error_and_disposes():
    dev = FakeUsb("A1")
    dev.read_error = usb.core.USBError("Input/Output Error")  # during the post-claim drain
    with pytest.raises(PortOpenError):
        opened(dev)
    assert dev.disposed and dev.released


def test_two_boards_with_unreadable_serial_still_listed():
    with pytest.raises(PortNotFound, match="multiple boards"):
        Mpsse.open(0x0403, 0x6010, find=lambda **kw: [FakeUsb(usb.core.USBError("busy")), FakeUsb("B2")])


def test_write_usb_error_becomes_timeout():  # Review Focus 1
    dev = FakeUsb("A1")
    m = opened(dev)
    dev.write_error = usb.core.USBTimeoutError("Operation timed out")
    m.shift(0, 8)
    with pytest.raises(TransportTimeout):
        m.flush()


def test_read_usb_error_becomes_timeout():  # Review Focus 1
    dev = FakeUsb("A1")
    m = opened(dev)
    dev.read_error = usb.core.USBError("Input/Output Error")
    m.shift(0, 8)
    with pytest.raises(TransportTimeout):
        m.flush()


def test_late_reply_after_timeout_is_not_returned_by_next_flush():
    dev = FakeUsb("A1")
    m = opened(dev)
    m.shift(0, 8)
    with pytest.raises(TransportTimeout):
        m.flush()
    dev.reply(bytes([0xAA, 0x80]))  # the first flush's answer arrives late
    m.shift(0, 8)
    dev.next_reply = bytes([0x0A << 1, 0x00])
    assert m.flush() == [0x0A]


@pytest.mark.parametrize("pkt", [64, 512])
def test_long_reply_strips_status_bytes_per_packet(pkt):
    dev = FakeUsb("A1", pkt=pkt)
    m = opened(dev)
    values = [(0x0123456789ABCDEF * (i + 1)) & ((1 << 64) - 1) for i in range(100)]  # 900 bytes back
    for v in values:
        m.shift(0, 64)
        b = v.to_bytes(8, "little")
        dev.reply(b[:7] + bytes([(b[7] & 0x7F) << 1, b[7] & 0x80]))
    assert m.flush() == values


def test_max_read_follows_packet_size():
    assert opened(FakeUsb("A1", pkt=64)).max_read == 1024
    assert opened(FakeUsb("A1", pkt=512)).max_read == 4096


class EchoUsb(FakeUsb):
    """Answers the one TDO byte shift_bytes waits for after each of its writes (a chunk ends with a 1-byte 0x39,
    the closing write with 0x6B); a plain flush of queued TMS gets no answer."""

    def write(self, ep, data, timeout):
        n = super().write(ep, data, timeout)
        if bytes(data)[:1] in (b"\x11", b"\x19", b"\x39", b"\x1b"):
            self.reply(b"\x00")
        return n


def _commands(out: bytes) -> list[tuple[int, int]]:
    """(opcode, data length) of each MPSSE command in what the driver wrote; length 0 for fixed-size ones."""
    cmds, i = [], 0
    while i < len(out):
        op = out[i]
        if op in _VARLEN:
            n = (out[i + 1] | out[i + 2] << 8) + 1
            cmds.append((op, n))
            i += 3 + n
        else:
            cmds.append((op, 0))
            i += _LEN[op]
    return cmds


def test_shift_bytes_sends_queued_tms_first():  # Review Focus 1
    dev = EchoUsb("A1")
    m = opened(dev)
    dev.out.clear()
    m.tms("100")
    m.shift_bytes(bytes([0x01, 0x02, 0x80]))
    ops = dev.opcodes()
    assert ops[0] == 0x4B  # TMS to Shift-DR goes out before any data
    assert ops[-2:] == [0x6B, 0x87]  # last bit with TMS=1, then send-immediate


def test_shift_bytes_payload_and_last_bit():
    dev = EchoUsb("A1")
    m = opened(dev)
    dev.out.clear()
    m.shift_bytes(bytes([0xA5, 0x80]))
    # 0xA5 is the only (and so the last) byte of its chunk: 0x39 with read-back, then wait. Then 7 bits of 0x80 as
    # a bit write, and its bit 7 as TDI of the 0x6B (TMS=1)
    assert bytes(dev.out) == bytes([0x39, 0, 0, 0xA5, 0x87, 0x1B, 6, 0x00, 0x6B, 0x00, 0x81, 0x87])


@pytest.mark.parametrize("pkt, chunk", [(64, 1024), (512, 0x4000)])
def test_shift_bytes_waits_for_the_debugger_after_each_chunk(pkt, chunk):
    # Without waiting, the host runs ahead of the debugger: on the 9K (BL702) about one load in four failed, and a
    # failed one once left the FPGA with POR clear and a wrong IDCODE until a power cycle. Each chunk now ends with
    # its last byte read back (0x39) and the host waits for that byte. A BL702 transfer must also stay within 1 KB.
    dev = EchoUsb("A1", pkt=pkt)
    m = opened(dev)
    dev.out.clear()
    m.shift_bytes(bytes(40000))
    cmds = _commands(bytes(dev.out))[:-3]  # drop the closing 0x1B, 0x6B, 0x87 of the last byte
    chunks = [cmds[i : i + 3] for i in range(0, len(cmds), 3)]
    assert all(c[0][0] == 0x19 and c[1] == (0x39, 1) and c[2] == (0x87, 0) for c in chunks), chunks[:2]
    assert max(c[0][1] for c in chunks) == chunk - 1
    assert sum(c[0][1] + 1 for c in chunks) == 39999


def test_open_failure_says_no_other_program_may_hold_it():
    with pytest.raises(PortOpenError, match=r"no other program \(openFPGALoader included\)"):
        opened(FakeUsb("A1", claim_error=True))


def test_linux_not_found_points_to_bundled_udev_rule(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(PortNotFound, match=r"99-nanopynq.rules"):
        Mpsse.open(0x0403, 0x6010, find=lambda **kw: [])


def test_close_survives_a_vanished_device(monkeypatch):  # Review Focus 5
    # libusb refuses to release the interface of an unplugged device; close() must still free the handle and
    # must not raise, or it would replace the error that ended the load (program_sram closes in a finally).
    dev = FakeUsb("A1")
    m = opened(dev)

    def gone(d, iface):
        raise usb.core.USBError("No such device (it may have been disconnected)", errno=19)

    monkeypatch.setattr(usb.util, "release_interface", gone)
    m.close()
    assert dev.disposed


def test_windows_hint_says_ftdis_driver_works_too(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(PortNotFound, match="FTDI's driver"):
        Mpsse.open(0x0403, 0x6010, find=lambda **kw: [])


@pytest.mark.parametrize("pkt, chunk", [(64, 1024), (512, 0x4000)])
def test_idle_clocks_zero_bytes_paced_like_shift_bytes(pkt, chunk):
    # The BL616 answers 0x8F (clocks without data) with 0xFA "bad command" (2026-11-21), so idle clocks zero bytes
    # with the data commands shift_bytes uses; TMS stays where the last tms() left it.
    dev = EchoUsb("A1", pkt=pkt)
    m = opened(dev)
    dev.out.clear()
    m.idle(1_000_000)  # 125000 bytes of 8 clocks
    cmds = _commands(bytes(dev.out))
    assert {op for op, _ in cmds} == {0x19, 0x39, 0x87}
    assert sum(n for op, n in cmds if op in (0x19, 0x39)) == 125000
    assert max(n for op, n in cmds if op == 0x19) == chunk - 1
    assert [op for op, _ in cmds].count(0x87) == -(-125000 // chunk)  # one wait per chunk


def test_idle_rounds_up_to_whole_bytes():
    dev = EchoUsb("A1")
    m = opened(dev)
    dev.out.clear()
    m.idle(9)  # 2 bytes = 16 clocks: one by 0x19, the last read back by 0x39
    assert bytes(dev.out) == bytes([0x19, 0, 0, 0x00, 0x39, 0, 0, 0x00, 0x87])


def test_idle_sends_queued_tms_first():
    dev = EchoUsb("A1")
    m = opened(dev)
    dev.out.clear()
    m.tms("0")
    m.idle(8)
    assert [op for op, _ in _commands(bytes(dev.out))] == [0x4B, 0x87, 0x39, 0x87]


def test_shift_bytes_msb_first_sends_the_body_as_0x11():
    # The 138K Pro's BL616 is about 6x faster with 0x11 (MSB first) than with 0x19 (reports/report_tangmega138kpro.md).
    # The bits on the wire stay the same: each byte goes out bit-reversed, MSB first.
    dev = EchoUsb("A1")
    m = opened(dev)
    m.msb_first = True
    dev.out.clear()
    m.shift_bytes(bytes([0x01, 0x02, 0x80]))
    assert bytes(dev.out) == bytes([0x11, 0, 0, 0x80, 0x39, 0, 0, 0x02, 0x87, 0x1B, 6, 0x00, 0x6B, 0x00, 0x81, 0x87])


def test_shift_bytes_msb_first_keeps_each_0x11_within_4096_bytes():
    # 0x11 commands of 16 KB broke on the BL616 (it read the rest of the data as commands); 4096 passed.
    dev = EchoUsb("A1", pkt=512)
    m = opened(dev)
    m.msb_first = True
    dev.out.clear()
    data = bytes(range(256)) * 160  # 40960 bytes
    m.shift_bytes(data)
    out, cmds, i, body = bytes(dev.out), [], 0, bytearray()
    for op, n in _commands(out):
        if op == 0x11:
            body += out[i + 3 : i + 3 + n]
        cmds.append((op, n))
        i += 3 + n if op in (0x11, 0x19, 0x39) else _LEN[op]
    assert max(n for op, n in cmds if op == 0x11) <= 4096 and not any(op == 0x19 for op, _ in cmds)
    assert [op for op, _ in cmds].count(0x39) == -(-(len(data) - 1) // 0x4000)  # one read-back per chunk
    tails = [out[j + 3] for j in range(len(out)) if out[j : j + 3] == bytes([0x39, 0, 0])]
    assert len(body) + len(tails) == len(data) - 1


def test_idle_msb_first_clocks_with_0x11():
    dev = EchoUsb("A1")
    m = opened(dev)
    m.msb_first = True
    dev.out.clear()
    m.idle(17)  # 3 bytes: two by 0x11, the last read back by 0x39
    assert bytes(dev.out) == bytes([0x11, 1, 0, 0, 0, 0x39, 0, 0, 0x00, 0x87])
