"""FabricGate designs (#34): a pulled folder opens as is, and fabricgate:// pulls once per version through the SDK.

The SDK is replaced by fake modules, so nothing here touches the network; only the last test uses the real SDK."""

import inspect
import os
import subprocess
import sys
import types
import typing
import warnings

import pytest

from nanopynq import Overlay
from nanopynq.npq import Npq, write_npq
from nanopynq.resolve import WARNINGS, resolve_design
from tests.test_npq import NINE_K, UART
from tests.test_overlay_npq import _device, _open

REF = "fabricgate://harurun78/tangnano9k-pwm:1.0.0"
PROD = "https://registry.fabricgate.dev/api/v1"
SDK_MODULES = ("fabricgate", "fabricgate.sdk", "fabricgate.client", "fabricgate.client.config")


def _pulled(folder):
    """What `fabricgate pull` leaves: FabricGate's manifest.yaml next to the .fs and the .npq (deps/ may be there)."""
    (folder / "pwm.fs").write_bytes(b"dummy bitstream")
    write_npq(folder / "pwm.fs", "tangnano9k", "gw1n", UART, NINE_K["ips"])
    (folder / "manifest.yaml").write_text(
        "schema: fabricgate-platform/v1\nruntime: nanopynq\nboard: tangnano9k\n"
        "design_ref: harurun78/tangnano9k-pwm:1.0.0\nartifacts:\n"
        f"  bitstream: {{file: pwm.fs, sha256: {'a' * 64}}}\n  metadata: {{file: pwm.npq, sha256: {'b' * 64}}}\n",
        encoding="utf-8",
    )
    (folder / "deps").mkdir()
    return folder


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    """Fake fabricgate.sdk.pull and fabricgate.client.config.load_config; the cache goes to tmp_path."""
    fake = types.SimpleNamespace(calls=[], registry=PROD, fail=None, said={}, extra={})

    def pull(design_ref, *, platform=None, output=None, registry=PROD, **kw):
        fake.calls.append((design_ref, platform, output, registry))
        output.mkdir(parents=True, exist_ok=True)
        (output / "manifest.yaml").write_text("half written", encoding="utf-8")
        if fake.fail:
            raise fake.fail
        _pulled(output)
        for name, text in fake.extra.items():  # files the publisher put in the design
            (output / name).write_text(text, encoding="utf-8")
        return types.SimpleNamespace(
            **{
                "path": str(output),
                "yanked_warning": None,
                "deprecated_warning": None,
                "shell_yanked_warning": None,
                "dependency_yanked_warnings": [],
                **fake.said,
            }
        )

    sdk_mod = types.ModuleType("fabricgate.sdk")
    sdk_mod.pull = pull
    config = types.ModuleType("fabricgate.client.config")
    config.load_config = lambda: types.SimpleNamespace(registry=fake.registry)
    for name in SDK_MODULES:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "fabricgate.sdk", sdk_mod)
    monkeypatch.setitem(sys.modules, "fabricgate.client.config", config)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    return fake


def test_pulled_folder_opens_as_is(tmp_path):
    folder = _pulled(tmp_path)
    ol = _open(folder, _device())
    assert isinstance(ol.manifest, Npq) and ol.manifest.bitstream.name == "pwm.fs"  # manifest.yaml is not read


def test_without_the_sdk_says_how_to_install(monkeypatch, tmp_path):
    for name in [n for n in sys.modules if n.partition(".")[0] == "fabricgate"]:
        monkeypatch.delitem(sys.modules, name)  # even if the real SDK was imported earlier
    monkeypatch.setattr(sys, "path", [])  # so the import finds no fabricgate, as when it is not installed
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    with pytest.raises(ImportError, match=r'pip install "nanopynq\[fabricgate\]"'):
        resolve_design(REF, "tangnano9k")


def test_a_changed_sdk_shows_its_own_error(sdk, monkeypatch):
    monkeypatch.setitem(sys.modules, "fabricgate.client.config", None)  # fabricgate is there, but not this module
    with pytest.raises(ImportError) as e:
        resolve_design(REF, "tangnano9k")
    assert e.value.name == "fabricgate.client.config" and "pip install" not in str(e.value)


