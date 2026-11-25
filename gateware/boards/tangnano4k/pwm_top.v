// Tang Nano 4K PWM / timer check: the base design (GW_JTAG link, sysinfo, LED, buttons) plus
// pwm_timer @0x7000 on the 27 MHz clock, and a one-channel clk_meter @0x5000 that counts the rising
// edges of the PWM output per 100 ms gate (expected 2 700 000 / PERIOD, +-1). The LED lights while
// the PWM output or the base LED register is high. Built with the patched toolchain like the base top.
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

    // two slaves behind the base's external port: each reads 0 outside its window and acks every strobe
    wire [31:0] pwm_dat, mtr_dat;
    wire        pwm_ack, mtr_ack, pwm_hit, mtr_hit, leds, pwm;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(pwm_hit | mtr_hit), .ext_dat_r(pwm_dat | mtr_dat), .ext_ack(pwm_ack | mtr_ack));
    assign led = ~(leds | pwm);

    pwm_timer #(.BASE(32'h0000_7000)) timer (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(pwm_dat), .bus_ack(pwm_ack), .hit(pwm_hit), .pwm(pwm));

    clk_meter #(.BASE(32'h0000_5000), .N(1)) meter (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(mtr_dat), .bus_ack(mtr_ack), .hit(mtr_hit), .mclk(pwm), .lock(1'b1));
endmodule
