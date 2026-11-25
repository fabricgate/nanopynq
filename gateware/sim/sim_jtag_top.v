// Simulation top for the JTAG bridge: the jtag_* inputs stand in for the GW_JTAG outputs
// (test_jtag_bridge.py drives them the way GW_JTAG was measured to behave).
module sim_jtag_top (
    input        clk,
    input        rst,
    input        jtag_tck,
    input        jtag_tdi,
    input        jtag_shift_dr,
    input        jtag_update_dr,
    input        jtag_enable,
    output       jtag_tdo,
    output [5:0] leds,
    input  [1:0] buttons
);
    wire [29:0] adr;
    wire [31:0] dat_w, dat_r;
    wire        we, stb, ack;

    jtag_bridge bridge (
        .clk(clk), .rst(rst), .jtag_tck(jtag_tck), .jtag_tdi(jtag_tdi), .jtag_shift_dr(jtag_shift_dr),
        .jtag_update_dr(jtag_update_dr), .jtag_enable(jtag_enable), .jtag_tdo(jtag_tdo),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));
    base_regs #(.LED_WIDTH(6), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(buttons),
        .ext_hit(1'b0), .ext_dat_r(32'd0), .ext_ack(1'b0));
endmodule
