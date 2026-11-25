// 8N1 UART receiver. 2-FF input synchroniser, samples each bit in the middle. `valid` is a 1-clock pulse.
module uart_rx #(
    parameter CLK_HZ = 27_000_000,
    parameter BAUD   = 115200
) (
    input            clk,
    input            rst,
    input            rx,
    output reg       valid,
    output reg [7:0] data
);
    localparam CPB = (CLK_HZ + BAUD / 2) / BAUD;  // clocks per bit
    localparam CW  = $clog2(CPB + 1);

    reg [1:0]    sync;
    reg          busy;
    reg [3:0]    nbit;  // 0 start, 1..8 data, 9 stop
    reg [CW-1:0] cnt;   // counts down to the next sample point

    always @(posedge clk) begin
        sync  <= {sync[0], rx};
        valid <= 1'b0;
        if (rst) begin
            sync <= 2'b11;
            busy <= 1'b0;
        end else if (!busy) begin
            if (!sync[1]) begin  // start edge: first sample in the middle of the start bit
                busy <= 1'b1;
                nbit <= 4'd0;
                cnt  <= CPB / 2 - 1;
            end
        end else if (cnt != 0) begin
            cnt <= cnt - 1'b1;
        end else begin
            cnt  <= CPB - 1;
            nbit <= nbit + 1'b1;
            if (nbit == 0) begin
                if (sync[1]) busy <= 1'b0;  // glitch, not a start bit
            end else if (nbit == 9) begin
                busy  <= 1'b0;
                valid <= sync[1];  // drop frames with a bad stop bit
            end else begin
                data <= {sync[1], data[7:1]};
            end
        end
    end
endmodule
