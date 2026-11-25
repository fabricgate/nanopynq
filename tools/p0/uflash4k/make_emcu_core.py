"""Turn Apicula's examples/emcu-blinky.v into emcu_core.v for snoop_top.v: rename the top to emcu_core and
bring out rom_sel, flash_in_addr and rom_out (reports/report_4k_peripherals.md 3.8).

Run: uv run python tools/p0/uflash4k/make_emcu_core.py emcu-blinky.v emcu_core.v
Build snoop_top.v + emcu_core.v + src/nanopynq/rtl/*.v like build_emcu.py (no gowin_pack -c), with a .cst for
clk 45, mode_led 10, TXD 44, RXD 46, rst_i 14; flash blinky.bin with openFPGALoader --mcufw first.
"""
import sys

s = open(sys.argv[1]).read()
s = s.replace("module top (", "module emcu_core (\n  output wire snoop_sel,\n  output wire [12:0] snoop_addr,\n"
              "  output wire [31:0] snoop_dout,", 1)
i = s.index("endmodule")
s = s[:i] + "  assign snoop_sel = rom_sel;\n  assign snoop_addr = flash_in_addr;\n  assign snoop_dout = rom_out;\n" + s[i:]
open(sys.argv[2], "w").write(s)
