"""Add the GW_JTAG entry to a ready-made Apicula chipdb (e.g. from an upstream CI wheel).

Runs fse_create_jtag of the Apicula on PYTHONPATH with the vendor .dat, instead of rebuilding the whole
chipdb (Windows chipdb_builder cannot do the HyperRAM/PSRAM pin search). First checks that this
reproduces the GW1NS-4 and GW2A-18C entries already in the wheel, then patches the given device in place.

Usage (Git Bash): GOWINHOME=<Gowin IDE> PYTHONPATH=<unpacked wheel with the branch's chipdb.py> \
    uv run --no-project --with msgspec --with numpy --with fastcrc python add_jtag_chipdb.py GW1N-9C
"""
import copy, os, sys
from pathlib import Path
from apycula import chipdb, dat_parser, wirenames as wnames
from apycula.chipdb_builder import DEVICE_PARAMS

G = os.environ['GOWINHOME']
pkg = Path(chipdb.__file__).parent

def dat(dev):
    wnames.select_wires(dev)
    v = DEVICE_PARAMS[dev]['device']
    return dat_parser.Datfile(Path(f"{G}/IDE/share/device/{v}/{v}.dat"))

for dev, cell in (('GW1NS-4', (0, 0)), ('GW2A-18C', (27, 50))):
    db = chipdb.load_chipdb(pkg / f'{dev}.msgpack.xz')
    want = db.extra_func[cell].pop('jtag')
    chipdb.fse_create_jtag(db, dev, dat(dev))
    assert db.extra_func[cell]['jtag'] == want, dev
    print(dev, 'reproduced')

dev = sys.argv[1]
p = pkg / f'{dev}.msgpack.xz'
db = chipdb.load_chipdb(p)
before = copy.deepcopy(db.extra_func)
assert not any('jtag' in v for v in before.values()), 'already has jtag'
chipdb.fse_create_jtag(db, dev, dat(dev))
cells = [k for k, v in db.extra_func.items() if 'jtag' in v]
assert len(cells) == 1, cells
cell = cells[0]
assert {k: v for k, v in db.extra_func.items() if k != cell} == {k: v for k, v in before.items() if k != cell}
assert {k: v for k, v in db.extra_func[cell].items() if k != 'jtag'} == before.get(cell, {})
print(dev, cell, db.extra_func[cell]['jtag'])
chipdb.save_chipdb(db, p)
