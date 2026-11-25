// Simulation models of the Gowin IO primitives ddr3_phy_slow instantiates (OBUF, IOBUF, IDDR), for Icarus.
// IDDR follows the GW5A simulation library's description: D is sampled on the rising edge (Q0) and on the
// falling edge (Q1), and both come out two rising edges later than a plain register would show them.
module OBUF (input I, output O);
    assign O = I;
endmodule

module IOBUF (input I, input OEN, output O, inout IO);
    assign IO = OEN ? 1'bz : I;
    assign O = IO;
endmodule

module IDDR #(
    parameter Q0_INIT = 1'b0,
    parameter Q1_INIT = 1'b0
) (
    input      D,
    input      CLK,
    output reg Q0 = Q0_INIT,
    output reg Q1 = Q1_INIT
);
    reg p0 = Q0_INIT, p1 = Q0_INIT, n0 = Q1_INIT, n1 = Q1_INIT;
    always @(posedge CLK) begin
        p0 <= D;
        p1 <= p0;
        Q0 <= p1;
        n1 <= n0;
        Q1 <= n1;
    end
    always @(negedge CLK) n0 <= D;
endmodule
