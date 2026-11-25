// P0 spike: is the Tang Nano 4K's DVP camera alive? Uses only the base design's parts.
// leds[3:0] (0x1000): [0] LED, [1] pull SCL low, [2] pull SDA low, [3] XCLK on (27 MHz / 2 on pin 33)
// buttons[6:0] (0x2000): [1:0] keys, [2] SCL, [3] SDA, [4] VSYNC, [5] HSYNC, [6] PCLK
// The host bit-bangs SCCB through these registers (sccb_probe.py). Pins from the board schematic
// (Tang_Nano_4K_3603, sheet 1). Throwaway; not part of the package.
(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

module top (
    input        clk,
    output       led,
    input  [1:0] btn,
    inout        cam_scl,
    inout        cam_sda,
    output       cam_xclk,
    input        cam_vsync,
    input        cam_hsync,
    input        cam_pclk
);
    reg [4:0] por = 5'd0;
    wire      rst = !por[4];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    wire tck, tdi, sdr, udr, en1, tdo;
    wire tlr, rti1, rti2, pdr, en2;
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

    wire [3:0] outs;
    base_regs #(.LED_WIDTH(4), .BTN_WIDTH(7)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(outs), .buttons({cam_pclk, cam_hsync, cam_vsync, cam_sda, cam_scl, ~btn}),
        .ext_hit(1'b0), .ext_dat_r(32'd0), .ext_ack(1'b0));

    assign led     = ~outs[0];
    assign cam_scl = outs[1] ? 1'b0 : 1'bz;  // open drain; 4.7k pull-ups to 2.5 V on the board
    assign cam_sda = outs[2] ? 1'b0 : 1'bz;

    reg xclk = 1'b0;
    always @(posedge clk) xclk <= outs[3] & ~xclk;
    assign cam_xclk = xclk;
endmodule
