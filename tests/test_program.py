import dataclasses
import shutil
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from nanopynq import program
from nanopynq.boards import get_board
from nanopynq.errors import ProgramError, ProgrammerNotFound
from nanopynq.program import find_openfpgaloader, program_sram, program_sram_openfpgaloader
from tests.fakes import FakeGowinDevice


def test_command_line(tmp_path):
    calls = []
    program_sram_openfpgaloader(
        get_board("tangnano9k"),
        tmp_path / "a.fs",
        exe=Path("ofl"),
        run=lambda c, **k: calls.append(c) or CompletedProcess(c, 0, "", ""),
    )
    assert calls == [["ofl", "-b", "tangnano9k", str(tmp_path / "a.fs")]]


def test_not_found_message_mentions_install(monkeypatch):
    monkeypatch.delenv("NANOPYNQ_OPENFPGALOADER", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ProgrammerNotFound, match="openFPGALoader"):
        find_openfpgaloader()


def test_windows_usb_error_suggests_zadig_interface0(monkeypatch, tmp_path):  # Review Focus 5
    monkeypatch.setattr(sys, "platform", "win32")
    err = "unable to open ftdi device: -3 (device not found)"
    with pytest.raises(ProgramError) as e:
        program_sram_openfpgaloader(
            get_board("tangnano9k"),
            tmp_path / "a.fs",
            exe=Path("ofl"),
            run=lambda c, **k: CompletedProcess(c, 1, "", err),
        )
    assert "Zadig" in str(e.value) and "Interface 0" in str(e.value) and err in e.value.stderr


def test_linux_usb_error_suggests_udev(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ProgramError, match=r"99-nanopynq.rules"):
        program_sram_openfpgaloader(
            get_board("tangnano9k"),
            tmp_path / "a.fs",
            exe=Path("ofl"),
            run=lambda c, **k: CompletedProcess(c, 1, "", "boom"),
        )


def test_env_var_wins_over_path(monkeypatch, tmp_path):
    ofl = tmp_path / "ofl"
    ofl.write_bytes(b"")
    monkeypatch.setenv("NANOPYNQ_OPENFPGALOADER", str(ofl))
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/openFPGALoader")
    assert find_openfpgaloader() == ofl


def test_env_var_to_missing_file_raises_programmer_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("NANOPYNQ_OPENFPGALOADER", str(tmp_path / "nope"))
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/openFPGALoader")
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ProgrammerNotFound, match=r"nope.*sudo apt install openfpgaloader"):
        find_openfpgaloader()


def test_not_found_message_per_os(monkeypatch):
    monkeypatch.delenv("NANOPYNQ_OPENFPGALOADER", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _: None)
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(ProgrammerNotFound, match="sudo apt install openfpgaloader"):
        find_openfpgaloader()
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ProgrammerNotFound, match="pacman -S mingw-w64-ucrt-x86_64-openFPGALoader"):
        find_openfpgaloader()


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_program_error_mentions_close_of_previous_overlay(monkeypatch, tmp_path, platform):  # Review Focus 2
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(ProgramError, match=r"ol\.close\(\)"):
        program_sram_openfpgaloader(
            get_board("tangnano4k"),
            tmp_path / "a.fs",
            exe=Path("ofl"),
            run=lambda c, **k: CompletedProcess(c, 1, "", "unable to open ftdi device"),
        )


REV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))


def test_nanopynq_tool_loads_over_jtag(tmp_path):
    fs = tmp_path / "a.fs"
    fs.write_text("10100101\n", encoding="ascii")
    dev = FakeGowinDevice(idcode=0x0000081B)
    program_sram(get_board("tangnano20k"), fs, open_jtag=lambda vid, pid: dev)
    assert dev.data == bytes([0xA5]).translate(REV) and dev.closed == 1


def test_program_sram_sends_msb_first_only_where_the_board_says(tmp_path):
    fs = tmp_path / "a.fs"
    fs.write_text("10100101\n", encoding="ascii")
    b = get_board("tangmega138kpro")
    b = dataclasses.replace(b, programmer={**b.programmer, "tool": "nanopynq"})
    dev = FakeGowinDevice(idcode=0x0001081B)
    program_sram(b, fs, open_jtag=lambda vid, pid: dev)
    assert dev.msb_first is True and dev.data == bytes([0xA5]).translate(REV)
    dev = FakeGowinDevice(idcode=0x0000081B)
    program_sram(get_board("tangnano20k"), fs, open_jtag=lambda vid, pid: dev)
    assert dev.msb_first is False


def test_program_sram_closes_jtag_on_error(tmp_path):  # Review Focus 5
    fs = tmp_path / "a.fs"
    fs.write_text("10100101\n", encoding="ascii")
    dev = FakeGowinDevice(idcode=0x0100481B)  # a 9K on the 20K's settings
    with pytest.raises(ProgramError):
        program_sram(get_board("tangnano20k"), fs, open_jtag=lambda vid, pid: dev)
    assert dev.closed == 1


def test_bad_fs_fails_before_opening_usb(tmp_path):
    fs = tmp_path / "a.fs"
    fs.write_text("1012\n", encoding="ascii")
    with pytest.raises(ProgramError):
        program_sram(get_board("tangnano20k"), fs, open_jtag=pytest.fail)


def test_openfpgaloader_tool_still_dispatches(tmp_path, monkeypatch):
    board = dataclasses.replace(get_board("tangnano9k"), programmer={"tool": "openfpgaloader", "board": "tangnano9k"})
    calls = []
    monkeypatch.setattr(program, "program_sram_openfpgaloader", lambda b, f: calls.append(f))
    program_sram(board, tmp_path / "a.fs")
    assert calls == [tmp_path / "a.fs"]


def test_unknown_tool_is_named_before_usb_is_opened(tmp_path):
    board = dataclasses.replace(get_board("tangnano9k"), programmer={"tool": "nanopyqn", "board": "tangnano9k"})
    with pytest.raises(ValueError, match=r"nanopyqn.*nanopynq.*openfpgaloader"):
        program_sram(board, tmp_path / "a.fs", open_jtag=pytest.fail)


def test_program_sram_passes_a_usb_timeout_through(tmp_path):  # Review Focus 5
    from nanopynq.errors import TransportTimeout

    class Unplugged(FakeGowinDevice):
        def shift_bytes(self, data):
            raise TransportTimeout(1, 0)

    fs = tmp_path / "a.fs"
    fs.write_text("10100101\n", encoding="ascii")
    dev = Unplugged(idcode=0x0000081B)
    with pytest.raises(TransportTimeout):
        program_sram(get_board("tangnano20k"), fs, open_jtag=lambda vid, pid: dev)
    assert dev.closed == 1
