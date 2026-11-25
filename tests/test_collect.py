"""The ips collected from the RTL and the IP descriptions (issue #44, docs/design_ips_from_rtl.md)."""

import hashlib
import json
import sys
import tomllib
from pathlib import Path

import pytest

import nanopynq.build.collect as col
from nanopynq.boards import get_board
from nanopynq.build.design import load_config
from nanopynq.build.gowin import build_gowin
from nanopynq.npq import design_id
from tests.fakes import own_netlist, pwm_netlist

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "tangnano9k_pwm"
HAND = tomllib.loads((Path(__file__).parent / "data" / "pwm_hand.toml").read_text())["ips"]  # all by hand
sys.path.insert(0, str(ROOT / "tools"))
import build_base as bb  # noqa: E402

# Rule 5 of docs/design_ips_from_rtl.md: a description whose registers change gets a new type version. A new
# version is a new line here; the hash of a type:version that is already here does not change.
PINNED = {
    "nanopynq:sysinfo:1.1": "05a2c8785805c9e2713d323492191f40cb1654e4639c8a535fa75fbb605ef101",
    "nanopynq:gpio_out:1.0": "615629c40dead6897313562c135e5759ac008e2a5dfdad10ec4198dc8249f309",
    "nanopynq:gpio_in:1.0": "18d3486cff8490e44c868936938ffd15d5eb0d7b2fc9f0e69db4adfcfd544ac5",
    "nanopynq:pwm_timer:1.0": "f9784e18b2738e663b8f87efc6a1b386ef1bd3fc003537b7f30a16dffd8b23ca",
}


def ips(netlist, overrides=None, descs=None) -> dict:
    return col.merge(col.collect(netlist, descs or col.load_descriptions()), overrides or {})[0]


def test_each_type_version_keeps_its_description():
    got = {
        d["type"]: hashlib.sha256(
            json.dumps({k: v for k, v in d.items() if k != "_file"}, sort_keys=True).encode()
        ).hexdigest()
        for d in col.load_descriptions()
    }
    assert got == PINNED, "a description changed: if its registers did, raise the version in its type"


def test_the_example_holds_only_what_the_rtl_does_not():
    after = load_config(EXAMPLE).ips
    assert after == {"pwm": {"parameters": {"clock_hz": 27_000_000}}}
    assert design_id(ips(pwm_netlist(), after)) == design_id(HAND) == 0x556FAE35


def test_instance_binds_names_without_attributes():
    ov = {
        "sys": {"instance": "regs.si"},
        "leds": {"instance": "regs.gpio_leds"},
        "buttons": {"instance": "regs.gpio_btns"},
        "pwm": {"instance": "timer", "parameters": {"clock_hz": 27_000_000}},
    }
    assert design_id(ips(pwm_netlist(names=False), ov)) == 0x556FAE35


@pytest.mark.parametrize("names", [False, True])
def test_hand_written_ips_win(names):  # a nanopynq.toml with every ip by hand gives exactly those
    assert ips(pwm_netlist(names), HAND) == HAND


def test_a_whole_entry_replaces_the_collected_ip():  # an entry with a base: nothing is added to it
    hand = HAND | {"leds": {k: v for k, v in HAND["leds"].items() if k != "parameters"}}
    assert ips(pwm_netlist(), hand) == hand


def test_a_whole_entry_replaces_the_collected_ips_in_its_range():  # one hand-written IP over leds and buttons
    regs = {
        "leds": {"offset": "0x0", "width": 5, "access": "rw"},
        "buttons": {"offset": "0x1000", "width": 2, "access": "ro"},
    }
    hand = {n: ip for n, ip in HAND.items() if n not in ("leds", "buttons")} | {
        "gpio": {"base": "0x1000", "addr_range": "0x2000", "type": "acme:gpio2:1.0", "registers": regs}
    }
    assert ips(pwm_netlist(), hand) == hand
    hand["gpio"]["base"] = "0x1800"  # overlaps leds' range without holding its base
    assert ips(pwm_netlist(), hand) == hand


def test_a_broken_hand_written_base_is_left_to_the_rules():  # spec 5.9 names the rule and the place
    assert ips(pwm_netlist(), {"pwm": {"parameters": {"clock_hz": 1}}, "x": {"base": "1000"}})["x"] == {"base": "1000"}


