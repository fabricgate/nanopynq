"""Print the GW_JTAG wire tables (JtagIns / JtagOuts) of Gowin .dat files.

Usage (Git Bash, Apicula source on PYTHONPATH):
  PYTHONPATH=<apicula> uv run --no-project --with msgspec --with numpy --with fastcrc \
      python dat_jtag_wires.py <GOWINHOME> GW1NR-9C GW1NSR-4C GW2A-18C
The names are the IDE's device folders. -1 means no wire (pad ports, pause_dr_o).
"""
import sys
from pathlib import Path
from apycula import dat_parser, wirenames as wn

for dev in sys.argv[2:]:
    d = dat_parser.Datfile(Path(f"{sys.argv[1]}/IDE/share/device/{dev}/{dev}.dat"))
    for t in ('JtagIns', 'JtagOuts'):
        v = d.compat_dict.get(t)
        print(dev, t, v, [wn.wirenames_pre5a.get(w, w) if w != -1 else -1 for w in (v or [])])
