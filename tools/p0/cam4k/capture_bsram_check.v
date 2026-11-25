// Build-only check: capture #(.DEPTH(5120)) on GW1NS-4 (32-bit wide, two clocks, 20 KB = all 10 BSRAMs).
// The write port comes from the camera pins, the bus is a free-running reader, so nothing is optimised away.
module top (input clk, input pclk, input vsync, input href, input [7:0] d, output led);
    reg vs1 = 0, vs2 = 0;
    always @(posedge pclk) begin vs1 <= vsync; vs2 <= vs1; end
    reg [29:0] adr = 30'h4000 + 30'h2000;
    reg        stb = 0, acc = 0;
    wire [31:0] dat;
    wire        ack, hit;
    capture #(.BASE(32'h0001_0000), .DEPTH(5120)) cap (
        .clk(clk), .rst(1'b0), .bus_adr(adr), .bus_dat_w(32'd1), .bus_we(adr == 30'h4000), .bus_stb(stb),
        .bus_dat_r(dat), .bus_ack(ack), .hit(hit),
        .wclk(pclk), .wstart(vs2 & ~vs1), .wvalid(href), .wdata(d), .wend(~vs2 & vs1));
    always @(posedge clk) begin
        stb <= ~ack;
        if (ack) begin adr <= (adr == 30'h6000 + 30'd5119) ? 30'h4000 : adr + 1'b1; acc <= acc ^ (^dat); end
    end
    assign led = acc;
endmodule
