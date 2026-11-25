import sys
from pathlib import Path
from subprocess import CompletedProcess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import usb_recover


def test_task_restart_waits_until_the_task_has_run(monkeypatch):
    # schtasks /run returns at once; probing the device while pnputil restarts it vetoes the
    # restart (Kernel-PnP 225), so task_restart must return only after a new run has finished.
    states = iter(
        [
            ("Ready", "t0"),  # before /run
            ("Ready", "t0"),  # not started yet
            ("Running", "t1"),
            ("Ready", "t1"),
        ]
    )  # done
    seen = []
    monkeypatch.setattr(usb_recover, "task_state", lambda: seen.append(1) or next(states))
    monkeypatch.setattr(usb_recover.time, "sleep", lambda s: None)
    runs = []
    monkeypatch.setattr(
        usb_recover.subprocess, "run", lambda cmd, **kw: runs.append((cmd, kw)) or CompletedProcess(cmd, 0, "ok", "")
    )
    assert usb_recover.task_restart() is True
    assert len(seen) == 4
    cmd, kw = runs[0]
    assert cmd[:2] == ["schtasks", "/run"]
    assert kw["encoding"] == "oem"  # schtasks prints in the console code page (cp932 here)


def test_task_restart_gives_up_when_the_task_never_runs(monkeypatch):
    monkeypatch.setattr(usb_recover, "task_state", lambda: ("Ready", "t0"))
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(usb_recover.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(usb_recover.time, "sleep", lambda s: None)
    monkeypatch.setattr(usb_recover.subprocess, "run", lambda cmd, **kw: CompletedProcess(cmd, 0, "", ""))
    assert usb_recover.task_restart() is False


def test_port_reset_releases_the_device(monkeypatch):
    class Dev:
        def reset(self):
            pass

    dev = Dev()
    monkeypatch.setattr(usb_recover.usb.core, "find", lambda **kw: dev)
    released = []
    monkeypatch.setattr(usb_recover.usb.util, "dispose_resources", released.append)
    usb_recover.port_reset()
    assert released == [dev]
