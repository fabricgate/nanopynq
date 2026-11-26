"""Overlay with a .npq: the design check of spec 5.7 step 6 and 5.8, with fake devices only."""

import warnings

import pytest

from nanopynq import Overlay
from nanopynq.boards import get_board, npq_family
from nanopynq.errors import BoardNotResponding, DesignMismatch, ManifestError, NpqError, TransportTimeout
from nanopynq.npq import write_npq
from tests.fakes import FakeUARTBoneDevice
from tests.test_npq import IPS as IPS_1_0
from tests.test_npq import JTAG, NINE_K, UART, as_format_1

ID, V1_0, V1_1 = 0x4E505131, 0x0001_0000, 0x0001_0001
DID = 0xABF78D8C  # NINE_K's design_id
SYS_WORDS = {0, 1, 3}  # sys.id, sys.version, sys.design_id as word addresses


def _npq(folder, ips=NINE_K["ips"], link=None, board="tangnano9k", family=None):
    fs = folder / "base.fs"
    fs.write_bytes(b"dummy bitstream")
    return write_npq(fs, board, family or npq_family(get_board(board)), link or UART, ips)


def _device(version=V1_1, did=DID):
    dev = FakeUARTBoneDevice({0: ID, 1: version, 3: did})
    dev.closed = 0
    dev.close = lambda: setattr(dev, "closed", dev.closed + 1)
    return dev


def _open(design, dev, download=False, programmer=None):
    return Overlay(
        design, download=download, port="X", open_port=lambda p, b: dev, programmer=programmer or (lambda b, f: None)
    )


