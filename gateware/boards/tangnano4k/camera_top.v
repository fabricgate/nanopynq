// Tang Nano 4K camera overlay: the base design (GW_JTAG link, sysinfo, LED, buttons) plus the OV2640 on
// the DVP connector: i2c_master @0x3000 (SCCB), dvp_frontend @0x4000 (XCLK, bytes to keep),
// capture @0x10000 (20 KB, all 10 BSRAMs). Pins from the board schematic (reports/report_p0_camera4k.md):
// 8-bit data is PIXDATA9..2 (connector D7..D0). Built with the patched toolchain like the base top.
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
    input  [1:0] btn,
    inout        cam_scl,
    inout        cam_sda,
    output       cam_xclk,
    input        cam_pclk,
    input        cam_vsync,
    input        cam_href,
    input  [7:0] cam_d
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

    wire [31:0] i2c_dat, dvp_dat, cap_dat;
    wire        i2c_ack, i2c_hit, dvp_ack, dvp_hit, cap_ack, cap_hit;
    wire        leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(i2c_hit | dvp_hit | cap_hit), .ext_dat_r(i2c_dat | dvp_dat | cap_dat),
        .ext_ack(i2c_ack | dvp_ack | cap_ack));
    assign led = ~leds;

    wire scl_low, sda_low;
    i2c_master #(.BASE(32'h0000_3000), .DIV(68)) i2c (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(i2c_dat), .bus_ack(i2c_ack), .hit(i2c_hit),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(cam_scl), .sda_in(cam_sda));
    assign cam_scl = scl_low ? 1'b0 : 1'bz;  // open drain; 4.7k pull-ups to 2.5 V on the board
    assign cam_sda = sda_low ? 1'b0 : 1'bz;

    wire       wstart, wvalid, wend;
    wire [7:0] wdata;
    dvp_frontend #(.BASE(32'h0000_4000)) dvp (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dvp_dat), .bus_ack(dvp_ack), .hit(dvp_hit), .xclk(cam_xclk),
        .pclk(cam_pclk), .vsync(cam_vsync), .href(cam_href), .d(cam_d),
        .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend));
    capture #(.BASE(32'h0001_0000), .DEPTH(5120)) cap (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(cap_dat), .bus_ack(cap_ack), .hit(cap_hit),
        .wclk(cam_pclk), .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend));
endmodule
