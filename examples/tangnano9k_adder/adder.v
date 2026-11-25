// Adder: the host writes a and b, reads sum = a + b (low 32 bits) and carry (bit 32). Byte addresses from BASE:
//   +0x0 A     (rw)
//   +0x4 B     (rw)
//   +0x8 SUM   (ro): a + b modulo 2^32; a write is ignored
//   +0xC CARRY (ro): 1 when a + b does not fit in 32 bits
module adder #(
    parameter BASE = 32'h0000_7000
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r = 32'd0,
    output reg        bus_ack = 1'b0,
    output            hit
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 4);

    reg  [31:0] a = 32'd0, b = 32'd0;
    wire [32:0] total = {1'b0, a} + {1'b0, b};

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[1:0])
            2'd0:    bus_dat_r <= a;
            2'd1:    bus_dat_r <= b;
            2'd2:    bus_dat_r <= total[31:0];
            default: bus_dat_r <= {31'd0, total[32]};
        endcase
        if (rst) begin
            a <= 32'd0; b <= 32'd0;
        end else if (bus_stb && bus_we && hit && !bus_ack)
            case (rel[1:0])
                2'd0:    a <= bus_dat_w;
                2'd1:    b <= bus_dat_w;
                default: ;
            endcase
    end
endmodule
