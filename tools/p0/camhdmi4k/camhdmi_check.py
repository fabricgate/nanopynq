"""Camera -> HyperRAM -> HDMI on the Tang Nano 4K (reports/report_4k_peripherals.md 3.6, 3.7: 320x240 shown 2x).

Build:  tools/build_base.py --board tangnano4k --design camhdmi --out DIR
Run (Git Bash; openFPGALoader and libusb on PATH, ffmpeg on PATH, the board's HDMI on a USB capture board):
    PATH="$OSS/bin:$OSS/lib:$PATH" uv run --with numpy python tools/p0/camhdmi4k/camhdmi_check.py DIR
        [--keep] [--device "UGREEN 25773"] [--save PREFIX]
Checks, after Camera.start() and enabling the frame buffer:
  - FPGA counts: camera frames completed at the sensor's rate (5-12/s), HDMI 59-61 fps, no BAD frame
  - two captures 1 s apart at 1280x960 (each source pixel is a 4x4 block there): the picture is not
    uniform, the two differ (the camera image is live), and the column / row differences peak at one
    phase of 4 (the 2x scaling; the phase is free because the capture board may shift the picture)
"""

import argparse
import subprocess
import sys
import time

import numpy as np

from nanopynq import Overlay
from nanopynq.camera import Camera

CTRL, FRAMES, BAD, HFRAMES, STATUS = 0x0, 0x4, 0x8, 0xC, 0x10
CW, CH = 1280, 960
SW, SH = 320, 240  # source size; each source pixel is CW // SW = 4 capture pixels wide
P = CW // SW

ap = argparse.ArgumentParser()
ap.add_argument("design")
ap.add_argument("--keep", action="store_true")
ap.add_argument("--device", default="UGREEN 25773")
ap.add_argument("--save", help="also write PREFIX_a.pgm / PREFIX_b.pgm")
args = ap.parse_args()


def grab() -> np.ndarray:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "dshow", "-rtbufsize", "200M",
           "-pixel_format", "yuyv422", "-video_size", f"{CW}x{CH}", "-i", f"video={args.device}",
           "-ss", "0.5", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw[:CW * CH], np.uint8).reshape(CH, CW).astype(int)


def phase_ratio(img: np.ndarray, axis: int) -> float:
    """Mean |difference| between neighbours, per phase mod P: the largest over the median."""
    d = np.abs(np.diff(img, axis=axis)).mean(axis=1 - axis)
    per = [d[p::P].mean() for p in range(P)]
    return max(per) / max(np.median(per), 1e-3)


def period_is_p(img: np.ndarray, axis: int) -> bool:
    """Per phase mod 2P, the two largest are P apart and within 2x of each other (so not a 2P period)."""
    d = np.abs(np.diff(img, axis=axis)).mean(axis=1 - axis)
    per = np.array([d[p::2 * P].mean() for p in range(2 * P)])
    i, j = np.argsort(per)[::-1][:2]
    return abs(int(i) - int(j)) == P and per[j] > per[i] / 2


ol = Overlay(args.design, board="tangnano4k", download=not args.keep)
ok = True
try:
    cam = Camera(ol.cam_i2c, None, ol.cam_dvp)
    cam.start(SW, SH)
    fb = ol.cam_fb
    fb.write(CTRL, 1)
    time.sleep(1.5)
    f0, h0, t0 = fb.read(FRAMES), fb.read(HFRAMES), time.perf_counter()
    time.sleep(3.0)
    f1, h1, t1 = fb.read(FRAMES), fb.read(HFRAMES), time.perf_counter()
    bad, st = fb.read(BAD), fb.read(STATUS)
    cam_fps, hdmi_fps = (f1 - f0) / (t1 - t0), (h1 - h0) / (t1 - t0)
    good = 5 <= cam_fps <= 12 and 59 <= hdmi_fps <= 61 and bad == 0 and st >> 8 & 1
    ok &= bool(good)
    print(f"camera frames {cam_fps:.2f}/s, HDMI {hdmi_fps:.1f} fps, BAD {bad}, STATUS 0x{st:03x} "
          f"(total frames {f1}) {'ok' if good else 'NG'}")

    a = grab()
    time.sleep(1.0)
    b = grab()
    if args.save:
        for tag, img in (("a", a), ("b", b)):
            with open(f"{args.save}_{tag}.pgm", "wb") as f:
                f.write(f"P5 {CW} {CH} 255\n".encode() + img.astype(np.uint8).tobytes())
    inner_a, inner_b = a[8:-8, 8:-8], b[8:-8, 8:-8]  # skip the capture board's edge (1-line offset)
    std = inner_a.std()
    changed = (np.abs(inner_a - inner_b) > 6).mean()
    hr, vr = phase_ratio(inner_a, 1), phase_ratio(inner_a, 0)
    checks = {
        f"not uniform (std {std:.1f} > 8)": std > 8,
        f"live ({changed:.1%} of pixels changed by > 6, want > 1 %)": changed > 0.01,
        f"2x columns (phase ratio {hr:.1f} > 3)": hr > 3,
        f"2x rows (phase ratio {vr:.1f} > 3)": vr > 3,
        "period 4, not 8 (columns and rows)": period_is_p(inner_a, 1) and period_is_p(inner_a, 0),
    }
    for name, g in checks.items():
        print(f"  {name}: {'ok' if g else 'NG'}")
        ok &= g
    print(f"  mean gray {inner_a.mean():.1f}, min {inner_a.min()}, max {inner_a.max()}")
finally:
    ol.close()
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
