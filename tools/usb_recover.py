"""Bring the Tang Nano 4K's debugger (BL702) back when it stops answering, without a replug.

Steps, stopping at the first that leaves the IDCODE readable:
  1. USB port reset through pyusb (no admin rights)
  2. the scheduled task from tools/register_usb_restart_task.ps1 (pnputil /restart-device)
Neither power-cycles the board, so a wedged BL702 may still need a replug (exit code 1).
--force runs both steps even when the board answers, to check that they are harmless.

Run (Git Bash):
    PATH="$OSS/lib:$PATH" uv run --no-project --with pyusb python tools/usb_recover.py [--force]
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import usb.core
import usb.util

sys.path.insert(0, str(Path(__file__).resolve().parent / "p0"))
from jtag_mpsse_min import PID, VID, Mpsse, read_idcode

IDCODE = 0x0100981B  # GW1NSR-4C
TASK = "nanopynq-tangnano4k-usb-restart"


def healthy() -> bool:
    m = None
    try:
        m = Mpsse(1000)
        return read_idcode(m) == IDCODE
    except (SystemExit, usb.core.USBError):  # Mpsse exits when the device is absent
        return False
    finally:
        if m is not None:
            try:
                m.close()
            except usb.core.USBError:
                pass


def wait_healthy(seconds: float) -> bool:
    t_end = time.monotonic() + seconds
    while True:
        if healthy():
            return True
        if time.monotonic() >= t_end:
            return False
        time.sleep(1)


def port_reset() -> None:
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print("  device not found")
        return
    try:
        dev.reset()
    except usb.core.USBError as e:
        print(f"  pyusb reset: {e}")
    finally:
        usb.util.dispose_resources(dev)  # an open handle would veto the restart in the next step


def task_state() -> tuple[str, str]:
    """(State, LastRunTime) of the task; State is the enum name, not localised."""
    ps = (
        f"$t = Get-ScheduledTask -TaskName '{TASK}'; $i = $t | Get-ScheduledTaskInfo; "
        "\"$($t.State)|$($i.LastRunTime.ToString('o'))\""
    )
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="oem", errors="replace"
    )
    state, _, last = r.stdout.strip().partition("|")
    return state, last


def task_restart(timeout: float = 70) -> bool:
    """Run the task and wait until that run has finished (the task's own limit is 1 minute).
    schtasks /run returns at once; probing the device while pnputil restarts it vetoes the
    restart (Kernel-PnP event 225), so the caller must not touch the device before this returns."""
    _, before = task_state()
    r = subprocess.run(
        ["schtasks", "/run", "/tn", TASK], capture_output=True, text=True, encoding="oem", errors="replace"
    )  # schtasks prints in the console code page
    print("  " + (r.stdout.strip() or r.stderr.strip()))
    if r.returncode != 0:
        return False
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
        state, last = task_state()
        if last != before and state != "Running":
            return True
        time.sleep(0.5)
    print("  the task did not finish in time")
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true", help="run every step even if the board answers")
    args = ap.parse_args(argv)

    ok = healthy()
    print(f"before: {'ok' if ok else 'no answer'}")
    if ok and not args.force:
        return 0
    for name, step, wait in (("pyusb port reset", port_reset, 10), ("scheduled task", task_restart, 20)):
        print(f"{name}:")
        step()
        ok = wait_healthy(wait)
        print(f"  after: {'ok' if ok else 'no answer'}")
        if ok and not args.force:
            return 0
    if not ok:
        print("still no answer: unplug and replug the board")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
