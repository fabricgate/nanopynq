// Byte-level I2C master (also does SCCB). The host issues one command at a time and polls busy.
// Byte addresses from BASE:
//   +0x0 CMD (write): [2:0] 1 START, 2 STOP, 3 WRITE ([15:8] = byte), 4 READ_ACK, 5 READ_NACK.
//        Ignored while busy.
//   +0x4 STATUS (read): [0] busy, [1] nack (the last WRITE got no ACK), [15:8] the last READ byte.
// Each bit takes 4 quarter periods of DIV clocks (27 MHz, DIV=68: about 99 kHz).
// No clock stretching. scl_low / sda_low pull the open-drain lines low (the top drives 1'bz otherwise).
// The bus acks in 1 clock and STATUS is valid in the ack cycle (jtag_bridge needs a fast ack).
module i2c_master #(
    parameter BASE = 32'h0000_3000,
    parameter DIV  = 68
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
    output reg        scl_low,
    output reg        sda_low,
    input             scl_in,
    input             sda_in
);
    localparam OP_START = 3'd1, OP_STOP = 3'd2, OP_WRITE = 3'd3, OP_READ_ACK = 3'd4, OP_READ_NACK = 3'd5;

    assign hit = (bus_adr == BASE[31:2]) || (bus_adr == BASE[31:2] + 30'd1);
    wire cmd_wr = hit && !bus_adr[0] && bus_stb && bus_we && !bus_ack;

    reg        busy = 1'b0, nack = 1'b0;
    reg [2:0]  op = 3'd0;
    reg [1:0]  q = 2'd0;
    reg [3:0]  bitn = 4'd0;
    reg [7:0]  sh = 8'd0, rdata = 8'd0;
    reg [15:0] cnt = 16'd0;
    reg [1:0]  sda_s = 2'b11;
    wire       sda = sda_s[1];
    wire       tick = (cnt == 16'd0);
    wire       last_q = (q == 2'd3);
    wire       one_bit = (op == OP_START) || (op == OP_STOP);
    wire       finish = last_q && (one_bit || bitn == 4'd8);

    always @(posedge clk) begin
        sda_s     <= {sda_s[0], sda_in};
        bus_ack   <= !rst && bus_stb && !bus_ack;
        bus_dat_r <= (hit && bus_adr[0]) ? {16'd0, rdata, 6'd0, nack, busy} : 32'd0;
        if (rst) begin
            busy <= 1'b0; scl_low <= 1'b0; sda_low <= 1'b0; nack <= 1'b0;
        end else if (!busy) begin
            if (cmd_wr && bus_dat_w[2:0] >= OP_START && bus_dat_w[2:0] <= OP_READ_NACK) begin
                busy <= 1'b1;
                op   <= bus_dat_w[2:0];
                sh   <= bus_dat_w[15:8];
                q    <= 2'd0;
                bitn <= 4'd0;
                cnt  <= DIV - 1;
            end
        end else begin
            cnt <= tick ? DIV - 1 : cnt - 1'b1;
            if (tick) begin
                case (op)
                    OP_START: case (q)
                        2'd0: sda_low <= 1'b0;
                        2'd1: scl_low <= 1'b0;
                        2'd2: sda_low <= 1'b1;
                        2'd3: scl_low <= 1'b1;
                    endcase
                    OP_STOP: case (q)
                        2'd0: sda_low <= 1'b1;
                        2'd1: scl_low <= 1'b0;
                        2'd2: sda_low <= 1'b0;
                        default: ;
                    endcase
                    OP_WRITE: case (q)
                        2'd0: sda_low <= (bitn == 4'd8) ? 1'b0 : !sh[7];
                        2'd1: scl_low <= 1'b0;
                        2'd2: if (bitn == 4'd8) nack <= sda;
                        2'd3: begin scl_low <= 1'b1; sh <= {sh[6:0], 1'b0}; end
                    endcase
                    default: case (q)  // READ_ACK / READ_NACK
                        2'd0: sda_low <= (bitn == 4'd8) ? (op == OP_READ_ACK) : 1'b0;
                        2'd1: scl_low <= 1'b0;
                        2'd2: if (bitn != 4'd8) sh <= {sh[6:0], sda};
                        2'd3: begin scl_low <= 1'b1; if (bitn == 4'd8) rdata <= sh; end
                    endcase
                endcase
                q <= q + 1'b1;
                if (last_q) bitn <= bitn + 1'b1;
                if (finish) busy <= 1'b0;
            end
        end
    end
endmodule
