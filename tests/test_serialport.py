from types import SimpleNamespace

import pytest

from nanopynq.boards import get_board
from nanopynq.errors import PortNotFound
from nanopynq.transport.serialport import find_port


def fake_port(device, vid, pid, location, serial_number=None):
    return SimpleNamespace(device=device, vid=vid, pid=pid, location=location, serial_number=serial_number)


def test_find_port_ambiguous_lists_candidates():  # Review Focus 3
    ports = [fake_port("/dev/ttyUSB0", 0x0403, 0x6010, "1-1:1.1"), fake_port("/dev/ttyUSB2", 0x0403, 0x6010, "1-2:1.1")]
    with pytest.raises(PortNotFound) as e:
        find_port(get_board("tangnano9k"), ports)
    assert "/dev/ttyUSB0" in str(e.value) and "/dev/ttyUSB2" in str(e.value) and "port=" in str(e.value)


def test_find_port_picks_interface_b():
    ports = [fake_port("/dev/ttyUSB0", 0x0403, 0x6010, "1-1:1.0"), fake_port("/dev/ttyUSB1", 0x0403, 0x6010, "1-1:1.1")]
    assert find_port(get_board("tangnano9k"), ports) == "/dev/ttyUSB1"
    assert find_port(get_board("tangnano9k"), ports[::-1]) == "/dev/ttyUSB1"


def test_find_port_ignores_other_devices():
    ports = [fake_port("COM1", 0x1234, 0x5678, "1-3:1.0"), fake_port("COM7", 0x0403, 0x6010, "1-1:1.1")]
    assert find_port(get_board("tangnano9k"), ports) == "COM7"


def test_find_port_none_found():
    with pytest.raises(PortNotFound, match="port="):
        find_port(get_board("tangnano9k"), [fake_port("COM1", 0x1234, 0x5678, None)])


def test_find_port_without_location():
    assert find_port(get_board("tangnano9k"), [fake_port("COM7", 0x0403, 0x6010, None)]) == "COM7"


def test_find_port_external_adapter_board_requires_port():
    from dataclasses import replace

    ext = replace(get_board("tangnano9k"), board_id="ext", host_link={"kind": "uart-external", "baudrate": 115200})
    with pytest.raises(PortNotFound, match="port="):
        find_port(ext, [fake_port("COM7", 0x0403, 0x6010, "1-1:1.1")])


def test_find_port_windows_ftdi_driver_picks_interface_b_by_serial():
    # Windows with FTDI's driver on both interfaces (no Zadig): no location, the serial ends in A / B per interface
    # (Tang Mega 138K Pro's BL616, 2026-11-21: COM6 2025071717A, COM7 2025071717B).
    ports = [
        fake_port("COM6", 0x0403, 0x6010, None, "2025071717A"),
        fake_port("COM7", 0x0403, 0x6010, None, "2025071717B"),
    ]
    assert find_port(get_board("tangmega138kpro"), ports) == "COM7"
    assert find_port(get_board("tangmega138kpro"), ports[::-1]) == "COM7"


def test_find_port_windows_two_boards_by_serial_is_ambiguous():
    ports = [fake_port("COM7", 0x0403, 0x6010, None, "2025071717B"), fake_port("COM9", 0x0403, 0x6010, None, "1234B")]
    with pytest.raises(PortNotFound, match=r"COM7.*COM9"):
        find_port(get_board("tangmega138kpro"), ports)


def test_find_port_windows_two_boards_with_the_same_serial_is_ambiguous():
    # The serial may name the debugger's firmware, not the unit: two boards can share it. Two B ports of one
    # "chip" are two boards, never one.
    ports = [
        fake_port("COM7", 0x0403, 0x6010, None, "2025071717B"),
        fake_port("COM9", 0x0403, 0x6010, None, "2025071717B"),
    ]
    with pytest.raises(PortNotFound, match=r"COM7.*COM9"):
        find_port(get_board("tangmega138kpro"), ports)
    four = [
        fake_port(f"COM{n}", 0x0403, 0x6010, None, "2025071717" + ab)
        for n, ab in ((6, "A"), (7, "B"), (8, "A"), (9, "B"))
    ]
    with pytest.raises(PortNotFound):
        find_port(get_board("tangmega138kpro"), four)
