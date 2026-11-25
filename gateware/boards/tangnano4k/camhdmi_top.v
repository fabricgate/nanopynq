// Tang Nano 4K camera -> HyperRAM -> HDMI: the base design (GW_JTAG link, sysinfo, LED, buttons) plus the
// OV2640 (i2c_master @0x3000, dvp_frontend @0x4000, as in camstream_top.v), cam_fb @0x6000 (3 frame
// buffers in the SiP HyperRAM) and fb_display: 320x240 gray shown as 640x480@60 on the HDMI connector,
// each pixel a 2x2 block (reports/report_4k_peripherals.md 3.6, 3.7).
// cam_fb and hyperram_ctrl run on hclk = 81 MHz from a second PLLVR (VCO 648 MHz, CK 20.25 MHz as in 3.5);
// the bus (jtag_bridge, 27 MHz) reaches cam_fb's registers through bus_cdc.
// HDMI clocks and outputs as in hdmi_top.v: PLLVR 126 MHz (VCO 1008), CLKDIV /5 -> 25.2 MHz pixel clock,
// OSER10 into TLVDS_OBUF on Bank2. cam_xclk (pin 33) is also on Bank2 (2.5 V), like Sipeed's camera_hdmi.
// HyperRAM ports are renamed O_hpram_ck[0] etc. after synthesis (tools/build_base.py). Built with the
// patched toolchain like the base top.
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
    input  [7:0] cam_d,
    output       O_hpram_ck,
    output       O_hpram_ck_n,
    output       O_hpram_cs_n,
    output       O_hpram_reset_n,
    inout  [7:0] IO_hpram_dq,
    inout        IO_hpram_rwds,
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

    wire [31:0] i2c_dat, dvp_dat, fb_dat;  // fb_*: bus_cdc's 27 MHz side
    wire        i2c_ack, i2c_hit, dvp_ack, dvp_hit, fb_ack, fb_hit;
    wire        leds;
    // Every slave but bus_cdc acks every strobe one clock later (data gated by its hit), and the bridge
    // takes the first ack. bus_cdc answers later, so on its hit the others must not see the strobe.
    wire        stb_1clk = stb & !fb_hit;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb_1clk),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(i2c_hit | dvp_hit | fb_hit), .ext_dat_r(i2c_dat | dvp_dat | fb_dat),
        .ext_ack(i2c_ack | dvp_ack | fb_ack));
    assign led = ~leds;

    wire scl_low, sda_low;
    i2c_master #(.BASE(32'h0000_3000), .DIV(68)) i2c (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb_1clk),
        .bus_dat_r(i2c_dat), .bus_ack(i2c_ack), .hit(i2c_hit),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(cam_scl), .sda_in(cam_sda));
    assign cam_scl = scl_low ? 1'b0 : 1'bz;  // open drain; 4.7k pull-ups to 2.5 V on the board
    assign cam_sda = sda_low ? 1'b0 : 1'bz;

    wire       wstart, wvalid, wend;
    wire [7:0] wdata;
    dvp_frontend #(.BASE(32'h0000_4000)) dvp (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb_1clk),
        .bus_dat_r(dvp_dat), .bus_ack(dvp_ack), .hit(dvp_hit), .xclk(cam_xclk),
        .pclk(cam_pclk), .vsync(cam_vsync), .href(cam_href), .d(cam_d),
        .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend));

    wire        cmd_valid, cmd_ready, cmd_write, wd_ready, rd_valid, done;
    wire [21:0] cmd_addr;
    wire [3:0]  cmd_len;
    wire [15:0] wd_data, rd_data;
    wire        req_t, frame_t, lb_we, have_frame;
    wire [7:0]  req_line, lb_addr;
    wire [31:0] lb_data;

    // HyperRAM clock: 27 x 3 = 81 MHz (VCO 648, keep it >= 600), cam_fb and hyperram_ctrl on it
    wire hclk, hlock;
    PLLVR #(
        .FCLKIN("27"), .DEVICE("GW1NSR-4C"),
        .IDIV_SEL(0), .FBDIV_SEL(2), .ODIV_SEL(8),
        .DYN_IDIV_SEL("false"), .DYN_FBDIV_SEL("false"), .DYN_ODIV_SEL("false"), .DYN_DA_EN("false"),
        .CLKFB_SEL("internal"), .CLKOUT_BYPASS("false"), .CLKOUTP_BYPASS("false"),
        .CLKOUTD_BYPASS("false"), .CLKOUTD_SRC("CLKOUT"), .CLKOUTD3_SRC("CLKOUT"), .DYN_SDIV_SEL(2),
        .PSDA_SEL("0000"), .DUTYDA_SEL("1000")
    ) hpll (
        .CLKIN(clk), .CLKFB(1'b0), .RESET(1'b0), .RESET_P(1'b0), .FBDSEL(6'b0), .IDSEL(6'b0),
        .ODSEL(6'b0), .PSDA(4'b0), .DUTYDA(4'b0), .FDLY(4'b0), .VREN(1'b1),
        .CLKOUT(hclk), .CLKOUTP(), .CLKOUTD(), .CLKOUTD3(), .LOCK(hlock));
    reg [4:0] hpor = 5'd0;  // hclk-domain reset until the PLL has locked
    wire      hrst = !hpor[4];
    always @(posedge hclk or negedge hlock)
        if (!hlock) hpor <= 5'd0;
        else if (hrst) hpor <= hpor + 1'b1;

    wire [29:0] h_adr;
    wire [31:0] h_dat_w, h_dat_r;
    wire        h_we, h_stb, h_ack;
    bus_cdc #(.BASE(32'h0000_6000), .WORDS(5)) fb_cdc (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(fb_dat), .bus_ack(fb_ack), .hit(fb_hit),
        .sclk(hclk), .srst(hrst), .s_adr(h_adr), .s_dat_w(h_dat_w), .s_we(h_we), .s_stb(h_stb),
        .s_dat_r(h_dat_r), .s_ack(h_ack));

    wire fb_hhit;  // always 1 for bus_cdc's cycles
    cam_fb #(.BASE(32'h0000_6000), .W(320), .H(240), .STRIDE(65536)) fb (
        .clk(hclk), .rst(hrst), .bus_adr(h_adr), .bus_dat_w(h_dat_w), .bus_we(h_we), .bus_stb(h_stb),
        .bus_dat_r(h_dat_r), .bus_ack(h_ack), .hit(fb_hhit),
        .wclk(cam_pclk), .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_write(cmd_write), .cmd_addr(cmd_addr),
        .cmd_len(cmd_len), .wd_ready(wd_ready), .wd_data(wd_data), .rd_valid(rd_valid), .rd_data(rd_data),
        .done(done), .req_t(req_t), .req_line(req_line), .frame_t(frame_t),
        .lb_we(lb_we), .lb_addr(lb_addr), .lb_data(lb_data), .have_frame(have_frame));

    wire       ck, cs_n, dq_oe, rwds_o, rwds_oe;
    wire [7:0] dq_o;
    hyperram_ctrl hram (
        .clk(hclk), .rst(hrst), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_write(cmd_write),
        .cmd_addr(cmd_addr), .cmd_len(cmd_len), .wd_ready(wd_ready), .wd_data(wd_data),
        .rd_valid(rd_valid), .rd_data(rd_data), .done(done),
        .ck(ck), .cs_n(cs_n), .dq_o(dq_o), .dq_oe(dq_oe), .dq_i(IO_hpram_dq),
        .rwds_o(rwds_o), .rwds_oe(rwds_oe), .rwds_i(IO_hpram_rwds));
    assign O_hpram_ck      = ck;
    assign O_hpram_ck_n    = ~ck;
    assign O_hpram_cs_n    = cs_n;
    assign O_hpram_reset_n = !hrst;
    assign IO_hpram_dq     = dq_oe ? dq_o : 8'bz;
    assign IO_hpram_rwds   = rwds_oe ? rwds_o : 1'bz;

    // HDMI clocks: 126 MHz serial (VCO 1008 MHz, keep it >= 600) and the 25.2 MHz pixel clock
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
    fb_display #(.SH(1)) disp (
        .clk(hclk), .lb_we(lb_we), .lb_addr(lb_addr), .lb_data(lb_data),
        .pclk(pclk), .prst(prst), .have_frame(have_frame), .req_t(req_t), .req_line(req_line),
        .frame_t(frame_t), .tmds0(w0), .tmds1(w1), .tmds2(w2));

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
