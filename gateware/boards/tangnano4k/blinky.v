// Toolchain smoke test: 27 MHz clock -> ~0.8 Hz blink.
module top (input clk, output [0:0] led);
    reg [24:0] cnt = 0;
    always @(posedge clk) cnt <= cnt + 1;
    assign led[0] = cnt[24];
endmodule
