// CRC-32 calculator: the host writes bytes one at a time and reads the CRC of everything written since INIT. It is the
// CRC-32 of zlib, Ethernet and PNG (reflected polynomial 0xEDB88320, start 0xFFFFFFFF, result inverted), so CRC equals
// Python's zlib.crc32 of the same bytes. Byte addresses from BASE:
//   +0x0 INIT   (wo): any write starts over (CRC 0, LENGTH 0)
//   +0x4 DATA   (wo): the low 8 bits are the next byte
//   +0x8 CRC    (ro): the CRC-32 of the bytes so far (0 for none, like zlib.crc32(b""))
//   +0xC LENGTH (ro): bytes written since INIT
// A byte is taken in one clock.
module crc32 #(
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

    // One byte through the CRC register, least significant bit first.
    function [31:0] next_crc(input [31:0] c, input [7:0] d);
        integer k;
        begin
            next_crc = c ^ {24'd0, d};
            for (k = 0; k < 8; k = k + 1)
                next_crc = next_crc[0] ? (next_crc >> 1) ^ 32'hEDB8_8320 : next_crc >> 1;
        end
    endfunction

    reg  [31:0] state = 32'hFFFF_FFFF, length = 32'd0;
    wire        wr = bus_stb && bus_we && hit && !bus_ack;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[1:0])
            2'd2:    bus_dat_r <= ~state;
            2'd3:    bus_dat_r <= length;
            default: bus_dat_r <= 32'd0;  // INIT and DATA are write-only
        endcase
        if (rst || (wr && rel[1:0] == 2'd0)) begin
            state <= 32'hFFFF_FFFF; length <= 32'd0;
        end else if (wr && rel[1:0] == 2'd1) begin
            state <= next_crc(state, bus_dat_w[7:0]); length <= length + 1'b1;
        end
    end
endmodule