def test_matching_design_id_opens_and_reads_only_sys_first(tmp_path):
    _npq(tmp_path)
    dev = _device()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ol = _open(tmp_path, dev)
    assert dev.accesses == [("r", 0), ("r", 1), ("r", 3)]
    ol.leds[0].on()
    assert dev.regs[0x1000 // 4] == 1


@pytest.mark.parametrize("did, seen", [(0x12345678, "0x12345678"), (0, "0x00000000 (built without a design ID)")])
def test_other_design_stops_before_any_other_register(tmp_path, did, seen):
    _npq(tmp_path)
    dev = _device(did=did)
    with pytest.raises(DesignMismatch) as e:
        _open(tmp_path, dev, programmer=pytest.fail)
    msg = str(e.value)
    assert seen in msg and "0xabf78d8c" in msg and "download=True" in msg
    assert {a for _, a in dev.accesses} <= SYS_WORDS and all(op == "r" for op, _ in dev.accesses)
    assert dev.closed == 1


def test_mismatch_after_programming_says_rebuild(tmp_path):
    _npq(tmp_path)
    programmed, dev = [], _device(did=0x12345678)
    with pytest.raises(DesignMismatch, match="rebuild"):
        _open(tmp_path, dev, download=True, programmer=lambda b, f: programmed.append(f))
    assert programmed and dev.closed == 1
    assert {a for _, a in dev.accesses} <= SYS_WORDS and all(op == "r" for op, _ in dev.accesses)


@pytest.mark.parametrize("download", [False, True])
def test_file_1_1_board_1_0_is_an_error(tmp_path, download):
    _npq(tmp_path)
    dev = _device(version=V1_0, did=0xDEADBEEF)
    with pytest.raises(DesignMismatch, match=r"sysinfo 1.0") as e:
        _open(tmp_path, dev, download=download)
    assert "nanopynq:sysinfo:1.1" in str(e.value)
    assert dev.accesses == [("r", 0), ("r", 1)] and dev.closed == 1


def test_manifest_design_download_false_warns_and_reads_only_id(tmp_design):
    dev = _device()
    with pytest.warns(UserWarning, match="not checked"):
        _open(tmp_design, dev)
    assert dev.accesses == [("r", 0)]


def test_manifest_design_download_true_is_as_before(tmp_design):
    dev = _device()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _open(tmp_design, dev, download=True)
    assert dev.accesses == [("r", 0)]


def test_npq_1_0_on_a_1_0_board(tmp_path):
    _npq(tmp_path, IPS_1_0)
    with pytest.warns(UserWarning, match="not checked"):
        _open(tmp_path, _device(version=V1_0))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _open(tmp_path, _device(version=V1_0), download=True)


def test_npq_1_0_on_a_1_1_board_still_compares(tmp_path):  # spec 5.7 step 6 looks at the board's version
    _npq(tmp_path, IPS_1_0)
    with pytest.raises(DesignMismatch, match="another design"):
        _open(tmp_path, _device(did=DID))


def test_link_comes_from_the_file(tmp_path):
    _npq(tmp_path, link={**UART, "baudrate": 57600})
    seen = []
    Overlay(
        tmp_path,
        download=False,
        port="X",
        programmer=pytest.fail,
        open_port=lambda p, baud: seen.append(baud) or _device(),
    )
    assert seen == [57600]


def test_link_kind_other_than_the_boards_is_refused_before_programming(tmp_path):
    _npq(tmp_path, link=JTAG)
    with pytest.raises(ManifestError, match=r"link.kind"):
        Overlay(tmp_path, port="X", programmer=pytest.fail, open_port=pytest.fail, open_jtag=pytest.fail)


@pytest.mark.parametrize(
    "change, where",
    [
        ({"family": "gw2a"}, r"bitstream.family is gw2a.*has gw1n"),
        ({"link": {**UART, "usb_vid": "0x1234"}}, r"link.usb_vid is 0x1234.*has 0x0403"),
        ({"link": {**UART, "usb_pid": "0x6011"}}, r"link.usb_pid is 0x6011.*has 0x6010"),
    ],
)
def test_family_or_usb_ids_other_than_the_boards_are_refused_before_programming(tmp_path, change, where):
    """Spec chapter 10, row 12: boards.yaml stays in use here, so a file that disagrees with it is not programmed,
    and not opened without programming either."""
    _npq(tmp_path, **change)
    for download in (True, False):
        with pytest.raises(ManifestError, match=where):
            Overlay(
                tmp_path,
                download=download,
                port="X",
                programmer=pytest.fail,
                open_port=pytest.fail,
                open_jtag=pytest.fail,
            )


def test_a_jtag_design_reaches_the_bridge_with_the_boards_integer_usb_ids(tmp_path, monkeypatch):
    """The file writes the IDs as hex strings; what opens the USB device gets boards.yaml's integers."""
    monkeypatch.setattr("nanopynq.overlay._sleep", lambda s: None)
    _npq(tmp_path, link=JTAG, board="tangnano4k")
    seen = []

    def open_jtag(link):  # no bridge behind it: only what it was handed matters
        seen.append(link)
        raise TransportTimeout(8, 0)

    with pytest.raises(BoardNotResponding):
        Overlay(tmp_path, programmer=lambda b, f: None, open_jtag=open_jtag)
    assert seen == [{"kind": "jtag", "usb_vid": 0x0403, "usb_pid": 0x6010}]


def test_a_format_1_file_still_opens_with_the_boards_values(tmp_path):
    as_format_1(_npq(tmp_path))
    seen = []
    ol = Overlay(
        tmp_path,
        port="X",
        programmer=lambda board, fs: seen.append(board.programmer["family"]),
        open_port=lambda p, baud: seen.append(baud) or _device(),
    )
    assert seen == ["gw1n", 115200] and ol.manifest.family is None


def test_a_20k_design_on_its_uart_is_programmed_and_opened_over_serial(tmp_path):
    """The 20K's default link is JTAG; a design built for its UART (boards.yaml uart_link) opens the serial port."""
    _npq(tmp_path, board="tangnano20k")
    seen = []
    ol = Overlay(
        tmp_path,
        port="X",
        programmer=lambda board, fs: seen.append(board.board_id),
        open_port=lambda p, baud: seen.append(baud) or _device(),
        open_jtag=pytest.fail,
    )
    assert seen == ["tangnano20k", 115200] and ol.board.board_id == "tangnano20k"


def test_a_uart_design_for_a_board_without_one_is_refused(tmp_path):
    _npq(tmp_path, board="tangnano4k")
    with pytest.raises(ManifestError, match=r"link.kind is 'uart'"):
        Overlay(tmp_path, port="X", programmer=pytest.fail, open_port=pytest.fail, open_jtag=pytest.fail)


def test_a_silent_20k_on_its_uart_gets_the_serial_hint_not_the_jtag_one(tmp_path, monkeypatch):
    monkeypatch.setattr("nanopynq.overlay._sleep", lambda s: None)
    _npq(tmp_path, board="tangnano20k")
    with pytest.raises(BoardNotResponding, match=r"抜き差し|replug") as e:
        Overlay(
            tmp_path, download=False, port="X", open_port=lambda p, b: FakeUARTBoneDevice({0: 0}), open_jtag=pytest.fail
        )
    assert "check over JTAG" not in str(e.value)  # the serial message, not the JTAG bridge one
    assert "at the same time" not in str(e.value)  # that is the 9K's BL702; the 20K's BL616 takes both


def test_npq_file_can_be_passed_directly(tmp_path):
    p = _npq(tmp_path)
    assert _open(p, _device()).manifest.design_id == DID


def test_broken_npq_does_not_fall_back_to_manifest_yaml(tmp_design):
    (tmp_design / "base.npq").write_text("{}")
    with pytest.raises(ManifestError, match="V2"):
        _open(tmp_design, _device(), programmer=pytest.fail)


def test_overlay_opens_an_npq_without_its_fs_when_not_downloading(tmp_path):
    _npq(tmp_path)
    (tmp_path / "base.fs").unlink()
    ol = _open(tmp_path / "base.npq", _device(), download=False)
    assert ol.manifest.board == "tangnano9k"


def test_downloading_still_needs_the_fs(tmp_path):
    _npq(tmp_path)
    (tmp_path / "base.fs").unlink()
    with pytest.raises(NpqError, match="V12"):
        _open(tmp_path / "base.npq", _device(), download=True)
