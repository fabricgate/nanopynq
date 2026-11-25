// Simulation top for the add-on IPs: cocotb drives the register bus directly (no bridge), plays the
// I2C device (it computes the open-drain lines from scl_low/sda_low and feeds scl_in/sda_in back)
// and the DVP camera (pclk, vsync, href, d). capture DEPTH must equal test_camera_ips.py.
module sim_regs_top (
    input         clk,
    input         rst,
    input  [29:0] bus_adr,
    input  [31:0] bus_dat_w,
    input         bus_we,
    input         bus_stb,
    output [31:0] bus_dat_r,
    output        bus_ack,
    output        scl_low,
    output        sda_low,
    input         scl_in,
    input         sda_in,
    output        xclk,
    input         pclk,
    input         vsync,
    input         href,
    input  [7:0]  d
);
    wire        led;
    wire [31:0] i2c_dat, dvp_dat, cap_dat;
    wire        i2c_ack, i2c_hit, dvp_ack, dvp_hit, cap_ack, cap_hit;
    wire        wstart, wvalid, wend;
    wire [7:0]  wdata;

    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(bus_dat_r), .bus_ack(bus_ack), .leds(led), .buttons(2'b00),
        .ext_hit(i2c_hit | dvp_hit | cap_hit), .ext_dat_r(i2c_dat | dvp_dat | cap_dat),
        .ext_ack(i2c_ack | dvp_ack | cap_ack));
    i2c_master #(.BASE(32'h0000_3000), .DIV(4)) i2c (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(i2c_dat), .bus_ack(i2c_ack), .hit(i2c_hit),
        .scl_low(scl_low), .sda_low(sda_low), .scl_in(scl_in), .sda_in(sda_in));
    dvp_frontend #(.BASE(32'h0000_4000)) dvp (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(dvp_dat), .bus_ack(dvp_ack), .hit(dvp_hit), .xclk(xclk),
        .pclk(pclk), .vsync(vsync), .href(href), .d(d),
        .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend));
    capture #(.BASE(32'h0001_0000), .DEPTH(64)) cap (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(cap_dat), .bus_ack(cap_ack), .hit(cap_hit),
        .wclk(pclk), .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend));
endmodule
