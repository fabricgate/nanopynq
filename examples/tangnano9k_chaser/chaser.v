// LED chaser: rotates a pattern across the LEDs at a set rate, on its own once started. Byte addresses from BASE:
//   +0x0  CTRL    (rw): [0] run, [1] reverse. Clearing [0] clears STEPS (top.v then shows the base leds GPIO)
//   +0x4  PATTERN (rw): the LEDs to light; a write restarts the chase from it
//   +0x8  RATE    (rw): steps per second, 0 holds the pattern
//   +0xC  CURRENT (ro): the chaser's pattern now: on the LEDs while running, held where it stopped otherwise
//   +0x10 STEPS   (ro): steps since [0] of CTRL was set
// The rate needs no divider: each clock adds RATE to an accumulator and steps when it reaches CLK_HZ.
module chaser #(
    parameter BASE   = 32'h0000_7000,
    parameter WIDTH  = 6,
    parameter CLK_HZ = 27_000_000
) (
    input                  clk,
    input                  rst,
    input      [29:0]      bus_adr,
    input      [31:0]      bus_dat_w,
    input                  bus_we,
    input                  bus_stb,
    output reg [31:0]      bus_dat_r = 32'd0,
    output reg             bus_ack = 1'b0,
    output                 hit,
    output                 run,
    output reg [WIDTH-1:0] current = {WIDTH{1'b0}}
);
    localparam ACC_W = $clog2(CLK_HZ + 65536);  // holds acc + RATE without overflow

    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 5);

    reg [1:0]       ctrl = 2'd0;
    reg [WIDTH-1:0] pattern = {WIDTH{1'b0}};
    reg [15:0]      rate = 16'd0;
    reg [31:0]      steps = 32'd0;
    reg [ACC_W-1:0] acc = {ACC_W{1'b0}};
    wire [ACC_W:0]  sum = {1'b0, acc} + rate;  // RATE < CLK_HZ, so at most one step per clock
    wire            step = sum >= CLK_HZ;
    wire            wr = bus_stb && bus_we && hit && !bus_ack;
    assign run = ctrl[0];

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[2:0])
            3'd0:    bus_dat_r <= {30'd0, ctrl};
            3'd1:    bus_dat_r <= {{(32-WIDTH){1'b0}}, pattern};
            3'd2:    bus_dat_r <= {16'd0, rate};
            3'd3:    bus_dat_r <= {{(32-WIDTH){1'b0}}, current};
            default: bus_dat_r <= steps;
        endcase
        if (rst) begin
            ctrl <= 2'd0; pattern <= {WIDTH{1'b0}}; rate <= 16'd0;
            current <= {WIDTH{1'b0}}; steps <= 32'd0; acc <= {ACC_W{1'b0}};
        end else if (wr && rel[2:0] == 3'd1) begin  // a new pattern starts the chase over
            pattern <= bus_dat_w[WIDTH-1:0]; current <= bus_dat_w[WIDTH-1:0]; acc <= {ACC_W{1'b0}};
        end else begin
            if (wr && rel[2:0] == 3'd0) ctrl <= bus_dat_w[1:0];
            if (wr && rel[2:0] == 3'd2) rate <= bus_dat_w[15:0];
            if (!run) begin
                acc <= {ACC_W{1'b0}}; steps <= 32'd0;
            end else if (step) begin
                acc <= sum - CLK_HZ; steps <= steps + 1'b1;
                current <= ctrl[1] ? {current[0], current[WIDTH-1:1]} : {current[WIDTH-2:0], current[WIDTH-1]};
            end else
                acc <= sum[ACC_W-1:0];
        end
    end
endmodule
