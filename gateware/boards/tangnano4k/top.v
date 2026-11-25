// Tang Nano 4K base design, host link over GW_JTAG (user instruction 0x42 = ER1) through the onboard
// BL702: no external USB-UART. LED and buttons are active-low.
// GW_JTAG on GW1NS-4 needs Apicula master (no release yet) + a chipdb from it (tools/p0/gwjtag4k/README.md);
// the pip (YoWASP) tools cannot build this top.
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
    output       led,       // 1 LED: scalar port, the .cst constrains "led"
    input  [1:0] btn
);
    // Power-on reset: no reset pin, hold rst for 16 clocks after configuration.
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

    wire leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(1'b0), .ext_dat_r(32'd0), .ext_ack(1'b0));
    assign led = ~leds;
endmodule