def test_what_the_collected_table_shows():
    got, origin, left_out = col.merge(
        col.collect(pwm_netlist(), col.load_descriptions()),
        {"pwm": {"parameters": {"clock_hz": 1}}, "extra": HAND["pwm"] | {"base": "0x8000"}},
    )
    assert origin == {
        "sys": "regs.si",
        "leds": "regs.gpio_leds",
        "buttons": "regs.gpio_btns",
        "pwm": "timer",
        "extra": None,
    }
    assert list(got) == list(origin) and left_out == []


def test_parameters_add_up_and_other_keys_replace():
    got = ips(
        pwm_netlist(), {"pwm": {"parameters": {"clock_hz": 1}, "doc": "LED 5"}, "leds": {"parameters": {"note": "x"}}}
    )
    assert got["pwm"]["doc"] == "LED 5" and got["leds"]["parameters"] == {"width": 5, "note": "x"}


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({}, r"ips.pwm \(timer\): give parameters \['clock_hz'\]"),
        # forgot (* npq_name *) and instance =: the entry is neither a collected IP nor a whole hand-written one
        ({"pwm": {"parameters": {"clock_hz": 1}}, "x": {"parameters": {}}}, r"ips.x: no IP is named x .*: sys, leds"),
        ({"pwm": {"instance": "tmr"}}, r"ips.pwm.instance: no described instance 'tmr' .*regs.si, timer"),
        (
            {"pwm": {"instance": "timer", "parameters": {"clock_hz": 1}}, "pwm2": {"instance": "timer"}},
            r"ips.pwm2.instance: .*'timer' is already ips.pwm",
        ),
        ({"leds": {"instance": "timer"}}, r"timer and regs.gpio_leds are both named 'leds'.* instance = in"),
        ({"pwm": {"parameters": 3}}, r"ips.pwm.parameters: must be a table"),
    ],
)
def test_merge_errors(overrides, match):
    with pytest.raises(col.CollectError, match=match):
        ips(pwm_netlist(), overrides)


def test_a_name_that_is_not_an_ip_name_is_an_error():
    n = pwm_netlist()
    n["modules"]["top"]["cells"]["timer"]["attributes"]["npq_name"] = "PWM"
    with pytest.raises(col.CollectError, match=r"'PWM' \(timer\) is not an IP name"):
        ips(n, {"PWM": {"parameters": {"clock_hz": 1}}})


def test_two_instances_with_one_name_are_an_error():
    n = pwm_netlist()
    n["modules"]["top"]["cells"]["timer"]["attributes"]["npq_name"] = "leds"
    with pytest.raises(col.CollectError, match=r"timer and regs.gpio_leds are both named 'leds'"):
        ips(n)


def loop_netlist(name=None) -> dict:
    """pwm_netlist() with two pwm_timers at 0x7000 and 0x8000 in a generate loop (begin : ch), as yosys names them;
    name: their (* npq_name *), written once in the loop."""
    n = pwm_netlist()
    cells = n["modules"]["top"]["cells"]
    del cells["timer"]
    for i, base in enumerate((0x7000, 0x8000)):
        mod = f"$paramod\\pwm_timer\\BASE=32'{base:032b}"
        n["modules"][mod] = {
            "attributes": {"hdlname": "pwm_timer"},
            "cells": {},
            "parameter_default_values": {"BASE": f"{base:032b}"},
        }
        cells[f"ch[{i}].timer"] = {"type": mod, "attributes": {"npq_name": name} if name else {}}
    return n


LOOP_HAND = {n: ip for n, ip in HAND.items() if n != "pwm"} | {
    "pwm0": HAND["pwm"],
    "pwm1": HAND["pwm"] | {"base": "0x8000"},
}


@pytest.mark.parametrize("name", [None, "pwm"])
@pytest.mark.parametrize("instance", [False, True])
def test_a_loop_written_by_hand_builds_as_before(name, instance):  # the names repeat; nanopynq.toml settles it
    hand = {
        n: ip | ({"instance": f"ch[{n[-1]}].timer"} if instance and n.startswith("pwm") else {})
        for n, ip in LOOP_HAND.items()
    }
    assert ips(loop_netlist(name), hand) == LOOP_HAND


