// 8N1 UART transmitter. A byte is accepted on valid && ready (ready = idle, independent of valid).
module uart_tx #(
    parameter CLK_HZ = 27_000_000,
    parameter BAUD   = 115200
) (
    input        clk,
    input        rst,
    input        valid,
    input  [7:0] data,
    output       ready,
    output       tx
);
    localparam CPB = (CLK_HZ + BAUD / 2) / BAUD;
    localparam CW  = $clog2(CPB + 1);

    reg [9:0]    shreg;  // {stop, data, start}; all ones when idle
    reg [3:0]    nbit;   // bits still to shift out
    reg [CW-1:0] cnt;

    assign ready = (nbit == 0);
    assign tx    = shreg[0];

    always @(posedge clk) begin
        if (rst) begin
            shreg <= 10'h3FF;
            nbit  <= 4'd0;
        end else if (ready) begin
            if (valid) begin
                shreg <= {1'b1, data, 1'b0};
                nbit  <= 4'd10;
                cnt   <= CPB - 1;
            end
        end else if (cnt != 0) begin
            cnt <= cnt - 1'b1;
        end else begin
            cnt   <= CPB - 1;
            shreg <= {1'b1, shreg[9:1]};
            nbit  <= nbit - 1'b1;
        end
    end
endmodule
