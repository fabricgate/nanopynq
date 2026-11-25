// Register-bus clock crossing: a slave on sclk answers bus cycles from clk (reports/report_4k_peripherals.md 3.7).
// clk side: hit from the address range [BASE, BASE + 4*WORDS); on a hit, latches adr/dat/we and toggles
// req_t; when ack_t comes back, bus_ack for one clock with the slave's data (bus_dat_r is 0 otherwise,
// it is OR-ed into the shared read bus). The master holds bus_stb until bus_ack (jtag_bridge), so one
// bus cycle makes one slave cycle.
// sclk side: req_t (2 flip-flops) starts s_stb with the latched adr/dat/we, which stay still while the
// toggle crosses; s_stb drops the clock after s_ack, r_dat keeps the read data and ack_t toggles back.
// A round trip is about 3 clk + 3 sclk + the slave's ack.
// The other slaves on this bus ack every strobe one clock later and the bridge takes the first ack, so
// the top must keep bus_stb from them while hit is high (camhdmi_top.v: stb & !hit).
// Limit: a srst during a cycle loses its ack and the master waits for ever; srst is only the
// power-up / PLL lock reset here, before any bus traffic.
module bus_cdc #(
    parameter BASE  = 32'h0000_0000,
    parameter WORDS = 1
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output     [31:0] bus_dat_r,
    output reg        bus_ack = 1'b0,
    output            hit,
    input             sclk,
    input             srst,
    output reg [29:0] s_adr = 30'd0,
    output reg [31:0] s_dat_w = 32'd0,
    output reg        s_we = 1'b0,
    output reg        s_stb = 1'b0,
    input      [31:0] s_dat_r,
    input             s_ack
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < WORDS);

    reg        busy = 1'b0, req_t = 1'b0, ack_t = 1'b0;
    reg [2:0]  ack_s = 3'd0, req_s = 3'd0;
    reg [31:0] r_dat = 32'd0;
    assign bus_dat_r = bus_ack ? r_dat : 32'd0;

    always @(posedge clk) begin
        ack_s   <= {ack_s[1:0], ack_t};
        bus_ack <= 1'b0;
        if (rst) busy <= 1'b0;
        else if (bus_ack) busy <= 1'b0;  // the master drops stb on this clock
        else if (busy) begin
            if (ack_s[2] ^ ack_s[1]) bus_ack <= 1'b1;
        end else if (bus_stb && hit) begin
            s_adr <= bus_adr; s_dat_w <= bus_dat_w; s_we <= bus_we;
            req_t <= ~req_t; busy <= 1'b1;
        end
    end

    always @(posedge sclk) begin
        req_s <= {req_s[1:0], req_t};
        if (srst) s_stb <= 1'b0;
        else if (s_stb) begin
            if (s_ack) begin s_stb <= 1'b0; r_dat <= s_dat_r; ack_t <= ~ack_t; end
        end else if (req_s[2] ^ req_s[1]) s_stb <= 1'b1;
    end
endmodule
