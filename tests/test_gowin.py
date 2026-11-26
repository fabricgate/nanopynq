import pytest

from nanopynq.errors import ProgramError
from nanopynq.gowin import load_sram, read_fs
from tests.fakes import FakeGowinDevice

REV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
# POR (bit 16), READY (bit 15), VLD (bit 12): set on a healthy GW1N (9K 0x0003f020, 4K 0x0001f020), never on the GW2A
HEALTHY_GW1N = 1 << 16 | 1 << 15 | 1 << 12


def test_read_fs_skips_comments_and_packs_msb_first(tmp_path):
    p = tmp_path / "a.fs"
    p.write_text("//Device: x\n\n1010010111000011\n", encoding="ascii")
    assert read_fs(p) == bytes([0xA5, 0xC3])


@pytest.mark.parametrize("bad", ["1010", "1010010x"])  # wrong length only; wrong character only
def test_read_fs_rejects_bad_line(tmp_path, bad):  # Review Focus 4
    p = tmp_path / "a.fs"
    p.write_text(f"10100101\n{bad}\n", encoding="ascii")
    with pytest.raises(ProgramError, match=r"a\.fs.*line 2"):
        read_fs(p)


def test_a_family_without_a_sequence_is_refused_before_the_board_is_touched():
    dev = FakeGowinDevice()
    with pytest.raises(ProgramError, match=r"no loading sequence for the family 'gw9z'"):
        load_sram(dev, b"\x00", 0x0000081B, "gw9z")
    assert dev.log == [] and dev.state == "TLR"  # nothing was sent


def test_max_polls_below_one_is_a_value_error():
    with pytest.raises(ValueError, match="max_polls"):
        load_sram(FakeGowinDevice(), b"\x00", 0x0000081B, "gw2a", max_polls=0)


def test_crc_error_offers_openfpgaloader_if_a_power_cycle_does_not_help():
    with pytest.raises(ProgramError, match="program_sram_openfpgaloader"):
        load_sram(FakeGowinDevice(status=1), b"\x00", 0x0000081B, "gw2a")


def test_no_done_final_also_names_a_lost_usb_transfer():
    with pytest.raises(ProgramError, match="USB"):
        load_sram(FakeGowinDevice(done=False), b"\x00", 0x0000081B, "gw2a")


def test_load_sends_the_bits_in_order_inside_shift_dr():
    dev = FakeGowinDevice()
    load_sram(dev, bytes([0xA5, 0x01]), 0x0000081B, "gw2a")
    assert dev.data == bytes([0xA5, 0x01]).translate(REV)
    assert dev.log == [
        "IDCODE",
        "STATUS",
        "CONFIG_ENABLE",
        "STATUS",
        "ERASE_SRAM",
        "NOOP",
        "STATUS",
        "XFER_DONE",
        "NOOP",
        "CONFIG_DISABLE",
        "NOOP",
        "STATUS",
        "CONFIG_ENABLE",
        "INIT_ADDR",
        "XFER_WRITE",
        "CONFIG_DISABLE",
        "NOOP",
        "STATUS",
    ]


def test_idcode_masks_version_nibble():
    load_sram(FakeGowinDevice(idcode=0x1100481B, status=HEALTHY_GW1N), b"\x00", 0x0100481B, "gw1n")


def test_idcode_mismatch_stops_before_erase():  # Review Focus 2
    dev = FakeGowinDevice(idcode=0x1100481B)
    with pytest.raises(ProgramError, match=r"0x0100481b.*0x0000081b"):
        load_sram(dev, b"\x00", 0x0000081B, "gw2a")
    assert "ERASE_SRAM" not in dev.log


def test_no_done_final_is_an_error():
    with pytest.raises(ProgramError, match="DONE_FINAL"):
        load_sram(FakeGowinDevice(done=False), b"\x00", 0x0000081B, "gw2a")


def test_poll_gives_up_with_status():  # Review Focus 3
    with pytest.raises(ProgramError, match=r"MEMORY_ERASE.*0x"):
        load_sram(FakeGowinDevice(stuck=1 << 5), b"\x00", 0x0000081B, "gw2a", max_polls=5)


def test_crc_error_stops_with_power_cycle_hint():  # spec 5.7 default; Task 5 may replace
    with pytest.raises(ProgramError, match="power"):
        load_sram(FakeGowinDevice(status=1), b"\x00", 0x0000081B, "gw2a")


def test_read_fs_without_bitstream_lines_is_an_error(tmp_path):
    p = tmp_path / "a.fs"
    p.write_text("//only a comment\n", encoding="ascii")
    with pytest.raises(ProgramError, match="no bitstream"):
        read_fs(p)


