// Tang Mega 138K Pro base design plus the onboard DDR3 (2 x 16-bit 4 Gb, 1 GiB on a 32-bit bus): a host window at
// 0x4000_0000 (ddr3_port, master a: one word per access) and a self-test block at 0x3000 (ddr3_test, master b: the
// 8 words of a burst per access), both masters of e-karge's ddr3_ctrl through ddr3_arb. Same UART host link and
// base_regs as top.v. Everything runs from the 50 MHz board clock, the DDR3 with e-karge's ddr3_phy_2to1 (GW5A = 1):
// CK = clk = 50 MHz in DLL-off mode, the controller on every clock, commands/CK/DQS/DQ through ODDR, DQ read through
// IODELAY and IDDR, a read delay of 64 steps per byte lane from the calibration. The IO logic needs the Apicula /
// nextpnr forks (tools/build_base.py, FORK_TOOLS): the GW5A IO block registers, e-karge's HAS_5A_IDES for the
// GW5AST-138C IDDR, and the GW5A IODELAY with dynamic delay. The parameters are those of e-karge's
// examples/tang-mega-138k-2to1-50mhz/top.sv, which passed on this board (reports/report_ddr3_138k_survey.md).
module top #(
    parameter [31:0] DESIGN_ID = 32'd0  // sysinfo design_id, set at build time
) (
    input         clk,       // 50 MHz
    input         uart_rx,
    output        uart_tx,
    output [5:0]  led,
    input  [1:0]  btn,
    output        ddr_ck,
    output        ddr_ck_n,
    output        ddr_reset_n,
    output        ddr_cke,
    output        ddr_cs_n,
    output        ddr_ras_n,
    output        ddr_cas_n,
    output        ddr_we_n,
    output        ddr_odt,
    output [2:0]  ddr_ba,
    output [14:0] ddr_addr,
    output [3:0]  ddr_dm,
    inout  [3:0]  ddr_dqs,
    inout  [3:0]  ddr_dqs_n,
    inout  [31:0] ddr_dq
);
    localparam DQ_W = 32, ROW_W = 15, COL_W = 10, BA_W = 3, DW = 6, SYS_FREQ = 50_000_000;
    localparam TCK_PS = 1_000_000 / (SYS_FREQ / 1_000_000);  // CK = clk
    localparam ADDR_W = BA_W + ROW_W + COL_W, LANES = DQ_W / 8;

    // Power-on reset: the reset key (K16) is not used; hold rst for 128 clocks after configuration.
    reg [7:0] por = 8'd0;
    wire      rst = !por[7];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    // host link and the base registers; ddr3_test sits on base_regs' ext port, ddr3_port beside it
    wire [29:0] adr;
    wire [31:0] dat_w, dat_r, base_dat, port_dat, test_dat;
    wire        we, stb, ack, base_ack, port_ack, port_hit, test_hit, test_ack;
    uartbone_bridge #(.CLK_HZ(SYS_FREQ), .BAUD(115200), .TIMEOUT_CYCLES(SYS_FREQ / 10)) bridge (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));
    assign ack   = base_ack | port_ack;
    assign dat_r = base_dat | port_dat;

    wire        base_stb = stb & ~port_hit;
    wire [5:0]  leds;
    base_regs #(.LED_WIDTH(6), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(base_stb),
        .bus_dat_r(base_dat), .bus_ack(base_ack), .leds(leds), .buttons(~btn),
        .ext_hit(test_hit), .ext_dat_r(test_dat), .ext_ack(test_ack));
    assign led = ~leds;

    // DDR3 controller and PHY (e-karge/gowin-ddr3)
    wire              ctrl_rd, ctrl_wr, ctrl_refresh, data_ready, busy, init_done, calib_done, calib_fail;
    wire [ADDR_W-1:0] ctrl_addr;
    wire [DQ_W-1:0]   ctrl_din, ctrl_dout;
    wire [LANES-1:0]  ctrl_be;
    wire              ctrl_burst;
    wire [8*DQ_W-1:0] ctrl_din_burst, ctrl_dout_burst;
    wire [8*LANES-1:0] ctrl_be_burst;

    wire ce, phy_reset_n, phy_cke, phy_odt, phy_wr, phy_rd, phy_rvalid, phy_ready;
    wire [2:0] phy_cmd;
    wire [ROW_W-1:0] phy_addr;
    wire [BA_W-1:0] phy_ba;
    wire [1:0] phy_wr_ph, phy_rd_ph, phy_wr_shift;
    wire [8*DQ_W-1:0] phy_wdata, phy_rdata;
    wire [DQ_W-1:0] phy_wmask;
    wire [LANES*DW-1:0] phy_rd_delay;

    ddr3_ctrl #(
        .DQ_W(DQ_W), .ROW_W(ROW_W), .COL_W(COL_W), .BA_W(BA_W),
        .NPH(1), .TCK_PS(TCK_PS), .CL(6), .CWL(6), .NWR(5), .DLL_OFF(1),
        .CAL_DW(DW), .CAL_STEPS(2 ** DW), .CAL_PER_LANE(1)
    ) ctrl (
        .clk(clk), .ce(ce), .rst(rst),
        .rd(ctrl_rd), .wr(ctrl_wr), .refresh(ctrl_refresh), .addr(ctrl_addr), .din(ctrl_din), .be(ctrl_be),
        .burst(ctrl_burst), .din_burst(ctrl_din_burst), .be_burst(ctrl_be_burst),
        .dout(ctrl_dout), .dout_burst(ctrl_dout_burst), .data_ready(data_ready), .busy(busy),
        .init_done(init_done), .calib_done(calib_done), .calib_fail(calib_fail),
        .phy_reset_n(phy_reset_n), .phy_cke(phy_cke), .phy_odt(phy_odt),
        .phy_cmd(phy_cmd), .phy_addr(phy_addr), .phy_ba(phy_ba),
        .phy_wr(phy_wr), .phy_wr_ph(phy_wr_ph), .phy_wdata(phy_wdata), .phy_wmask(phy_wmask),
        .phy_rd(phy_rd), .phy_rd_ph(phy_rd_ph), .phy_rd_delay(phy_rd_delay), .phy_wr_shift(phy_wr_shift),
        .phy_rvalid(phy_rvalid), .phy_rdata(phy_rdata), .phy_ready(phy_ready)
    );

    ddr3_phy_2to1 #(.DQ_W(DQ_W), .ROW_W(ROW_W), .BA_W(BA_W), .TCK_PS(TCK_PS), .DW(DW), .GW5A(1)) phy (
        .clk(clk), .lock(1'b1), .ce(ce), .dbg_rx(),
        .phy_reset_n(phy_reset_n), .phy_cke(phy_cke), .phy_odt(phy_odt),
        .phy_cmd(phy_cmd), .phy_addr(phy_addr), .phy_ba(phy_ba),
        .phy_wr(phy_wr), .phy_wr_ph(phy_wr_ph), .phy_wdata(phy_wdata), .phy_wmask(phy_wmask),
        .phy_rd(phy_rd), .phy_rd_ph(phy_rd_ph), .phy_rd_delay(phy_rd_delay), .phy_wr_shift(phy_wr_shift),
        .phy_rvalid(phy_rvalid), .phy_rdata(phy_rdata), .phy_ready(phy_ready),
        .ddr_ck(ddr_ck), .ddr_ck_n(ddr_ck_n), .ddr_reset_n(ddr_reset_n), .ddr_cke(ddr_cke),
        .ddr_cs_n(ddr_cs_n), .ddr_ras_n(ddr_ras_n), .ddr_cas_n(ddr_cas_n), .ddr_we_n(ddr_we_n),
        .ddr_odt(ddr_odt), .ddr_ba(ddr_ba), .ddr_addr(ddr_addr), .ddr_dm(ddr_dm),
        .ddr_dqs(ddr_dqs), .ddr_dqs_n(ddr_dqs_n), .ddr_dq(ddr_dq)
    );

    // two masters (the host window first) and the refresh onto the controller; nothing reaches the DRAM unless the
    // calibration passed (e-karge's calibration ends with calib_done = 1 also when it failed, with calib_fail = 1)
    wire        ddr_ok = calib_done & ~calib_fail;
    wire        a_valid, a_ready, a_write, a_rd_valid, b_valid, b_ready, b_write, b_rd_valid;
    wire [27:0] a_addr, b_addr;
    wire [31:0] a_wdata, a_rd_data;
    wire [255:0] b_wdata, b_rd_data;
    wire [3:0]  a_wmask;
    wire [31:0] b_wmask;
    ddr3_arb #(.REFRESH_CYCLES(SYS_FREQ / 1000 * 78 / 10000)) arb (
        .clk(clk), .rst(rst), .ready(ddr_ok),
        .a_valid(a_valid), .a_ready(a_ready), .a_write(a_write), .a_addr(a_addr), .a_wdata(a_wdata),
        .a_wmask(a_wmask), .a_rd_valid(a_rd_valid), .a_rd_data(a_rd_data),
        .b_valid(b_valid), .b_ready(b_ready), .b_write(b_write), .b_addr(b_addr), .b_wdata(b_wdata),
        .b_wmask(b_wmask), .b_rd_valid(b_rd_valid), .b_rd_data(b_rd_data),
        .rd(ctrl_rd), .wr(ctrl_wr), .refresh(ctrl_refresh), .addr(ctrl_addr), .din(ctrl_din), .be(ctrl_be),
        .burst(ctrl_burst), .din_burst(ctrl_din_burst), .be_burst(ctrl_be_burst),
        .dout(ctrl_dout), .dout_burst(ctrl_dout_burst), .data_ready(data_ready), .busy(busy));
    ddr3_port port (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(port_dat), .bus_ack(port_ack), .hit(port_hit), .ready(ddr_ok),
        .m_valid(a_valid), .m_ready(a_ready), .m_write(a_write), .m_addr(a_addr), .m_wdata(a_wdata),
        .m_wmask(a_wmask), .m_rd_valid(a_rd_valid), .m_rd_data(a_rd_data));
    ddr3_test test (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(base_stb),
        .bus_dat_r(test_dat), .bus_ack(test_ack), .hit(test_hit),
        .init_done(init_done), .calib_done(calib_done), .calib_fail(calib_fail), .rd_delay(phy_rd_delay),
        .m_valid(b_valid), .m_ready(b_ready), .m_write(b_write), .m_addr(b_addr), .m_wdata(b_wdata),
        .m_wmask(b_wmask), .m_rd_valid(b_rd_valid), .m_rd_data(b_rd_data));
endmodule
