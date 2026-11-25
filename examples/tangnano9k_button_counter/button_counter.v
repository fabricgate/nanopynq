// Button counter: counts the presses of each button, with the contact bounce filtered out. Byte addresses from BASE:
//   +0x0 COUNT0 (ro): presses of button 0 since power-on (wraps at 2^32)
//   +0x4 COUNT1 (ro): presses of button 1
// A button's level is taken once it has stayed the same for DEBOUNCE clocks; a press is a change to pressed.
module button_counter #(
    parameter BASE     = 32'h0000_7000,
    parameter DEBOUNCE = 540_000  // 20 ms at 27 MHz
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r = 32'd0,
    output reg        bus_ack = 1'b0,
    output            hit,
    input      [1:0]  pressed  // 1 = pressed (top.v inverts the active-low pins)
);
    localparam CW = $clog2(DEBOUNCE + 1);

    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 2);

    wire [63:0] counts;  // button 1 in the upper half

    genvar i;
    generate
        for (i = 0; i < 2; i = i + 1) begin : btn
            reg [1:0]    sync = 2'b00;  // the pin is asynchronous: two flip-flops before it is used
            reg          stable = 1'b0;
            reg [CW-1:0] held = {CW{1'b0}};
            reg [31:0]   n = 32'd0;
            assign counts[32*i +: 32] = n;
            always @(posedge clk) begin
                sync <= {sync[0], pressed[i]};
                if (rst) begin
                    stable <= 1'b0; held <= {CW{1'b0}}; n <= 32'd0;
                end else if (sync[1] == stable) begin
                    held <= {CW{1'b0}};
                end else if (held == DEBOUNCE - 1) begin  // the new level has lasted DEBOUNCE clocks
                    stable <= sync[1]; held <= {CW{1'b0}};
                    if (sync[1]) n <= n + 1'b1;
                end else
                    held <= held + 1'b1;
            end
        end
    endgenerate

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        bus_dat_r <= !hit ? 32'd0 : rel[0] ? counts[63:32] : counts[31:0];
    end
endmodule
