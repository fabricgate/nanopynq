// Identification block. Byte addresses: +0x0 ID "NPQ1" (ro), +0x4 VERSION 1.1 (ro),
// +0x8 SCRATCH (rw, 32 bits, 0 after reset; for link tests), +0xc DESIGN_ID (ro, set at build time).
module sysinfo #(
    parameter [31:0] DESIGN_ID = 32'd0
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r,
    output reg        bus_ack,
    output            hit
);
    assign hit = (bus_adr <= 30'd3);

    reg [31:0] scratch;

    always @(posedge clk) begin
        bus_ack   <= !rst && bus_stb && !bus_ack;
        bus_dat_r <= !hit ? 32'd0 : bus_adr[1] ? (bus_adr[0] ? DESIGN_ID : scratch)
                                                : (bus_adr[0] ? 32'h0001_0001 : 32'h4E50_5131);
        if (rst) scratch <= 32'd0;
        else if (bus_adr == 30'd2 && bus_stb && bus_we && !bus_ack) scratch <= bus_dat_w;
    end
endmodule