def test_instance_names_the_ips_of_a_loop():
    clock = {"parameters": {"clock_hz": 1}}
    got = ips(
        loop_netlist("pwm"), {"pwm": {"instance": "ch[0].timer"} | clock, "pwm2": {"instance": "ch[1].timer"} | clock}
    )
    assert (got["pwm"]["base"], got["pwm2"]["base"]) == ("0x7000", "0x8000")
    # one of them by name, the other written whole: the whole one does not take the named one
    got = ips(loop_netlist("pwm"), {"pwm": {"instance": "ch[0].timer"} | clock, "pwm1": LOOP_HAND["pwm1"]})
    assert got["pwm"]["base"] == "0x7000" and got["pwm1"] == LOOP_HAND["pwm1"]


def test_a_loop_left_to_the_rtl_needs_names():
    with pytest.raises(col.CollectError, match=r"ch\[1\].timer and ch\[0\].timer are both named 'pwm'.* instance ="):
        ips(loop_netlist("pwm"), {"pwm": {"parameters": {"clock_hz": 1}}})


GPIO_LEFT_OUT = (
    "does not fit nanopynq's regbus_gpio (gpio_in.toml: unknown name 'IS_INPUT' (known: BASE, WIDTH); "
    "gpio_out.toml: unknown name 'IS_INPUT' (known: BASE, WIDTH))"
)


@pytest.mark.parametrize(
    "module, params, left_out",
    [
        (
            "pwm_timer",
            {"ADDR": 0x7000},
            ["timer does not fit nanopynq's pwm_timer (pwm_timer.toml: unknown name 'BASE' (known: ADDR))"],
        ),
        (
            "regbus_gpio",
            {"BASE": 0, "WIDTH": 5},
            [f"regs.gpio_leds {GPIO_LEFT_OUT}", f"regs.gpio_btns {GPIO_LEFT_OUT}"],
        ),
    ],
)
def test_an_own_module_of_a_described_name_written_by_hand_builds_as_before(module, params, left_out):
    # the instances no entry names are left out, and merge() says which and why (the build shows it)
    assert col.merge(col.collect(own_netlist(module, **params), col.load_descriptions()), HAND) == (
        HAND,
        dict.fromkeys(HAND),
        left_out,
    )
    if module == "pwm_timer":  # the entry that names it is its IP: nothing is left out
        got = col.merge(
            col.collect(own_netlist(module, **params), col.load_descriptions()),
            HAND | {"pwm": HAND["pwm"] | {"instance": "timer"}},
        )
        assert got[0] == HAND and got[2] == []


@pytest.mark.parametrize(
    "module, params, overrides, match",
    [
        (
            "pwm_timer",
            {"ADDR": 0x7000},
            {"pwm": {"instance": "timer", "parameters": {"clock_hz": 1}}},
            r"ips.pwm: timer does not fit nanopynq's pwm_timer "
            r"\(pwm_timer.toml: unknown name 'BASE' \(known: ADDR\)\); "
            r"write the IP whole",
        ),
        (
            "regbus_gpio",
            {"WIDTH": 5},
            {"leds": {"instance": "regs.gpio_leds"}},
            r"ips.leds: regs.gpio_leds does not fit nanopynq's regbus_gpio \(gpio_in.toml: unknown name 'IS_INPUT' "
            r"\(known: WIDTH\); gpio_out.toml: unknown name 'IS_INPUT'",
        ),
    ],
)
def test_an_own_module_named_in_nanopynq_toml_must_fit_the_description(module, params, overrides, match):
    with pytest.raises(col.CollectError, match=match):
        ips(own_netlist(module, **params), overrides)


def test_npq_base_that_disagrees_with_the_decoding_is_an_error():
    n = pwm_netlist()
    n["modules"]["top"]["cells"]["timer"]["attributes"]["npq_base"] = f"{0x8000:032b}"
    with pytest.raises(col.CollectError, match="timer: npq_base is 0x8000, but the IP decodes 0x7000"):
        col.collect(n, col.load_descriptions())


@pytest.mark.parametrize(
    "attr, v, match",
    [
        ("npq_name", 1, r"timer: npq_name must be a string"),  # (* npq_name *) without a value
        ("npq_base", "7000h", r"timer: npq_base '7000h' is not an address"),
    ],
)
def test_attributes_written_wrong_are_errors(attr, v, match):
    n = pwm_netlist()
    n["modules"]["top"]["cells"]["timer"]["attributes"][attr] = v
    with pytest.raises(col.CollectError, match=match):
        col.collect(n, col.load_descriptions())


