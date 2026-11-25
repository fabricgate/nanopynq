// P0 spike: the 4K base (GW_JTAG link) plus hram_probe on the SiP HyperRAM. Throwaway.
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
    output       O_hpram_ck,       // renamed to O_hpram_ck[0] etc. after synthesis (see hram_probe.py):
    output       O_hpram_ck_n,     // nextpnr places the SiP pins by those names, and declaring [1:0]
    output       O_hpram_cs_n,     // would put the non-existent second channel on the JTAG pads
    output       O_hpram_reset_n,
    inout  [7:0] IO_hpram_dq,
    inout        IO_hpram_rwds
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
    wire [31:0] dat_w, dat_r, hr_dat;
    wire        we, stb, ack, hr_ack, hr_hit, leds;
    jtag_bridge bridge (
        .clk(clk), .rst(rst), .jtag_tck(tck), .jtag_tdi(tdi), .jtag_shift_dr(sdr),
        .jtag_update_dr(udr), .jtag_enable(en1), .jtag_tdo(tdo),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(hr_hit), .ext_dat_r(hr_dat), .ext_ack(hr_ack));
    assign led = ~leds;

    wire       ck, cs_n, dq_oe, rwds_o, rwds_oe;
    wire [7:0] dq_o;
    hram_probe #(.BASE(32'h0000_5000)) hram (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(hr_dat), .bus_ack(hr_ack), .hit(hr_hit),
        .ck(ck), .cs_n(cs_n), .dq_o(dq_o), .dq_oe(dq_oe), .dq_i(IO_hpram_dq),
        .rwds_o(rwds_o), .rwds_oe(rwds_oe), .rwds_i(IO_hpram_rwds));
    assign O_hpram_ck      = ck;
    assign O_hpram_ck_n    = ~ck;
    assign O_hpram_cs_n    = cs_n;
    assign O_hpram_reset_n = !rst;
    assign IO_hpram_dq     = dq_oe ? dq_o : 8'bz;
    assign IO_hpram_rwds   = rwds_oe ? rwds_o : 1'bz;
endmodule
