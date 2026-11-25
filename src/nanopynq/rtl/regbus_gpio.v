// One-word GPIO at byte address BASE. Output: DATA read/write (1 = pin high). Input: DATA read-only,
// pins synchronised with 2 FFs. Only the low WIDTH bits are used.
module regbus_gpio #(
    parameter BASE     = 32'h0000_1000,
    parameter WIDTH    = 6,
    parameter IS_INPUT = 0
) (
    input              clk,
    input              rst,
    input      [29:0]  bus_adr,
    input      [31:0]  bus_dat_w,
    input              bus_we,
    input              bus_stb,
    output reg [31:0]  bus_dat_r,
    output reg         bus_ack,
    output             hit,
    input  [WIDTH-1:0] pins_in,
    output [WIDTH-1:0] pins_out
);
    assign hit = (bus_adr == BASE[31:2]);

    reg [WIDTH-1:0] out_q, in_q0, in_q1;
    assign pins_out = out_q;

    always @(posedge clk) begin
        in_q0     <= pins_in;
        in_q1     <= in_q0;
        bus_ack   <= !rst && bus_stb && !bus_ack;
        bus_dat_r <= !hit ? 32'd0 : IS_INPUT ? {{(32-WIDTH){1'b0}}, in_q1} : {{(32-WIDTH){1'b0}}, out_q};
        if (rst) out_q <= 0;
        else if (!IS_INPUT && hit && bus_stb && bus_we && !bus_ack) out_q <= bus_dat_w[WIDTH-1:0];
    end
endmodule
