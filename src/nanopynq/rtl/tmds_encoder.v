// TMDS (DVI 1.0, section 3.2.3) 8b/10b encoder, one word per clock, registered output.
// q[0] is the first bit on the wire. While de is low it sends the control code for {c1, c0} and resets the
// running disparity. Checked word for word against a Python model in gateware/sim/test_video.py.
module tmds_encoder (
    input            clk,
    input      [7:0] d,
    input            c0,
    input            c1,
    input            de,
    output reg [9:0] q = 10'd0
);
    function [3:0] ones8(input [7:0] v);
        integer i;
        begin
            ones8 = 4'd0;
            for (i = 0; i < 8; i = i + 1) ones8 = ones8 + v[i];
        end
    endfunction

    wire [3:0] n1d  = ones8(d);
    wire       xnor_ = (n1d > 4'd4) || (n1d == 4'd4 && !d[0]);
    wire [8:0] qm;
    assign qm[0] = d[0];
    genvar i;
    generate for (i = 1; i < 8; i = i + 1) begin : stage
        assign qm[i] = xnor_ ? ~(qm[i - 1] ^ d[i]) : (qm[i - 1] ^ d[i]);
    end endgenerate
    assign qm[8] = ~xnor_;

    wire [3:0]        n1q  = ones8(qm[7:0]);
    wire signed [5:0] diff = $signed({1'b0, n1q, 1'b0}) - 6'sd8;  // n1q - n0q = 2 * n1q - 8
    reg signed [5:0]  cnt = 6'sd0;

    always @(posedge clk) begin
        if (!de) begin
            cnt <= 6'sd0;
            case ({c1, c0})
                2'b00: q <= 10'b1101010100;
                2'b01: q <= 10'b0010101011;
                2'b10: q <= 10'b0101010100;
                default: q <= 10'b1010101011;
            endcase
        end else if (cnt == 0 || diff == 0) begin
            q   <= {~qm[8], qm[8], qm[8] ? qm[7:0] : ~qm[7:0]};
            cnt <= qm[8] ? cnt + diff : cnt - diff;
        end else if ((cnt > 0 && diff > 0) || (cnt < 0 && diff < 0)) begin
            q   <= {1'b1, qm[8], ~qm[7:0]};
            cnt <= cnt + $signed({4'd0, qm[8], 1'b0}) - diff;
        end else begin
            q   <= {1'b0, qm[8], qm[7:0]};
            cnt <= cnt - $signed({4'd0, ~qm[8], 1'b0}) + diff;
        end
    end
endmodule
