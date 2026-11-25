// Simulation top for ddr3_port and ddr3_test: ddr3_arb with ddr3_port (master a, the 1 GiB host window) and
// ddr3_test (master b), wired like the board top: ddr3_test sees bus_stb & ~port_hit, and the bus ack / read data
// are the OR of the two slaves. The controller side of ddr3_arb is out (ddr3_ctrl_model.Ddr3CtrlModel drives
// busy / dout / data_ready), and so are the calibration inputs (driven by the test).
module sim_ddr3_top (
    input         clk,
    input         rst,
    input  [29:0] bus_adr,
    input  [31:0] bus_dat_w,
    input         bus_we,
    input         bus_stb,
    output [31:0] bus_dat_r,
    output        bus_ack,
    output        port_hit,
    input         init_done,
    input         calib_done,
    input         calib_fail,
    input  [23:0] rd_delay,
    output        rd,
    output        wr,
    output        refresh,
    output [27:0] addr,
    output [31:0] din,
    output [3:0]  be,
    output        burst,
    output [255:0] din_burst,
    output [31:0] be_burst,
    input  [31:0] dout,
    input  [255:0] dout_burst,
    input         data_ready,
    input         busy
);
    wire        a_valid, a_ready, a_write, a_rd_valid, b_valid, b_ready, b_write, b_rd_valid;
    wire [27:0] a_addr, b_addr;
    wire [31:0] a_wdata, a_rd_data, port_dat, test_dat;
    wire [255:0] b_wdata, b_rd_data;
    wire [3:0]  a_wmask;
    wire [31:0] b_wmask;
    wire        port_ack, test_ack, test_hit;

    wire        ddr_ok = calib_done & ~calib_fail;  // as ddr3_top.v
    assign bus_ack   = port_ack | test_ack;
    assign bus_dat_r = port_dat | test_dat;

    ddr3_arb arb (
        .clk(clk), .rst(rst), .ready(ddr_ok),
        .a_valid(a_valid), .a_ready(a_ready), .a_write(a_write), .a_addr(a_addr), .a_wdata(a_wdata),
        .a_wmask(a_wmask), .a_rd_valid(a_rd_valid), .a_rd_data(a_rd_data),
        .b_valid(b_valid), .b_ready(b_ready), .b_write(b_write), .b_addr(b_addr), .b_wdata(b_wdata),
        .b_wmask(b_wmask), .b_rd_valid(b_rd_valid), .b_rd_data(b_rd_data),
        .rd(rd), .wr(wr), .refresh(refresh), .addr(addr), .din(din), .be(be),
        .burst(burst), .din_burst(din_burst), .be_burst(be_burst),
        .dout(dout), .dout_burst(dout_burst), .data_ready(data_ready), .busy(busy));
    ddr3_port port (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(port_dat), .bus_ack(port_ack), .hit(port_hit), .ready(ddr_ok),
        .m_valid(a_valid), .m_ready(a_ready), .m_write(a_write), .m_addr(a_addr), .m_wdata(a_wdata),
        .m_wmask(a_wmask), .m_rd_valid(a_rd_valid), .m_rd_data(a_rd_data));
    ddr3_test test (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we),
        .bus_stb(bus_stb & ~port_hit), .bus_dat_r(test_dat), .bus_ack(test_ack), .hit(test_hit),
        .init_done(init_done), .calib_done(calib_done), .calib_fail(calib_fail), .rd_delay(rd_delay),
        .m_valid(b_valid), .m_ready(b_ready), .m_write(b_write), .m_addr(b_addr), .m_wdata(b_wdata),
        .m_wmask(b_wmask), .m_rd_valid(b_rd_valid), .m_rd_data(b_rd_data));
endmodule
