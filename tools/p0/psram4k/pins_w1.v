// Build-only: which IO cells does nextpnr put on the GW1NSR-4C SiP HyperRAM pins (sip_cst)?
module top (input clk, output led,
    output [1:0] O_hpram_ck, output [1:0] O_hpram_ck_n, output [1:0] O_hpram_cs_n,
    output [1:0] O_hpram_reset_n, inout [7:0] IO_hpram_dq, inout [1:0] IO_hpram_rwds);
    reg [7:0] c = 0;
    always @(posedge clk) c <= c + 1'b1;
    assign O_hpram_ck = {(1+1){c[0]}};
    assign O_hpram_ck_n = ~O_hpram_ck;
    assign O_hpram_cs_n = {(1+1){c[7]}};
    assign O_hpram_reset_n = {(1+1){1'b1}};
    assign IO_hpram_dq = c[6] ? c : 8'bz;
    assign IO_hpram_rwds = c[5] ? {(1+1){1'b0}} : {(1+1){1'bz}};
    assign led = ^IO_hpram_dq ^ IO_hpram_rwds[0];
endmodule
