// Simulation top for sdram_test: sdram_ctrl + sdram_arb + sdram_port (master a, the host window) +
// sdram_test (master b; its rd_lat drives the controller), wired like the board top: sdram_test sees
// bus_stb & ~port_hit, and the bus ack / read data are the OR of the two slaves. The SDRAM pins are out
// (sdram_model.SDRAMModel attaches to them).
module sim_sdram_test_top (
    input         clk,
    input         rst,
    input  [29:0] bus_adr,
    input  [31:0] bus_dat_w,
    input         bus_we,
    input         bus_stb,
    output [31:0] bus_dat_r,
    output        bus_ack,
    output        init_done,
    output        sdram_clk,
    output        sdram_cke,
    output        sdram_cs_n,
    output        sdram_ras_n,
    output        sdram_cas_n,
    output        sdram_we_n,
    output [1:0]  sdram_ba,
    output [10:0] sdram_a,
    output [3:0]  sdram_dqm,
    output [31:0] dq_o,
    output        dq_oe,
    input  [31:0] dq_i
);
    wire        a_valid, a_ready, a_write, a_rd_valid, b_valid, b_ready, b_write, b_rd_valid;
    wire        c_valid, c_ready, c_write, c_rd_valid;
    wire [20:0] a_addr, b_addr, c_addr;
    wire [31:0] a_wdata, a_rd_data, b_wdata, b_rd_data, c_wdata, c_rd_data;
    wire [3:0]  a_wmask, b_wmask, c_wmask;
    wire [2:0]  rd_lat;
    wire        port_hit, test_hit, port_ack, test_ack;
    wire [31:0] port_dat, test_dat;

    assign bus_ack   = port_ack | test_ack;
    assign bus_dat_r = port_dat | test_dat;

    sdram_ctrl ctrl (
        .clk(clk), .rst(rst), .rd_lat(rd_lat),
        .cmd_valid(c_valid), .cmd_ready(c_ready), .cmd_write(c_write), .cmd_addr(c_addr),
        .cmd_wdata(c_wdata), .cmd_wmask(c_wmask), .rd_valid(c_rd_valid), .rd_data(c_rd_data),
        .init_done(init_done), .sdram_clk(sdram_clk), .sdram_cke(sdram_cke), .sdram_cs_n(sdram_cs_n),
        .sdram_ras_n(sdram_ras_n), .sdram_cas_n(sdram_cas_n), .sdram_we_n(sdram_we_n),
        .sdram_ba(sdram_ba), .sdram_a(sdram_a), .sdram_dqm(sdram_dqm), .dq_o(dq_o), .dq_oe(dq_oe),
        .dq_i(dq_i));
    sdram_arb arb (
        .clk(clk), .rst(rst),
        .a_valid(a_valid), .a_ready(a_ready), .a_write(a_write), .a_addr(a_addr), .a_wdata(a_wdata),
        .a_wmask(a_wmask), .a_rd_valid(a_rd_valid), .a_rd_data(a_rd_data),
        .b_valid(b_valid), .b_ready(b_ready), .b_write(b_write), .b_addr(b_addr), .b_wdata(b_wdata),
        .b_wmask(b_wmask), .b_rd_valid(b_rd_valid), .b_rd_data(b_rd_data),
        .c_valid(c_valid), .c_ready(c_ready), .c_write(c_write), .c_addr(c_addr), .c_wdata(c_wdata),
        .c_wmask(c_wmask), .c_rd_valid(c_rd_valid), .c_rd_data(c_rd_data));
    sdram_port port (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(port_dat), .bus_ack(port_ack), .hit(port_hit), .init_done(init_done),
        .m_valid(a_valid), .m_ready(a_ready), .m_write(a_write), .m_addr(a_addr), .m_wdata(a_wdata),
        .m_wmask(a_wmask), .m_rd_valid(a_rd_valid), .m_rd_data(a_rd_data));
    sdram_test test (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we),
        .bus_stb(bus_stb & ~port_hit), .bus_dat_r(test_dat), .bus_ack(test_ack), .hit(test_hit),
        .rd_lat(rd_lat),
        .m_valid(b_valid), .m_ready(b_ready), .m_write(b_write), .m_addr(b_addr), .m_wdata(b_wdata),
        .m_wmask(b_wmask), .m_rd_valid(b_rd_valid), .m_rd_data(b_rd_data));
endmodule
