// Simulation top for cam_fb: cam_fb + hyperram_ctrl. cocotb drives the register bus, the camera write
// port (no dvp_frontend) and the display's request toggle, watches the line-buffer writes, and plays
// the HyperRAM (hyperram_model.py on the pin-side ports). Small frames: these must equal test_cam_fb.py.
module sim_camfb_top #(parameter W = 320, parameter H = 4, parameter STRIDE = 1024) (
    input         clk,
    input         rst,
    input  [29:0] bus_adr,
    input  [31:0] bus_dat_w,
    input         bus_we,
    input         bus_stb,
    output [31:0] bus_dat_r,
    output        bus_ack,
    output        hit,
    input         wclk,
    input         wstart,
    input         wvalid,
    input  [7:0]  wdata,
    input         wend,
    input         req_t,
    input  [7:0]  req_line,
    input         frame_t,
    output        lb_we,
    output [7:0]  lb_addr,
    output [31:0] lb_data,
    output        have_frame,
    output        ck,
    output        cs_n,
    output [7:0]  dq_o,
    output        dq_oe,
    input  [7:0]  dq_i,
    output        rwds_o,
    output        rwds_oe,
    input         rwds_i
);
    wire        cmd_valid, cmd_ready, cmd_write, wd_ready, rd_valid, done;
    wire [21:0] cmd_addr;
    wire [3:0]  cmd_len;
    wire [15:0] wd_data, rd_data;
    cam_fb #(.BASE(32'h0000_6000), .W(W), .H(H), .STRIDE(STRIDE)) fb (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(bus_dat_r), .bus_ack(bus_ack), .hit(hit),
        .wclk(wclk), .wstart(wstart), .wvalid(wvalid), .wdata(wdata), .wend(wend),
        .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_write(cmd_write), .cmd_addr(cmd_addr),
        .cmd_len(cmd_len), .wd_ready(wd_ready), .wd_data(wd_data), .rd_valid(rd_valid), .rd_data(rd_data),
        .done(done), .req_t(req_t), .req_line(req_line), .frame_t(frame_t),
        .lb_we(lb_we), .lb_addr(lb_addr), .lb_data(lb_data), .have_frame(have_frame));
    hyperram_ctrl hram (
        .clk(clk), .rst(rst), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready), .cmd_write(cmd_write),
        .cmd_addr(cmd_addr), .cmd_len(cmd_len), .wd_ready(wd_ready), .wd_data(wd_data),
        .rd_valid(rd_valid), .rd_data(rd_data), .done(done),
        .ck(ck), .cs_n(cs_n), .dq_o(dq_o), .dq_oe(dq_oe), .dq_i(dq_i),
        .rwds_o(rwds_o), .rwds_oe(rwds_oe), .rwds_i(rwds_i));
endmodule