def test_import_does_not_need_a_home_folder():
    # the cache folder is found only when a fabricgate:// design is opened (e.g. a container with no home)
    code = (
        "import pathlib\ndef no_home(cls): raise RuntimeError('Could not determine home directory.')\n"
        "pathlib.Path.home = classmethod(no_home)\nimport nanopynq"
    )
    env = {k: v for k, v in os.environ.items() if k != "XDG_CACHE_HOME"}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_pulls_once_per_version_and_registry(sdk, tmp_path):
    cache = tmp_path / "cache/nanopynq/fabricgate"
    first = resolve_design(REF, "tangnano9k")
    assert sdk.calls == [("harurun78/tangnano9k-pwm:1.0.0", "tangnano9k/nanopynq", sdk.calls[0][2], PROD)]
    assert first == cache / "registry.fabricgate.dev_api_v1/harurun78/tangnano9k-pwm/1.0.0/tangnano9k"
    assert sorted(p.name for p in first.iterdir()) == [WARNINGS, "deps", "manifest.yaml", "pwm.fs", "pwm.npq"]
    assert resolve_design(REF, "tangnano9k") == first and len(sdk.calls) == 1  # no second pull
    for n, (registry, folder) in enumerate(
        [
            ("http://localhost:8000/api/v1", "localhost_8000_api_v1"),
            ("http://localhost:9000/api/v1", "localhost_9000_api_v1"),  # another port is another registry
            ("https://user:secret@registry-staging.example/api/v1", "registry-staging.example_api_v1"),
        ],
        start=2,
    ):
        sdk.registry = registry
        got = resolve_design(REF, "tangnano9k")
        assert len(sdk.calls) == n and sdk.calls[-1][3] == registry
        assert got.relative_to(cache).parts[0] == folder  # the credentials are not in the path


def test_failed_pull_leaves_nothing_and_is_retried(sdk, tmp_path):
    sdk.fail = OSError("connection reset")
    with pytest.raises(OSError, match="connection reset"):
        resolve_design(REF, "tangnano9k")
    parent = tmp_path / "cache/nanopynq/fabricgate" / "registry.fabricgate.dev_api_v1/harurun78/tangnano9k-pwm/1.0.0"
    assert list(parent.iterdir()) == []  # neither the half-written folder nor the final one
    sdk.fail = None
    assert (resolve_design(REF, "tangnano9k") / "pwm.npq").is_file() and len(sdk.calls) == 2


def test_yanked_or_deprecated_is_said_on_every_open(sdk):
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # a version the registry says nothing about opens quietly
        resolve_design(REF, "tangnano9k")
    sdk.said = {
        "yanked_warning": "harurun78/tangnano9k-pwm:2.0.0 is yanked: bad timing\x1b[2J\nok",
        "deprecated_warning": "harurun78/tangnano9k-pwm is deprecated",
        "shell_yanked_warning": "Shell harurun78/shell:1.0.0 is yanked",
        "dependency_yanked_warnings": ["Dependency harurun78/uart:1.0.0 is yanked"],
    }
    for _ in range(2):  # the second open comes from the cache, without asking the registry
        with pytest.warns(UserWarning) as said:
            resolve_design(REF.replace("1.0.0", "2.0.0"), "tangnano9k")
        assert [str(w.message) for w in said] == [
            "FabricGate: harurun78/tangnano9k-pwm:2.0.0 is yanked: bad timing?[2J?ok",  # no escapes, one line
            "FabricGate: harurun78/tangnano9k-pwm is deprecated",
            "FabricGate: Shell harurun78/shell:1.0.0 is yanked",
            "FabricGate: Dependency harurun78/uart:1.0.0 is yanked",
        ]
    assert len(sdk.calls) == 2


def test_a_warnings_file_from_the_publisher_is_replaced(sdk):
    sdk.extra = {WARNINGS: "looks fine\x1b]0;pwned\x07\x1b[2J\n"}  # the registry itself said nothing
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert (resolve_design(REF, "tangnano9k") / WARNINGS).read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    "design, board",
    [
        ("fabricgate://harurun78/tangnano9k-pwm", "tangnano9k"),  # no version
        ("fabricgate://harurun78/tangnano9k-pwm:latest", "tangnano9k"),
        ("fabricgate://../tangnano9k-pwm:1.0.0", "tangnano9k"),
        ("fabricgate://harurun78/../../x:1.0.0", "tangnano9k"),
        ("fabricgate://Harurun78/tangnano9k-pwm:1.0.0", "tangnano9k"),
        (REF, None),
        (REF, "../tangnano9k"),
    ],
)
def test_bad_ref_or_board_is_refused_before_any_pull(sdk, design, board):
    with pytest.raises(ValueError):
        resolve_design(design, board)
    assert sdk.calls == []


def test_overlay_opens_a_fabricgate_design(sdk, tmp_path):
    ol = Overlay(
        REF, board="tangnano9k", download=False, port="X", open_port=lambda p, b: _device(), programmer=pytest.fail
    )
    assert ol.design_dir.is_relative_to(tmp_path / "cache") and ol.manifest.board == "tangnano9k"
    with pytest.raises(ValueError, match="board"):
        Overlay(REF)


def test_real_sdk_takes_the_calls_nanopynq_makes(tmp_path):
    sdk = pytest.importorskip("fabricgate.sdk", reason="the fabricgate extra is not installed")
    from fabricgate.client.config import load_config

    inspect.signature(sdk.pull).bind("ns/d:1.0.0", platform="tangnano9k/nanopynq", output="out", registry=PROD)
    said = {"yanked_warning", "deprecated_warning", "shell_yanked_warning", "dependency_yanked_warnings"}
    assert said <= typing.get_type_hints(sdk.pull)["return"].model_fields.keys()
    assert load_config(tmp_path / "none.yaml").registry.startswith("http")  # no file: the default, or FG_REGISTRY
