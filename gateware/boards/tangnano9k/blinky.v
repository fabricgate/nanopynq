// Toolchain smoke test: 27 MHz clock -> binary counter on the 6 LEDs.
module top (input clk, output [5:0] led);
    reg [29:0] cnt = 0;
    always @(posedge clk) cnt <= cnt + 1;
    assign led = ~cnt[29:24];
endmodule
