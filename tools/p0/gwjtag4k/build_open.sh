#!/usr/bin/env bash
# Build a GW_JTAG test design (default userdr_open.v) with open tools only (yosys + nextpnr + Apicula).
# Bash (Git Bash). Usage: [BOARD=4k|9k|20k] build_open.sh [out dir] [design .v in this folder]
# OSS = oss-cad-suite 2026-10-22. OVL = folder holding an apycula/ with GW_JTAG for the board's device.
# CHIPDB = nextpnr chipdb built from that Apicula (gowin_arch_gen.py + bbasm -l); 20k may use the bundled one.
# GW_JTAG in Apicula: GW2A-18C (20k) and GW1NS-4 (4k) in master, GW1N-9C (9k) on fork branch gw1n9c-gw_jtag.
set -euo pipefail
: "${OSS:?}" "${OVL:?}" "${CHIPDB:?}"
here=$(cd "$(dirname "$0")" && pwd -W)  # C:/... so the native yosys/nextpnr can read it
out=${1:-build_open}
design=${2:-userdr_open.v}
case ${BOARD:-4k} in
  4k)  dev=GW1NSR-LV4CQN48PC7/I6 fam=          pack=GW1NS-4  synth=             cst=led.cst    popt=--mspi_as_gpio ;;
  9k)  dev=GW1NR-LV9QN88PC6/I5   fam=GW1N-9C   pack=GW1N-9C  synth=             cst=led9k.cst  popt= ;;
  20k) dev=GW2AR-LV18QN88C8/I7   fam=GW2A-18C  pack=GW2A-18C synth="-family gw2a" cst=led20k.cst popt= ;;
  *) echo "BOARD must be 4k, 9k or 20k" >&2; exit 2 ;;
esac
mkdir -p "$out" && cd "$out"
export PATH="$OSS/bin:$OSS/lib:$PATH"
yosys -q -p "read_verilog $here/$design; synth_gowin -top top $synth -json synth.json"
nextpnr-himbaechel --json synth.json --write pnr.json --device "$dev" ${fam:+--vopt family=$fam} \
    --vopt cst="$here/$cst" --chipdb "$CHIPDB" --seed "${SEED:-1}"
PYTHONPATH="$OVL" uv run -q --no-project --with msgspec --with numpy --with fastcrc \
    python -m apycula.gowin_pack -d "$pack" -c $popt -o top.fs pnr.json
echo "$out/top.fs"
