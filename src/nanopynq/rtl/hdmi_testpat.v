// DVI/HDMI test pattern source: 640x480@60 timing, a pattern and three TMDS encoders on the pixel clock,
// with registers on the board-clock bus. Byte addresses from BASE:
//   +0x0 CTRL (rw):   [0] 0 = eight colour bars with a 1-pixel white border, 1 = solid COLOR
//   +0x4 COLOR (rw):  [23:0] RGB (R in [23:16]) for the solid mode
//   +0x8 FRAMES (ro): frames sent (counted on the board clock from a per-frame toggle), so the host can
//                     check the pixel clock without a monitor: about 60 per second
// CTRL and COLOR reach the pixel clock through two flip-flops per bit (quasi-static: a change may tear
// one frame). Outputs: TMDS words for channel 0 (blue, carries HSYNC/VSYNC), 1 (green), 2 (red).
module hdmi_testpat #(
    parameter BASE = 32'h0000_6000
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
    input             pclk,
    input             prst,
    output     [9:0]  tmds0,
    output     [9:0]  tmds1,
    output     [9:0]  tmds2
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 30'd3);
    wire wr = hit && bus_stb && bus_we && !bus_ack;

    reg        solid = 1'b0;
    reg [23:0] color = 24'h000000;
    reg [31:0] frames = 32'd0;
    reg [2:0]  ft_s = 3'd0;
    wire       frame_t;
    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        case (rel[1:0])
            2'd0:    bus_dat_r <= hit ? {31'd0, solid} : 32'd0;
            2'd1:    bus_dat_r <= hit ? {8'd0, color} : 32'd0;
            default: bus_dat_r <= hit ? frames : 32'd0;
        endcase
        if (rst) begin solid <= 1'b0; color <= 24'h000000; end
        else if (wr && rel == 30'd0) solid <= bus_dat_w[0];
        else if (wr && rel == 30'd1) color <= bus_dat_w[23:0];
        ft_s <= {ft_s[1:0], frame_t};
        if (ft_s[2] ^ ft_s[1]) frames <= frames + 1'b1;
    end

    // pixel clock domain
    reg [24:0] cfg_a = 25'd0, cfg_b = 25'd0;  // {solid, color}
    always @(posedge pclk) begin
        cfg_a <= {solid, color};
        cfg_b <= cfg_a;
    end

    wire        hs, vs, de, fs;
    wire [11:0] x, y;
    video_timing vt (.clk(pclk), .rst(prst), .hsync(hs), .vsync(vs), .de(de), .x(x), .y(y), .frame_start(fs));

    reg        ft = 1'b0, hs1 = 1'b1, vs1 = 1'b1, de1 = 1'b0;
    reg [23:0] rgb = 24'd0;
    wire       border = x == 12'd0 || x == 12'd639 || y == 12'd0 || y == 12'd479;
    wire [2:0] bar = x < 80 ? 3'd0 : x < 160 ? 3'd1 : x < 240 ? 3'd2 : x < 320 ? 3'd3 :
                     x < 400 ? 3'd4 : x < 480 ? 3'd5 : x < 560 ? 3'd6 : 3'd7;  // 80-pixel bars
    always @(posedge pclk) begin
        if (fs) ft <= ~ft;
        hs1 <= hs; vs1 <= vs; de1 <= de;
        if (cfg_b[24]) rgb <= cfg_b[23:0];
        else if (border) rgb <= 24'hFFFFFF;
        else case (bar)
            3'd0: rgb <= 24'hFFFFFF;  // white
            3'd1: rgb <= 24'hFFFF00;  // yellow
            3'd2: rgb <= 24'h00FFFF;  // cyan
            3'd3: rgb <= 24'h00FF00;  // green
            3'd4: rgb <= 24'hFF00FF;  // magenta
            3'd5: rgb <= 24'hFF0000;  // red
            3'd6: rgb <= 24'h0000FF;  // blue
            default: rgb <= 24'h000000;  // black
        endcase
    end
    assign frame_t = ft;

    tmds_encoder enc0 (.clk(pclk), .d(rgb[7:0]),   .c0(hs1), .c1(vs1), .de(de1), .q(tmds0));
    tmds_encoder enc1 (.clk(pclk), .d(rgb[15:8]),  .c0(1'b0), .c1(1'b0), .de(de1), .q(tmds1));
    tmds_encoder enc2 (.clk(pclk), .d(rgb[23:16]), .c0(1'b0), .c1(1'b0), .de(de1), .q(tmds2));
endmodule
