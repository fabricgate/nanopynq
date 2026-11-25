// Frame-buffer display: 640x480@60 from a (640 >> SH) x (480 >> SH) grayscale source, each source pixel
// shown as an S x S block, S = 2^SH (SH 1: 320x240, SH 2: 160x120). Two source lines sit in a line buffer
// (BSRAM, 2 x 128 entries of 4 pixels, pixel x in byte x%4): clk writes it (cam_fb), pclk reads it.
// Source line sy lives in half sy[0].
// Line requests go to cam_fb as a toggle with the line number held until the next one: at the start of
// display line y = S*sy (y < 480 - S) for source line sy + 1, and at v = 520 for line 0 (5 lines ahead).
// Until have_frame (async, from cam_fb) the screen is black. frame_t toggles once per frame.
// Pipeline: video_timing (registered x/y/de) -> line buffer read (1 clock) -> byte select -> encoders;
// de/hsync/vsync are delayed one clock to match the read.
module fb_display #(
    parameter SH = 1
) (
    input             clk,
    input             lb_we,
    input      [7:0]  lb_addr,
    input      [31:0] lb_data,
    input             pclk,
    input             prst,
    input             have_frame,
    output reg        req_t = 1'b0,
    output reg [7:0]  req_line = 8'd0,
    output reg        frame_t = 1'b0,
    output     [9:0]  tmds0,
    output     [9:0]  tmds1,
    output     [9:0]  tmds2
);
    localparam [11:0] S = 12'd1 << SH;
    reg [31:0] lb [0:255];
    always @(posedge clk) if (lb_we) lb[lb_addr] <= lb_data;

    wire        hs, vs, de, fs;
    wire [11:0] x, y;
    wire [11:0] sx = x >> SH, sy = y >> SH;  // source pixel and line
    video_timing vt (.clk(pclk), .rst(prst), .hsync(hs), .vsync(vs), .de(de), .x(x), .y(y), .frame_start(fs));

    reg [31:0] q = 32'd0;
    reg [1:0]  have_s = 2'd0, bsel = 2'd0;
    reg        hs1 = 1'b1, vs1 = 1'b1, de1 = 1'b0;
    always @(posedge pclk) begin
        q      <= lb[{sy[0], sx[8:2]}];
        bsel   <= sx[1:0];
        hs1    <= hs;
        vs1    <= vs;
        de1    <= de;
        have_s <= {have_s[0], have_frame};
        if (fs) frame_t <= ~frame_t;
        if (!prst && x == 12'd0) begin
            if (y < 12'd480 - S && (y & (S - 1'b1)) == 12'd0) begin
                req_line <= sy[7:0] + 1'b1; req_t <= ~req_t;
            end else if (y == 12'd520) begin
                req_line <= 8'd0; req_t <= ~req_t;
            end
        end
    end
    wire [7:0] gray = !have_s[1] ? 8'd0 : bsel == 2'd0 ? q[7:0] : bsel == 2'd1 ? q[15:8] :
                      bsel == 2'd2 ? q[23:16] : q[31:24];

    tmds_encoder enc0 (.clk(pclk), .d(gray), .c0(hs1), .c1(vs1), .de(de1), .q(tmds0));
    tmds_encoder enc1 (.clk(pclk), .d(gray), .c0(1'b0), .c1(1'b0), .de(de1), .q(tmds1));
    tmds_encoder enc2 (.clk(pclk), .d(gray), .c0(1'b0), .c1(1'b0), .de(de1), .q(tmds2));
endmodule
