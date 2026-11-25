// Snoop the user flash DOUT from the fabric while the M3 runs blinky.bin (reports/report_4k_peripherals.md 3.8).
// emcu_core = Apicula's examples/emcu-blinky.v with the flash signals brought out (make_emcu_core.py).
// Registers @0x10000 (read only): +0 fetches (SE pulses), +4 nonzero DOUT samples, +8 OR of all samples,
// +C last word address, +10 last DOUT, +14 sample of word 0 (first fetch of address 0), +18 word 1.
// DOUT is sampled 2 clocks after SE rises (when emcu-blinky's FSM is back in IDLE and the M3 takes HRDATA).
(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

module top (
    input  clk,       // 27 MHz
    inout  mode_led,  // the M3's GPIO0[0]
    input  RXD,
    output TXD,
    input  rst_i      // button, pulled up; low = GSR
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

    wire        sel;
    wire [12:0] faddr;
    wire [31:0] fdout;
    emcu_core core (.snoop_sel(sel), .snoop_addr(faddr), .snoop_dout(fdout),
        .clk(clk), .mode_led(mode_led), .RXD(RXD), .TXD(TXD), .rst_i(rst_i));

    reg        sel_d = 1'b0, p1 = 1'b0, p2 = 1'b0;
    reg [31:0] fetches = 0, nonzero = 0, oracc = 0, last_dout = 0, w0 = 0, w1 = 0;
    reg [12:0] last_addr = 0;
    reg        got0 = 1'b0, got1 = 1'b0;
    always @(posedge clk) begin
        sel_d <= sel;
        p1 <= sel & !sel_d;
        p2 <= p1;
        if (p1) fetches <= fetches + 1'b1;
        if (p2) begin
            last_dout <= fdout; last_addr <= faddr; oracc <= oracc | fdout;
            if (|fdout) nonzero <= nonzero + 1'b1;
            if (faddr == 13'd0 && !got0) begin w0 <= fdout; got0 <= 1'b1; end
            if (faddr == 13'd1 && !got1) begin w1 <= fdout; got1 <= 1'b1; end
        end
    end

    // bus slave in the 1-clock style of spi_master (ack every strobe, data gated by hit)
    wire [29:0] rel = adr - 30'h4000;  // 0x10000 >> 2
    wire        sn_hit = (adr >= 30'h4000) && (rel < 8);
    reg  [31:0] sn_dat = 0;
    reg         sn_ack = 1'b0;
    always @(posedge clk) begin
        sn_ack <= !rst && stb && !sn_ack;
        if (!sn_hit) sn_dat <= 32'd0;
        else case (rel[2:0])
            3'd0: sn_dat <= fetches;
            3'd1: sn_dat <= nonzero;
            3'd2: sn_dat <= oracc;
            3'd3: sn_dat <= {19'd0, last_addr};
            3'd4: sn_dat <= last_dout;
            3'd5: sn_dat <= w0;
            3'd6: sn_dat <= w1;
            default: sn_dat <= {30'd0, got1, got0};
        endcase
    end

    wire leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(2'b00),
        .ext_hit(sn_hit), .ext_dat_r(sn_dat), .ext_ack(sn_ack));
endmodule
