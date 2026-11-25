// Simulation top for frame_ring: cocotb drives the register bus directly (no bridge), plays the DVP
// camera (pclk, vsync, href, d) and the HyperRAM (hyperram_model.py on the pin-side ports).
// Small ring so the full ring, the sequence wrap and the FIFO overflow are quick to reach:
// 4 slots of 256 words, 4-bit WSEQ/RSEQ, a 16-entry (32-word) FIFO. These must equal test_frame_ring.py.
module sim_ring_top (
    input         clk,
    input         rst,
    input  [29:0] bus_adr,
    input  [31:0] bus_dat_w,
    input         bus_we,
    input         bus_stb,
    output [31:0] bus_dat_r,
    output        bus_ack,
    output        xclk,
    input         pclk,
    input         vsync,
    input         href,
    input  [7:0]  d,
    output        ck,
    output        cs_n,
    output [7:0]  dq_o,
    output        dq_oe,
    input  [7:0]  dq_i,
    output        rwds_o,
    output        rwds_oe,
    input         rwds_i
);
    wire        led;
    wire [31:0] dvp_dat, ring_dat;
    wire        dvp_ack, dvp_hit, ring_ack, ring_hit;
    wire        wstart, wvalid, wend;
    wire [7:0]  wdata;

    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(bus_dat_r), .bus_ack(bus_ack), .leds(led), .buttons(2'b00),
        .ext_hit(dvp_hit | ring_hit), .ext_dat_r(dvp_dat | ring_dat), .ext_ack(dvp_ack | ring_ack));
    dvp_frontend #(.BASE(32'h0000_4000)) dvp (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(dvp_dat), .bus_ack(dvp_ack), .hit(dvp_hit), .xclk(xclk),
        .pclk(pclk), .vsync(vsync), .href(href), .d(d),
        .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend));

    wire        cmd_valid, cmd_ready, cmd_write, wd_ready, rd_valid, done;
    wire [21:0] cmd_addr;
    wire [3:0]  cmd_len;
    wire [15:0] wd_data, rd_data;
    frame_ring #(.BASE(32'h0002_0000), .SLOT_WORDS(256), .NSLOTS(4), .SEQW(4), .FIFO_AW(4)) ring (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(ring_dat), .bus_ack(ring_ack), .hit(ring_hit),
        .wclk(pclk), .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_write(cmd_write), .cmd_addr(cmd_addr),
        .cmd_len(cmd_len), .wd_ready(wd_ready), .wd_data(wd_data), .rd_valid(rd_valid), .rd_data(rd_data),
        .done(done));
    hyperram_ctrl hram (
        .clk(clk), .rst(rst), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_write(cmd_write),
        .cmd_addr(cmd_addr), .cmd_len(cmd_len), .wd_ready(wd_ready), .wd_data(wd_data),
        .rd_valid(rd_valid), .rd_data(rd_data), .done(done),
        .ck(ck), .cs_n(cs_n), .dq_o(dq_o), .dq_oe(dq_oe), .dq_i(dq_i),
        .rwds_o(rwds_o), .rwds_oe(rwds_oe), .rwds_i(rwds_i));
endmodule
