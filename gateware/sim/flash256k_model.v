// Sim-only read model of Gowin's FLASH256K, written for nanopynq from UG295 (table 3-13 truth table,
// table 3-9 / fig. 3-7 timing; FLASH256K timing = FLASH64KZ). A read is XE = YE = 1, then SE rising;
// DOUT is X until Tacc (25 ns max) after SE rises, then word {XADR, YADR}, which holds
// {XADR, YADR} * 0x9E3779B1. err counts protocol violations: PROG / ERASE / NVSTR ever non-zero,
// SE rising without XE & YE, XADR / YADR / XE / YE changing within Tah (25 ns) of SE rising.
`timescale 1ns/1ps
module FLASH256K (
    input      [6:0]  XADR,
    input      [5:0]  YADR,
    input             XE, YE, SE, ERASE, PROG, NVSTR,
    input      [31:0] DIN,
    output reg [31:0] DOUT
);
    integer  err = 0, reads = 0;
    realtime t_se = -1000.0;

    always @(posedge SE) begin
        t_se = $realtime;
        reads = reads + 1;
        if (!(XE === 1'b1 && YE === 1'b1)) err = err + 1;
        DOUT = 32'hxxxx_xxxx;
        #24 DOUT = {XADR, YADR} * 32'h9E37_79B1;
    end
    always @(XADR, YADR, XE, YE) if ($realtime - t_se < 25.0) err = err + 1;
    always @(ERASE, PROG, NVSTR) if (ERASE !== 1'b0 || PROG !== 1'b0 || NVSTR !== 1'b0) err = err + 1;
endmodule
