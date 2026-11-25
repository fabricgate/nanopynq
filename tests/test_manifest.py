import pytest

from nanopynq.errors import ManifestError
from nanopynq.manifest import load_manifest
from nanopynq.resolve import resolve_design


def test_load_normalises_ips(tmp_design):
    m = load_manifest(tmp_design)
    assert m.board == "tangnano9k"
    assert m.bitstream == (tmp_design / "base.fs").resolve()
    assert m.ips["leds"] == {
        "name": "leds",
        "type": "nanopynq:gpio_out:1.0",
        "phys_addr": 0x1000,
        "addr_range": 0x1000,
        "parameters": {"width": 6},
        "registers": {"data": {"offset": 0, "width": 6, "access": "rw"}},
        "streams": {},
    }
    assert m.ips["sys"]["parameters"] == {}
    assert m.ips["sys"]["registers"]["version"]["offset"] == 4


def test_explicit_addr_range_kept(tmp_design):
    p = tmp_design / "manifest.yaml"
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            'leds:    {base: "0x1000",', 'leds:    {base: "0x1000", addr_range: "0x40",'
        ),
        encoding="utf-8",
    )
    assert load_manifest(tmp_design).ips["leds"]["addr_range"] == 0x40


def _with_streams(design, streams):
    p = design / "manifest.yaml"
    p.write_text(
        p.read_text(encoding="utf-8").replace(
            'leds:    {base: "0x1000",', 'leds:    {base: "0x1000", streams: ' + streams + ","
        ),
        encoding="utf-8",
    )


def test_manifest_streams_parsed(tmp_design):
    _with_streams(tmp_design, "{video: {dir: read, mtu: 400, register: window, framing: slot-header32}}")
    assert load_manifest(tmp_design).ips["leds"]["streams"] == {
        "video": {"dir": "read", "mtu": 400, "register": "window", "framing": "slot-header32"}
    }


@pytest.mark.parametrize(
    "streams",
    [
        "[video]",
        "{video: {dir: sideways, mtu: 400}}",
        "{video: {dir: read}}",
        "{video: {dir: read, mtu: 0}}",
        "{video: {dir: read, mtu: true}}",
        "{video: 3}",
    ],
)
def test_manifest_streams_malformed(tmp_design, streams):
    _with_streams(tmp_design, streams)
    with pytest.raises(ManifestError, match="stream"):
        load_manifest(tmp_design)


def test_wrong_runtime_rejected(tmp_design):
    p = tmp_design / "manifest.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("runtime: nanopynq", "runtime: pynq"), encoding="utf-8")
    with pytest.raises(ManifestError, match="runtime"):
        load_manifest(tmp_design)


def test_missing_manifest(tmp_path):
    with pytest.raises(ManifestError, match="manifest"):
        load_manifest(tmp_path)


def test_malformed_manifest(tmp_design):
    (tmp_design / "manifest.yaml").write_text("runtime: nanopynq\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="malformed"):
        load_manifest(tmp_design)


def test_sha256_mismatch(tmp_design):
    (tmp_design / "base.fs").write_bytes(b"tampered")
    with pytest.raises(ManifestError, match="sha256"):
        load_manifest(tmp_design)


def test_missing_bitstream(tmp_design):
    (tmp_design / "base.fs").unlink()
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_design)


def test_bitstream_path_traversal_rejected(tmp_design):
    p = tmp_design / "manifest.yaml"
    p.write_text(p.read_text(encoding="utf-8").replace("file: base.fs", "file: ../base.fs"), encoding="utf-8")
    with pytest.raises(ManifestError, match="escapes"):
        load_manifest(tmp_design)


def test_resolve_design(tmp_path):
    assert resolve_design(tmp_path, None) == tmp_path
    base = resolve_design("base", "tangnano9k")
    assert base.parts[-3:] == ("data", "designs", "tangnano9k-base") and base.parts[-4] == "nanopynq"
    with pytest.raises(ValueError):  # a version is X.Y.Z, and a fabricgate:// design needs a board
        resolve_design("fabricgate://x/y:1", None)
