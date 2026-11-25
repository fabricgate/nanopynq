// Tang Nano 20K base design plus the onboard SDR SDRAM (32-bit, 8 MiB used): a host window at 0x80_0000
// (sdram_port) and a self-test block at 0x3000 (sdram_test), both masters of sdram_ctrl through sdram_arb.
// Same GW_JTAG host link, jtag_bridge and base_regs as top.v. The SDRAM pins are placed by name.
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
    input         clk,       // 27 MHz
    output [5:0]  led,
    input  [1:0]  btn,
    output        O_sdram_clk,
    output        O_sdram_cke,
    output        O_sdram_cs_n,
    output        O_sdram_cas_n,
    output        O_sdram_ras_n,
    output        O_sdram_wen_n,
    output [3:0]  O_sdram_dqm,
    output [10:0] O_sdram_addr,
    output [1:0]  O_sdram_ba,
    inout  [31:0] IO_sdram_dq
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
    wire [31:0] dat_w, dat_r, base_dat, port_dat;
    wire        we, stb, ack, base_ack, port_ack, port_hit;
    jtag_bridge bridge (
        .clk(clk), .rst(rst), .jtag_tck(tck), .jtag_tdi(tdi), .jtag_shift_dr(sdr),
        .jtag_update_dr(udr), .jtag_enable(en1), .jtag_tdo(tdo),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));
    assign ack   = base_ack | port_ack;
    assign dat_r = base_dat | port_dat;

    wire        base_stb = stb & ~port_hit;
    wire        test_hit, test_ack, init_done;
    wire [31:0] test_dat;
    wire [5:0]  leds;
    base_regs #(.LED_WIDTH(6), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(base_stb),
        .bus_dat_r(base_dat), .bus_ack(base_ack), .leds(leds), .buttons(btn),
        .ext_hit(test_hit), .ext_dat_r(test_dat), .ext_ack(test_ack));
    assign led = ~leds;

    wire        a_valid, a_ready, a_write, a_rd_valid, b_valid, b_ready, b_write, b_rd_valid;
    wire        c_valid, c_ready, c_write, c_rd_valid;
    wire [20:0] a_addr, b_addr, c_addr;
    wire [31:0] a_wdata, a_rd_data, b_wdata, b_rd_data, c_wdata, c_rd_data;
    wire [3:0]  a_wmask, b_wmask, c_wmask;
    wire [2:0]  rd_lat;
    wire [31:0] dq_o, dq_i;
    wire        dq_oe;

    sdram_ctrl ctrl (
        .clk(clk), .rst(rst), .rd_lat(rd_lat),
        .cmd_valid(c_valid), .cmd_ready(c_ready), .cmd_write(c_write), .cmd_addr(c_addr),
        .cmd_wdata(c_wdata), .cmd_wmask(c_wmask), .rd_valid(c_rd_valid), .rd_data(c_rd_data),
        .init_done(init_done), .sdram_clk(O_sdram_clk), .sdram_cke(O_sdram_cke), .sdram_cs_n(O_sdram_cs_n),
        .sdram_ras_n(O_sdram_ras_n), .sdram_cas_n(O_sdram_cas_n), .sdram_we_n(O_sdram_wen_n),
        .sdram_ba(O_sdram_ba), .sdram_a(O_sdram_addr), .sdram_dqm(O_sdram_dqm), .dq_o(dq_o), .dq_oe(dq_oe),
        .dq_i(dq_i));
    assign IO_sdram_dq = dq_oe ? dq_o : 32'bz;
    assign dq_i        = IO_sdram_dq;

    sdram_arb arb (
        .clk(clk), .rst(rst),
        .a_valid(a_valid), .a_ready(a_ready), .a_write(a_write), .a_addr(a_addr), .a_wdata(a_wdata),
        .a_wmask(a_wmask), .a_rd_valid(a_rd_valid), .a_rd_data(a_rd_data),
        .b_valid(b_valid), .b_ready(b_ready), .b_write(b_write), .b_addr(b_addr), .b_wdata(b_wdata),
        .b_wmask(b_wmask), .b_rd_valid(b_rd_valid), .b_rd_data(b_rd_data),
        .c_valid(c_valid), .c_ready(c_ready), .c_write(c_write), .c_addr(c_addr), .c_wdata(c_wdata),
        .c_wmask(c_wmask), .c_rd_valid(c_rd_valid), .c_rd_data(c_rd_data));
    sdram_port port (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(port_dat), .bus_ack(port_ack), .hit(port_hit), .init_done(init_done),
        .m_valid(a_valid), .m_ready(a_ready), .m_write(a_write), .m_addr(a_addr), .m_wdata(a_wdata),
        .m_wmask(a_wmask), .m_rd_valid(a_rd_valid), .m_rd_data(a_rd_data));
    sdram_test test (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(base_stb),
        .bus_dat_r(test_dat), .bus_ack(test_ack), .hit(test_hit), .rd_lat(rd_lat),
        .m_valid(b_valid), .m_ready(b_ready), .m_write(b_write), .m_addr(b_addr), .m_wdata(b_wdata),
        .m_wmask(b_wmask), .m_rd_valid(b_rd_valid), .m_rd_data(b_rd_data));
endmodule
