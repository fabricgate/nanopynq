// Video timing generator, 640x480@60 by default (25.175 MHz nominal; 25.2 MHz from the 4K's PLL is
// within monitor tolerance). Syncs are active low. x/y count the visible area from 0 while de is high.
module video_timing #(
    parameter H_ACTIVE = 640, H_FP = 16, H_SYNC = 96, H_BP = 48,
    parameter V_ACTIVE = 480, V_FP = 10, V_SYNC = 2,  V_BP = 33
) (
    input             clk,
    input             rst,
    output reg        hsync = 1'b1,
    output reg        vsync = 1'b1,
    output reg        de = 1'b0,
    output reg [11:0] x = 12'd0,
    output reg [11:0] y = 12'd0,
    output reg        frame_start = 1'b0  // one clock at the first visible pixel of a frame
);
    localparam H_TOTAL = H_ACTIVE + H_FP + H_SYNC + H_BP;
    localparam V_TOTAL = V_ACTIVE + V_FP + V_SYNC + V_BP;
    reg [11:0] h = 12'd0, v = 12'd0;
    always @(posedge clk) begin
        if (rst) begin
            h <= 12'd0; v <= 12'd0;
        end else if (h == H_TOTAL - 1) begin
            h <= 12'd0;
            v <= (v == V_TOTAL - 1) ? 12'd0 : v + 1'b1;
        end else h <= h + 1'b1;
        // h = v = 0 holds during reset: keep de and frame_start low then, or frame_start would stay high
        de    <= !rst && (h < H_ACTIVE) && (v < V_ACTIVE);
        x     <= h;
        y     <= v;
        hsync <= !(h >= H_ACTIVE + H_FP && h < H_ACTIVE + H_FP + H_SYNC);
        vsync <= !(v >= V_ACTIVE + V_FP && v < V_ACTIVE + V_FP + V_SYNC);
        frame_start <= !rst && (h == 0) && (v == 0);
    end
endmodule
