// Tang Nano 4K HDMI (DVI) test: the base design (GW_JTAG link, sysinfo, LED, buttons) plus hdmi_testpat
// @0x6000 (640x480@60 colour bars or a solid colour, frame counter). Clocks: PLLVR 27 -> 126 MHz
// (VCO 1008 MHz, see pll_top.v), CLKDIV /5 -> 25.2 MHz pixel clock. Each TMDS channel is an OSER10
// (10:1, DDR on the 126 MHz FCLK = 252 Mbit/s) into a true-LVDS TLVDS_OBUF on Bank2 (pins 27-35, the
// board's HDMI connector, AC-coupled). The clock channel sends 0000011111 once per pixel.
// Built with the patched toolchain like the base top.
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
    output       tmds_clk_p,
    output       tmds_clk_n,
    output [2:0] tmds_d_p,
    output [2:0] tmds_d_n
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

    wire [31:0] vid_dat;
    wire        vid_ack, vid_hit, leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(vid_hit), .ext_dat_r(vid_dat), .ext_ack(vid_ack));
    assign led = ~leds;

    wire fclk, pclk, lock;
    PLLVR #(
        .FCLKIN("27"), .DEVICE("GW1NSR-4C"),
        .IDIV_SEL(2), .FBDIV_SEL(13), .ODIV_SEL(8),
        .DYN_IDIV_SEL("false"), .DYN_FBDIV_SEL("false"), .DYN_ODIV_SEL("false"), .DYN_DA_EN("false"),
        .CLKFB_SEL("internal"), .CLKOUT_BYPASS("false"), .CLKOUTP_BYPASS("false"),
        .CLKOUTD_BYPASS("false"), .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"), .DYN_SDIV_SEL(2),
        .PSDA_SEL("0000"), .DUTYDA_SEL("1000")
    ) pll (
        .CLKIN(clk), .CLKFB(1'b0), .RESET(1'b0), .RESET_P(1'b0), .FBDSEL(6'b0), .IDSEL(6'b0),
        .ODSEL(6'b0), .PSDA(4'b0), .DUTYDA(4'b0), .FDLY(4'b0), .VREN(1'b1),
        .CLKOUT(fclk), .CLKOUTP(), .CLKOUTD(), .CLKOUTD3(), .LOCK(lock));
    CLKDIV #(.DIV_MODE("5"), .GSREN("false")) div5 (
        .HCLKIN(fclk), .RESETN(lock), .CALIB(1'b0), .CLKOUT(pclk));

    reg [2:0] prst_s = 3'b111;  // pixel-domain reset until the PLL has locked
    always @(posedge pclk or negedge lock)
        if (!lock) prst_s <= 3'b111;
        else prst_s <= {prst_s[1:0], 1'b0};
    wire prst = prst_s[2];

    wire [9:0] w0, w1, w2;
    hdmi_testpat #(.BASE(32'h0000_6000)) video (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(vid_dat), .bus_ack(vid_ack), .hit(vid_hit),
        .pclk(pclk), .prst(prst), .tmds0(w0), .tmds1(w1), .tmds2(w2));

    wire [39:0] words = {10'b0000011111, w2, w1, w0};  // {clock, red, green, blue}
    wire [3:0]  ser;
    genvar i;
    generate for (i = 0; i < 4; i = i + 1) begin : lane
        OSER10 #(.GSREN("false"), .LSREN("true")) oser (
            .D0(words[i*10+0]), .D1(words[i*10+1]), .D2(words[i*10+2]), .D3(words[i*10+3]),
            .D4(words[i*10+4]), .D5(words[i*10+5]), .D6(words[i*10+6]), .D7(words[i*10+7]),
            .D8(words[i*10+8]), .D9(words[i*10+9]), .PCLK(pclk), .FCLK(fclk), .RESET(prst), .Q(ser[i]));
    end endgenerate
    TLVDS_OBUF b0 (.I(ser[0]), .O(tmds_d_p[0]), .OB(tmds_d_n[0]));
    TLVDS_OBUF b1 (.I(ser[1]), .O(tmds_d_p[1]), .OB(tmds_d_n[1]));
    TLVDS_OBUF b2 (.I(ser[2]), .O(tmds_d_p[2]), .OB(tmds_d_n[2]));
    TLVDS_OBUF bc (.I(ser[3]), .O(tmds_clk_p),  .OB(tmds_clk_n));
endmodule