@pytest.mark.parametrize(
    "status",
    [
        0x00021020,  # the 9K after a failed load (POR, READY clear)
        0x00023020,  # the 4K before its flash broke
        HEALTHY_GW1N & ~(1 << 12),
    ],
)  # VLD clear
def test_gw1n_refuses_unless_por_ready_and_vld(status):  # issue 67
    dev = FakeGowinDevice(idcode=0x1100481B, status=status)
    with pytest.raises(ProgramError, match="power-cycle"):
        load_sram(dev, b"\x00", 0x0100481B, "gw1n")
    assert "CONFIG_ENABLE" not in dev.log and "ERASE_SRAM" not in dev.log


def test_gw1n_in_that_state_with_another_idcode_says_power_cycle_not_wrong_board():
    # The 9K in that state read as 0x1100581b (the IDCODE of the GW1NR-9 without C), not its own 0x1100481b.
    dev = FakeGowinDevice(idcode=0x1100581B, status=0x00021020)
    with pytest.raises(ProgramError, match=r"0x0100581b.*power-cycle") as e:
        load_sram(dev, b"\x00", 0x0100481B, "gw1n")
    assert "board option" not in str(e.value) and "ERASE_SRAM" not in dev.log


def test_gw2a_is_not_checked_for_por():
    # A healthy 20K (GW2A) reads 0x00006020: no POR, READY or VLD bit.
    dev = FakeGowinDevice(status=0x00006020)
    load_sram(dev, b"\x00", 0x0000081B, "gw2a")
    assert dev.data


GW5A = 0x0001081B
ERASE_PASS = [
    "CONFIG_ENABLE",
    "STATUS",
    "ERASE_SRAM",
    "NOOP",
    "IDLE 60000",
    "STATUS",
    "XFER_DONE",
    "NOOP",
    "CONFIG_DISABLE",
    "NOOP",
    "STATUS",
    "STATUS",
]


def test_gw5a_reloads_idles_and_erases_twice():
    dev = FakeGowinDevice(idcode=GW5A)
    load_sram(dev, bytes([0xA5, 0x01]), GW5A, "gw5a")
    assert dev.data == bytes([0xA5, 0x01]).translate(REV)
    assert dev.log == [
        "IDCODE",
        "STATUS",
        "RELOAD",
        "NOOP",
        "IDLE 1000000",
        "STATUS",
        *ERASE_PASS,
        *ERASE_PASS,
        "CONFIG_ENABLE",
        "INIT_ADDR",
        "XFER_WRITE",
        "CONFIG_DISABLE",
        "NOOP",
        "STATUS",
    ]


def test_gw5a_running_design_is_erased_before_loading():  # Review Focus 5
    dev = FakeGowinDevice(idcode=GW5A, status=1 << 13)
    load_sram(dev, b"\x00", GW5A, "gw5a")
    assert dev.log.count("ERASE_SRAM") == 2


@pytest.mark.parametrize("bit", [1, 3, 4])  # Review Focus 2
def test_gw5a_error_state_is_refused_before_erase(bit):
    dev = FakeGowinDevice(idcode=GW5A, status=1 << bit)
    with pytest.raises(ProgramError, match="program_sram_openfpgaloader"):
        load_sram(dev, b"\x00", GW5A, "gw5a")
    assert "ERASE_SRAM" not in dev.log


def test_gw5a_gives_up_when_done_final_stays_set():
    dev = FakeGowinDevice(idcode=GW5A, status=1 << 13, latched=1 << 13)
    with pytest.raises(ProgramError, match="DONE_FINAL"):
        load_sram(dev, b"\x00", GW5A, "gw5a")
    assert dev.log.count("ERASE_SRAM") == 4 and "XFER_WRITE" not in dev.log


def test_gw5a_wrong_idcode_stops_before_reload():  # Review Focus 4
    dev = FakeGowinDevice(idcode=0x0000081B)
    with pytest.raises(ProgramError, match=r"0x0000081b.*0x0001081b"):
        load_sram(dev, b"\x00", GW5A, "gw5a")
    assert "RELOAD" not in dev.log and "ERASE_SRAM" not in dev.log


def test_gw5a_errors_say_switch_the_power_off_not_unplug():
    # The 138K Pro runs from its 12 V jack: unplugging USB does not power-cycle it.
    for dev in (
        FakeGowinDevice(idcode=GW5A, status=1 << 3),
        FakeGowinDevice(idcode=GW5A, status=1 << 13, latched=1 << 13),
    ):
        with pytest.raises(ProgramError) as e:
            load_sram(dev, bytes(1), GW5A, "gw5a")
        assert "power" in str(e.value) and "Unplug" not in str(e.value)
