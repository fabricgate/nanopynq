// DVP camera front end: drives XCLK, turns PCLK/VSYNC/HREF/D into the capture write port.
// Byte addresses from BASE:
//   +0x0 CTRL (rw): [0] XCLK on (board clock / 2), [2:1] bytes to keep per line: 0 all, 1 even, 2 odd
//        (YUV422 from an OV2640 carries Y in every other byte),
//        [3] the frame is while VSYNC is high (else while it is low)
//   +0x4 FRAMES (ro): VSYNC rising edges seen (to tell whether the sensor is running)
//   +0x8 PCLKS (ro): PCLK rising edges while VSYNC was at the frame level, in the last whole frame
//   +0xC LINES (ro): HREF rising edges in the last whole frame
//   (PCLKS and LINES are counted on PCLK and cross to clk at the frame end as a toggle, like capture's done)
// Write port (pclk domain): wstart when VSYNC enters the frame level, wend when it leaves it (the
// Tang Nano 4K's OV2640 drives VSYNC high during the frame after its init table, but pulses it high
// between frames before that, so the level is a register); wvalid/wdata for kept bytes while HREF
// is high, sampled on the rising edge of PCLK.
module dvp_frontend #(
    parameter BASE = 32'h0000_4000
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r,
    output reg        bus_ack,
    output            hit,
    output reg        xclk = 1'b0,
    input             pclk,
    input             vsync,
    input             href,
    input      [7:0]  d,
    output reg        wstart = 1'b0,
    output reg        wvalid = 1'b0,
    output reg [7:0]  wdata = 8'd0,
    output reg        wend = 1'b0
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 30'd4);

    reg [3:0]  ctrl = 4'd0;
    reg [2:0]  vs_s = 3'd0, fe_s = 3'd0;
    reg [31:0] frames = 32'd0, pclks_c = 32'd0, lines_c = 32'd0;
    wire       fe_t;
    wire [31:0] pclks_w, lines_w;

    always @(posedge clk) begin
        bus_ack   <= !rst && bus_stb && !bus_ack;
        case (rel[1:0])
            2'd0: bus_dat_r <= hit ? {28'd0, ctrl} : 32'd0;
            2'd1: bus_dat_r <= hit ? frames : 32'd0;
            2'd2: bus_dat_r <= hit ? pclks_c : 32'd0;
            2'd3: bus_dat_r <= hit ? lines_c : 32'd0;
        endcase
        if (rst) ctrl <= 4'd0;
        else if (hit && rel == 30'd0 && bus_stb && bus_we && !bus_ack) ctrl <= bus_dat_w[3:0];
        xclk   <= ctrl[0] & ~xclk;
        vs_s   <= {vs_s[1:0], vsync};
        if (vs_s[1] & ~vs_s[2]) frames <= frames + 1'b1;
        fe_s   <= {fe_s[1:0], fe_t};
        if (fe_s[2] ^ fe_s[1]) begin
            pclks_c <= pclks_w; lines_c <= lines_w;
        end
    end

    // pclk domain
    reg [2:0] cfg_a = 3'd0, cfg_b = 3'd0;  // {frame level, keep}
    wire [1:0] keep_b = cfg_b[1:0];
    wire       high = cfg_b[2];
    reg       vs1 = 1'b0, vs2 = 1'b0, hr1 = 1'b0, hr2 = 1'b0, odd = 1'b0;
    reg [7:0] d1 = 8'd0;
    reg [31:0] pcnt = 32'd0, lcnt = 32'd0, pclks_p = 32'd0, lines_p = 32'd0;
    reg        fe_p = 1'b0;
    wire       in_now = high ? vs1 : ~vs1, in_prev = high ? vs2 : ~vs2;
    assign fe_t = fe_p;
    assign pclks_w = pclks_p;
    assign lines_w = lines_p;
    always @(posedge pclk) begin
        cfg_a <= ctrl[3:1];
        cfg_b <= cfg_a;
        vs1 <= vsync; hr1 <= href; d1 <= d;
        vs2 <= vs1;   hr2 <= hr1;
        wstart <= high ? (vs1 & ~vs2) : (vs2 & ~vs1);
        wend   <= high ? (vs2 & ~vs1) : (vs1 & ~vs2);
        odd    <= hr1 ? (hr2 ? ~odd : 1'b1) : 1'b0;  // the first byte of a line is byte 0 (even)
        wvalid <= hr1 && (keep_b == 2'd0 || (keep_b == 2'd1 && !(hr2 && odd)) || (keep_b == 2'd2 && hr2 && odd));
        wdata  <= d1;
        if (in_now) pcnt <= in_prev ? pcnt + 1'b1 : 32'd1;
        if (in_now) lcnt <= (in_prev ? lcnt : 32'd0) + (hr1 & ~hr2);
        if (in_prev & ~in_now) begin
            pclks_p <= pcnt; lines_p <= lcnt; fe_p <= ~fe_p;
        end
    end
endmodule
