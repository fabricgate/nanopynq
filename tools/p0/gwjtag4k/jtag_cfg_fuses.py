"""Check GW_JTAG config fuses in an IDE bitstream (throwaway analysis).

Usage: jtag_cfg_fuses.py <ide.fs> <reference.fs> [device, default GW1NS-4]
"""
import importlib.resources, sys
from apycula.chipdb import load_chipdb, tile_bitmap, get_shortval_fuses
from apycula.bslib import read_bitstream
from apycula import attrids
from apycula.gowin_pack import add_attr_val

dev = sys.argv[3] if len(sys.argv) > 3 else "GW1NS-4"
with importlib.resources.path("apycula", f"{dev}.msgpack.xz") as p:
    db = load_chipdb(p)

def tiles(fs):
    bm = read_bitstream(fs)[0]
    return tile_bitmap(db, bm, empty=True)

def setbits(tile):
    return {(r, c) for r, row in enumerate(tile) for c, b in enumerate(row) if b}

ide, ref = tiles(sys.argv[1]), tiles(sys.argv[2])
cell = (0, 0)
ttyp = db[cell].ttyp
print("tile", cell, "ttyp", ttyp, "tables:", sorted(db.shortval.get(ttyp, {}).keys()))
a, b = setbits(ide[cell]), setbits(ref[cell])
print("IDE bits:", len(a), "ref bits:", len(b), "only in IDE:", sorted(a - b))
print("only in ref:", sorted(b - a))
cfg = db.shortval.get(ttyp, {}).get("CFG")
if cfg:
    for name in ("JTAG_ER1", "JTAG_ER2"):
        av = set()
        add_attr_val(db, "CFG", av, attrids.cfg_attrids[name], attrids.cfg_attrvals["USED"])
        f = get_shortval_fuses(db, ttyp, av, "CFG")
        print(name, "USED fuses:", sorted(f), "set in IDE:", sorted(f & a), "set in ref:", sorted(f & b))
# which shortval table entries are fully explained by IDE-only bits
diff = a - b
for tname, tbl in db.shortval.get(ttyp, {}).items():
    for key, fz in tbl.items():
        if fz and set(fz) <= a and set(fz) & diff:
            print("table", tname, "key", key, "fuses", sorted(fz))