def test_npq_base_gives_the_base_when_the_description_has_none():  # a user IP decoded in the top
    desc = {
        "_file": "blinkreg.toml",
        "type": "acme:blinkreg:1.0",
        "module": "blinkreg",
        "registers": {"value": {"offset": "0x0", "width": 32, "access": "rw"}},
    }
    n = {
        "modules": {
            "top": {
                "attributes": {},
                "cells": {"blink": {"type": "blinkreg", "attributes": {"npq_base": f"{0x9000:032b}"}}},
            },
            "blinkreg": {"attributes": {}, "cells": {}, "parameter_default_values": {}},
        }
    }
    assert ips(n, descs=[desc]) == {
        "blink": {
            "base": "0x9000",
            "type": "acme:blinkreg:1.0",
            "registers": {"value": {"offset": "0x0", "width": 32, "access": "rw"}},
        }
    }
    del n["modules"]["top"]["cells"]["blink"]["attributes"]["npq_base"]
    with pytest.raises(col.CollectError, match=r"blink: the description of blinkreg has no base; add \(\* npq_base"):
        ips(n, descs=[desc])


def test_expressions_allow_only_arithmetic():
    assert col.value("=WIDTH * 4 if IS_INPUT == 0 else 1", {"WIDTH": 5, "IS_INPUT": 0}) == 20
    assert col.value({"w": "=8 + len(ch)", "n": 3}, {"ch": ["a", "b"]}) == {"w": 10, "n": 3}
    for bad in ("=__import__('os')", "=NOPE", "=WIDTH.real", "=1 << 40", "=[1]"):
        with pytest.raises(col.CollectError):
            col.value(bad, {"WIDTH": 1})


def test_a_description_with_an_unknown_key_is_refused(tmp_path):
    (tmp_path / "x.toml").write_text('type = "a:b:1.0"\nmodule = "m"\nuser_parameter = ["x"]\n')
    with pytest.raises(col.CollectError, match=r"x.toml: unknown key user_parameter"):
        col.load_descriptions(tmp_path)
    (tmp_path / "x.toml").write_text('type = "a:b:1.0"\n')
    with pytest.raises(col.CollectError, match=r"x.toml: module missing"):
        col.load_descriptions(tmp_path)


def test_two_descriptions_that_fit_one_instance_are_an_error():
    descs = col.load_descriptions()
    descs.append({**next(d for d in descs if d["module"] == "pwm_timer"), "_file": "copy.toml"})
    with pytest.raises(
        col.CollectError,
        match=r"timer: several descriptions fit pwm_timer: \['pwm_timer.toml', "
        r"'copy.toml'\]",
    ):
        col.collect(pwm_netlist(), descs)


# ------------------------------------------------------------ YoWASP yosys


@pytest.mark.toolchain
def test_9k_base_from_the_rtl(tmp_path):
    got = ips(col.elaborate(bb.sources("tangnano9k", "base"), tmp_path))
    assert design_id(got) == design_id(bb.ips("tangnano9k", "base")) == 0xABF78D8C


@pytest.mark.toolchain
def test_the_example_from_the_rtl(tmp_path):  # yosys' own JSON, where the tests above use pwm_netlist()
    d = load_config(EXAMPLE)
    netlist = col.elaborate([p for _, p in d.sources], tmp_path)
    assert design_id(ips(netlist, d.ips)) == 0x556FAE35
    assert ips(netlist, HAND) == HAND


@pytest.mark.toolchain
def test_the_attributes_do_not_change_the_bundled_9k_bitstream(tmp_path):
    bundled = ROOT / "src" / "nanopynq" / "data" / "designs" / "tangnano9k-base"
    fs = build_gowin(
        bb.sources("tangnano9k", "base"),
        ROOT / "gateware/boards/tangnano9k/tangnano9k.cst",
        get_board("tangnano9k"),
        tmp_path,
        design_id=0xABF78D8C,
    )
    sha = hashlib.sha256(fs.read_bytes()).hexdigest()
    assert sha == hashlib.sha256((bundled / "base.fs").read_bytes()).hexdigest()
    assert sha == json.loads((bundled / "build.json").read_text())["bitstream_sha256"]
