// LiteX UARTBone-compatible UART <-> register-bus bridge (same FSM as Stream2Wishbone).
// Frame: cmd(1) length(1, 0 = 256) word_addr(4, BE) [data(4*length, BE) for writes].
// cmd 1 write-incr, 2 read-incr, 3 write-fixed, 4 read-fixed. Reads reply 4*length bytes, BE.
// Any non-RECEIVE-CMD state lasting TIMEOUT_CYCLES returns to RECEIVE-CMD.
// Bus: bus_stb is held until bus_ack; a slave answers with a 1-clock ack the clock after stb.
module uartbone_bridge #(
    parameter CLK_HZ         = 27_000_000,
    parameter BAUD           = 115200,
    parameter TIMEOUT_CYCLES = CLK_HZ / 10
) (
    input         clk,
    input         rst,
    input         uart_rx,
    output        uart_tx,
    output [29:0] bus_adr,
    output [31:0] bus_dat_w,
    input  [31:0] bus_dat_r,
    output        bus_we,
    output        bus_stb,
    input         bus_ack
);
    localparam S_CMD = 3'd0, S_LEN = 3'd1, S_ADDR = 3'd2, S_DATA = 3'd3,
               S_WRITE = 3'd4, S_READ = 3'd5, S_SEND = 3'd6;

    reg [2:0]  state;
    reg [7:0]  cmd, length, words;
    reg [31:0] address, data, timer;
    reg [1:0]  acnt, bcnt;
    reg        incr;

    wire       rx_valid;
    wire [7:0] rx_data;
    wire       tx_ready;
    wire       words_done = (words == length - 8'd1);
    wire [7:0] tx_byte    = data >> (8 * (3 - bcnt));

    uart_rx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_rx (
        .clk(clk), .rst(rst), .rx(uart_rx), .valid(rx_valid), .data(rx_data));
    uart_tx #(.CLK_HZ(CLK_HZ), .BAUD(BAUD)) u_tx (
        .clk(clk), .rst(rst), .valid(state == S_SEND), .data(tx_byte), .ready(tx_ready), .tx(uart_tx));

    assign bus_adr   = address[29:0];
    assign bus_dat_w = data;
    assign bus_we    = (state == S_WRITE);
    assign bus_stb   = (state == S_WRITE) || (state == S_READ);

    always @(posedge clk) begin
        timer <= (state == S_CMD) ? 32'd0 : timer + 1'b1;
        if (rst || timer == TIMEOUT_CYCLES) begin
            state <= S_CMD;
        end else begin
            case (state)
                S_CMD: begin
                    acnt  <= 0;
                    bcnt  <= 0;
                    words <= 0;
                    if (rx_valid) begin
                        cmd   <= rx_data;
                        state <= S_LEN;
                    end
                end
                S_LEN: if (rx_valid) begin
                    length <= rx_data;
                    state  <= S_ADDR;
                end
                S_ADDR: if (rx_valid) begin
                    address <= {address[23:0], rx_data};
                    acnt    <= acnt + 1'b1;
                    if (acnt == 2'd3) begin
                        incr <= (cmd == 8'h01) || (cmd == 8'h02);
                        if (cmd == 8'h01 || cmd == 8'h03) state <= S_DATA;
                        else if (cmd == 8'h02 || cmd == 8'h04) state <= S_READ;
                        else state <= S_CMD;
                    end
                end
                S_DATA: if (rx_valid) begin
                    data <= {data[23:0], rx_data};
                    bcnt <= bcnt + 1'b1;
                    if (bcnt == 2'd3) state <= S_WRITE;
                end
                S_WRITE: if (bus_ack) begin
                    words   <= words + 1'b1;
                    address <= address + incr;
                    state   <= words_done ? S_CMD : S_DATA;
                end
                S_READ: if (bus_ack) begin
                    data  <= bus_dat_r;
                    state <= S_SEND;
                end
                S_SEND: if (tx_ready) begin
                    bcnt <= bcnt + 1'b1;
                    if (bcnt == 2'd3) begin
                        words   <= words + 1'b1;
                        address <= address + incr;
                        state   <= words_done ? S_CMD : S_READ;
                    end
                end
                default: state <= S_CMD;
            endcase
        end
    end
endmodule
