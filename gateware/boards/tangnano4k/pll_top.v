// Tang Nano 4K PLL check: the base design (GW_JTAG link, sysinfo, LED, buttons) plus a PLLVR and a
// clk_meter @0x5000 that counts, per 100 ms gate of the 27 MHz board clock:
//   ch0 CLKOUT  126 MHz  (27 / 3 * 14, ODIV 8 -> VCO 1008 MHz): the 5x TMDS clock of 640x480 HDMI.
//                        Keep the VCO at 600 MHz or above: `apycula.gowin_pll` allows 400, but the IDE
//                        rejects < 600 and ODIV 4 (VCO 504) never locked on the board (reports/report_4k_peripherals.md)
//   ch1 CLKDIV  25.2 MHz (CLKOUT / 5): the pixel clock
//   ch2 CLKOUTD 31.5 MHz (CLKOUT / SDIV 4): not used by any Apicula example
// Expected counts: 12 600 000, 2 520 000, 3 150 000 (+-1). Built with the patched toolchain like the base top.
(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

module top #(
    parameter [31:0] DESIGN_ID = 32'd0  // sysinfo design_id, set at build time
) (
    input        clk,       // 27 MHz
    output       led,
    input  [1:0] btn
);
    reg [4:0] por = 5'd0;
    wire      rst = !por[4];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    wire tck, tdi, sdr, udr, en1, tdo;
    wire tlr, rti1, rti2, pdr, en2;  // unused GW_JTAG outputs
    (* keep *) GW_JTAG u_gw_jtag (
        .tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr), .run_test_idle_er1_o(rti1),
        .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr), .pause_dr_o(pdr),
        .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(tdo), .tdo_er2_i(1'b1));

    wire [29:0] adr;
    wire [31:0] dat_w, dat_r;
    wire        we, stb, ack;
    jtag_bridge bridge (
        .clk(clk), .rst(rst), .jtag_tck(tck), .jtag_tdi(tdi), .jtag_shift_dr(sdr),
        .jtag_update_dr(udr), .jtag_enable(en1), .jtag_tdo(tdo),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));

    wire [31:0] mtr_dat;
    wire        mtr_ack, mtr_hit, leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(mtr_hit), .ext_dat_r(mtr_dat), .ext_ack(mtr_ack));
    assign led = ~leds;

    wire clk126, clk31, clk25, lock;
    PLLVR #(
        .FCLKIN("27"), .DEVICE("GW1NSR-4C"),
        .IDIV_SEL(2), .FBDIV_SEL(13), .ODIV_SEL(8),
        .DYN_IDIV_SEL("false"), .DYN_FBDIV_SEL("false"), .DYN_ODIV_SEL("false"), .DYN_DA_EN("false"),
        .CLKFB_SEL("internal"), .CLKOUT_BYPASS("false"), .CLKOUTP_BYPASS("false"),
        .CLKOUTD_BYPASS("false"), .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"), .DYN_SDIV_SEL(4),
        .PSDA_SEL("0000"), .DUTYDA_SEL("1000")
    ) pll (
        .CLKIN(clk), .CLKFB(1'b0), .RESET(1'b0), .RESET_P(1'b0), .FBDSEL(6'b0), .IDSEL(6'b0),
        .ODSEL(6'b0), .PSDA(4'b0), .DUTYDA(4'b0), .FDLY(4'b0), .VREN(1'b1),
        .CLKOUT(clk126), .CLKOUTP(), .CLKOUTD(clk31), .CLKOUTD3(), .LOCK(lock));
    CLKDIV #(.DIV_MODE("5"), .GSREN("false")) div5 (
        .HCLKIN(clk126), .RESETN(lock), .CALIB(1'b0), .CLKOUT(clk25));

    clk_meter #(.BASE(32'h0000_5000), .N(3)) meter (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(mtr_dat), .bus_ack(mtr_ack), .hit(mtr_hit),
        .mclk({clk31, clk25, clk126}), .lock(lock));
endmodule
