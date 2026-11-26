from dataclasses import replace

import pytest

from nanopynq.boards import get_board, list_boards, npq_family, npq_link


def test_tangnano9k_values():
    b = get_board("tangnano9k")
    assert (b.device, b.family, b.pack_device) == ("GW1NR-LV9QN88PC6/I5", "GW1N-9C", "GW1N-9C")
    assert b.synth_args == [] and b.pack_args == ["-c"]
    assert b.programmer == {"tool": "nanopynq", "idcode": 0x0100481B, "family": "gw1n", "board": "tangnano9k"}
    assert b.host_link["exclusive_with_jtag"] is True
    assert (b.host_link["baudrate"], b.host_link["usb_vid"], b.host_link["usb_pid"]) == (115200, 0x0403, 0x6010)
    assert b.clock_hz == 27_000_000


def test_tangnano4k_values():
    b = get_board("tangnano4k")
    assert (b.device, b.family, b.pack_device) == ("GW1NSR-LV4CQN48PC7/I6", None, "GW1NS-4")
    assert b.synth_args == ["-nolutram", "-nowidelut"]
    assert b.pack_args == ["-c", "--mspi_as_gpio"]
    assert b.host_link == {"kind": "jtag", "usb_vid": 0x0403, "usb_pid": 0x6010}
    assert b.programmer == {"tool": "nanopynq", "idcode": 0x0100981B, "family": "gw1n", "board": "tangnano4k"}


def test_tangnano20k_values():
    b = get_board("tangnano20k")
    assert (b.device, b.family, b.pack_device) == ("GW2AR-LV18QN88C8/I7", "GW2A-18C", "GW2A-18C")
    assert b.synth_args == ["-family", "gw2a"] and b.pack_args == ["-c"]
    assert b.programmer == {"tool": "nanopynq", "idcode": 0x0000081B, "family": "gw2a", "board": "tangnano20k"}
    assert b.host_link == {"kind": "jtag", "usb_vid": 0x0403, "usb_pid": 0x6010}
    assert b.uart_link == {"baudrate": 115200}  # the BL616's UART to pins 69 / 70, for designs from nanopynq build


def test_only_the_20k_has_a_second_link():
    assert {b: get_board(b).uart_link for b in list_boards()} == {
        "tangmega138kpro": None,
        "tangnano20k": {"baudrate": 115200},
        "tangnano4k": None,
        "tangnano9k": None,
    }


def test_tangmega138kpro_values():
    b = get_board("tangmega138kpro")
    assert (b.device, b.family, b.pack_device) == ("GW5AST-LV138FPG676AC1/I0", None, "GW5AST-138C")
    assert b.synth_args == ["-family", "gw5a"] and b.pack_args == ["-c", "--cpu_as_gpio"]
    assert b.programmer == {
        "tool": "nanopynq",
        "idcode": 0x0001081B,
        "family": "gw5a",
        "board": "tangmega138k",
        "msb_first": True,
    }
    assert b.host_link == {"kind": "uart", "baudrate": 115200, "usb_vid": 0x0403, "usb_pid": 0x6010}
    assert b.io_voltage == {"clk": 3.3, "uart": 3.3, "led": 3.3, "btn": 3.3}
    assert b.clock_hz == 50_000_000


def test_list_and_unknown():
    assert list_boards() == ["tangmega138kpro", "tangnano20k", "tangnano4k", "tangnano9k"]
    with pytest.raises(KeyError):
        get_board("nope")


def test_what_a_npq_takes_from_the_board():
    nine, four, twenty = (get_board(b) for b in ("tangnano9k", "tangnano4k", "tangnano20k"))
    usb = {"usb_vid": "0x0403", "usb_pid": "0x6010"}
    assert (npq_family(nine), npq_family(twenty)) == ("gw1n", "gw2a")
    assert npq_link(nine, "uart") == {"kind": "uart", "baudrate": 115200, **usb}
    assert npq_link(four, "jtag") == {"kind": "jtag", **usb}
    assert npq_link(twenty, "uart") == {"kind": "uart", "baudrate": 115200, **usb}  # its uart_link
    with pytest.raises(ValueError, match=r"tangnano4k.*no UART link"):
        npq_link(four, "uart")
    with pytest.raises(ValueError, match="no usb_vid / usb_pid"):
        npq_link(replace(nine, host_link={"kind": "uart", "baudrate": 115200}), "uart")
