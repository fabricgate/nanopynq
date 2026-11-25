#!/bin/bash
# Read the M3's 32 KB flash through its debug port, in 256-byte pieces (the BL702 stalls in mpsse_flush() on one
# big dump_image). Needs the chip's JTAG handed to the M3 first (openFPGALoader -b tangnano4k --conmcu; only a
# full power cycle gives it back to the FPGA). Halts the M3. reports/report_4k_mcu_tools.md 8.
# usage: ocd_readback.sh OUT.bin [bytes]      Env: GMD = the GMD folder (its OpenOCD is used)
set -e
OCD="$GMD/toolchain/gowin/openocd"
N=${2:-32768}; cmds=(); for a in $(seq 0 256 $((N - 256))); do cmds+=(-c "mdw $a 64"); done
LOG=$(mktemp)
"$OCD/bin/openocd.exe" -s "$OCD/share/openocd/scripts" -f "$(dirname "$0")/bl702.cfg" -f target/gowin_cm3.cfg \
    -c init -c halt "${cmds[@]}" -c shutdown > "$LOG" 2>&1
python - "$LOG" "$1" "$N" <<'PY'
import re, sys
w = {}
for line in open(sys.argv[1]):
    m = re.match(r"0x([0-9a-f]{8}): (.*)", line.strip())
    if m:
        a = int(m.group(1), 16)
        for i, x in enumerate(m.group(2).split()):
            w[a + 4 * i] = int(x, 16)
n = int(sys.argv[3])
open(sys.argv[2], "wb").write(b"".join(w.get(a, 0).to_bytes(4, "little") for a in range(0, n, 4)))
print(f"{len(w)} of {n // 4} words read")
PY
rm -f "$LOG"
