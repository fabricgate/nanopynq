// Clock meter: counts the rising edges of N clocks during a gate of GATE board-clock cycles.
// Both sides come from the same crystal on the board, so a count off the expected ratio means a PLL or
// toolchain problem, not crystal tolerance. Byte addresses from BASE:
//   +0x0          STATUS (ro): [0] lock (input, synchronised), [8+i] channel i has finished a gate
//   +0x4 + 4*i    COUNT[i] (ro): edges of mclk[i] in the last whole gate (+-1). A W-bit count wraps,
//                 so the fastest clock must stay below 2^W * f_clk / GATE.
// Per channel: the gate toggle crosses to mclk through 2 flip-flops; mclk counts between its edges and
// hands the count back with a done toggle, which clk takes once it has crossed (like dvp_frontend's
// PCLKS). The mclk side is only a counter and a holding register, to keep its Fmax high.
module clk_meter #(
    parameter BASE = 32'h0000_5000,
    parameter N    = 3,
    parameter GATE = 2_700_000,  // 100 ms at 27 MHz
    parameter W    = 24
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
    input  [N-1:0]    mclk,
    input             lock
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < N + 1);

    reg [31:0] gcnt = 32'd0;
    reg        gate_t = 1'b0;
    reg [1:0]  lock_s = 2'd0;
    wire [N*W-1:0] counts;
    wire [N-1:0]   valid;
    always @(posedge clk) begin
        if (gcnt == GATE - 1) begin gcnt <= 32'd0; gate_t <= ~gate_t; end
        else gcnt <= gcnt + 1'b1;
        lock_s <= {lock_s[0], lock};
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else if (rel == 30'd0) bus_dat_r <= {{(24 - N){1'b0}}, valid, 7'd0, lock_s[1]};
        else bus_dat_r <= {{(32 - W){1'b0}}, counts[(rel - 1) * W +: W]};
    end

    genvar i;
    generate for (i = 0; i < N; i = i + 1) begin : ch
        clk_meter_ch #(.W(W)) u (.clk(clk), .rst(rst), .gate_t(gate_t), .mclk(mclk[i]),
                                 .count(counts[i * W +: W]), .valid(valid[i]));
    end endgenerate
endmodule

module clk_meter_ch #(parameter W = 24) (
    input              clk,
    input              rst,
    input              gate_t,
    input              mclk,
    output reg [W-1:0] count = {W{1'b0}},
    output reg         valid = 1'b0
);
    // mclk domain
    reg [2:0]   g_s = 3'd0;
    reg [W-1:0] cnt = {W{1'b0}}, hold = {W{1'b0}};
    reg         done_t = 1'b0;
    always @(posedge mclk) begin
        g_s <= {g_s[1:0], gate_t};
        if (g_s[2] ^ g_s[1]) begin hold <= cnt; cnt <= {{(W - 1){1'b0}}, 1'b1}; done_t <= ~done_t; end
        else cnt <= cnt + 1'b1;
    end

    // clk domain: the first hand-back covers a partial gate, so take counts from the second one on
    reg [2:0] d_s = 3'd0;
    reg       seen = 1'b0;
    always @(posedge clk) begin
        d_s <= {d_s[1:0], done_t};
        if (rst) begin seen <= 1'b0; valid <= 1'b0; count <= {W{1'b0}}; end
        else if (d_s[2] ^ d_s[1]) begin
            seen <= 1'b1;
            if (seen) begin count <= hold; valid <= 1'b1; end
        end
    end
endmodule
