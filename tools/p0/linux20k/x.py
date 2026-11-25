"""X display :20 helper (XTest): shot <png> [x y w h] | key <keysym>... | click <x> <y>

Usage: uv run --no-project --with pillow --with python-xlib python tools/p0/linux20k/x.py shot out.png
"""
import sys
import time

from PIL import Image
from Xlib import X, XK, display
from Xlib.ext import xtest

d = display.Display(":20")
root = d.screen().root
cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "shot":
    g = root.get_geometry()
    x, y, w, h = map(int, args[1:5]) if len(args) >= 5 else (0, 0, g.width, g.height)
    raw = root.get_image(x, y, w, h, X.ZPixmap, 0xFFFFFFFF)
    Image.frombytes("RGB", (w, h), raw.data, "raw", "BGRX").save(args[0])
elif cmd == "key":
    for name in args:
        mods = name.split("+")
        codes = [d.keysym_to_keycode(XK.string_to_keysym(k)) for k in mods]
        for c in codes:
            xtest.fake_input(d, X.KeyPress, c)
        for c in reversed(codes):
            xtest.fake_input(d, X.KeyRelease, c)
        d.sync()
        time.sleep(0.3)
elif cmd == "click":
    xtest.fake_input(d, X.MotionNotify, x=int(args[0]), y=int(args[1]))
    xtest.fake_input(d, X.ButtonPress, 1)
    xtest.fake_input(d, X.ButtonRelease, 1)
    d.sync()
