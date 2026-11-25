// P0 spike (build only): does the patched open toolchain place a PLLVR and a 16 KB dual-clock
// BSRAM on GW1NS-4? PLL parameters from `python -m apycula.gowin_pll -d "GW1NSR-4C C7/I6" -i 27 -o 54`.
// Writes run on the 54 MHz PLL clock (standing in for the camera PCLK), reads on the 27 MHz board clock.
module top (input clk, output led);
    wire clk54, locked;
    PLLVR #(.FCLKIN("27.0"), .IDIV_SEL(0), .FBDIV_SEL(1), .ODIV_SEL(8)) pll (
        .CLKOUTP(), .CLKOUTD(), .CLKOUTD3(), .RESET(1'b0), .RESET_P(1'b0), .CLKFB(1'b0),
        .FBDSEL(6'b0), .IDSEL(6'b0), .ODSEL(6'b0), .PSDA(4'b0), .DUTYDA(4'b0), .FDLY(4'b0),
        .VREN(1'b1), .CLKIN(clk), .CLKOUT(clk54), .LOCK(locked));

    reg [7:0] mem [0:16383];
    reg [13:0] wa = 0, ra = 0;
    reg [7:0]  rd = 0;
    reg        acc = 0;
    always @(posedge clk54) if (locked) begin
        mem[wa] <= wa[7:0] ^ wa[13:6];
        wa <= wa + 1'b1;
    end
    always @(posedge clk) begin
        rd  <= mem[ra];
        ra  <= ra + 1'b1;
        acc <= acc ^ (^rd);
    end
    assign led = acc;
endmodule
