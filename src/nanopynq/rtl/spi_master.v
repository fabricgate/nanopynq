// SPI master, mode 0 (SCK idles low, MOSI changes on the falling edge, MISO sampled on the rising
// edge), SCK = clk / 4. The host builds the commands: it holds CS# low through CTRL and moves 1..4
// bytes per DATA write. Byte addresses from BASE:
//   +0x0 CTRL   (rw): [0] cs (1 = CS# low), [2:1] bytes per transfer - 1
//   +0x4 DATA   (rw): a write sends the low N bytes, most significant first ([31:24] first for N = 4,
//                     [7:0] alone for N = 1); a read returns the N bytes received, the first one most
//                     significant, right-aligned
//   +0x8 STATUS (ro): [0] busy (a transfer is shifting; at clk / 4 it lasts 32 * N clocks)
// A DATA write while busy is ignored.
module spi_master #(
    parameter BASE = 32'h0000_8000
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r = 32'd0,
    output reg        bus_ack = 1'b0,
    output            hit,
    output reg        sck = 1'b0,
    output            cs_n,
    output            mosi,
    input             miso
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 3);

    reg        cs = 1'b0, busy = 1'b0;
    reg [1:0]  nm1 = 2'd0, ph = 2'd0;
    reg [31:0] sh = 32'd0, rx = 32'd0;
    reg [5:0]  left = 6'd0;  // bits still to shift
    assign cs_n = !cs;
    assign mosi = sh[31];

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[1:0])
            2'd0:    bus_dat_r <= {29'd0, nm1, cs};
            2'd1:    bus_dat_r <= rx;
            default: bus_dat_r <= {31'd0, busy};
        endcase
        if (rst) begin
            cs <= 1'b0; busy <= 1'b0; sck <= 1'b0; ph <= 2'd0;
        end else begin
            if (bus_stb && bus_we && hit && !bus_ack) begin
                if (rel[1:0] == 2'd0) begin cs <= bus_dat_w[0]; nm1 <= bus_dat_w[2:1]; end
                if (rel[1:0] == 2'd1 && !busy) begin
                    busy <= 1'b1; ph <= 2'd0; rx <= 32'd0;
                    sh   <= bus_dat_w << {~nm1, 3'b000};  // the first byte to [31:24]
                    left <= {nm1, 3'b111} + 6'd1;          // 8 * N
                end
            end
            if (busy) begin
                ph <= ph + 1'b1;
                case (ph)
                    2'd1: begin sck <= 1'b1; rx <= {rx[30:0], miso}; end  // rising edge: sample
                    2'd3: begin
                        sck <= 1'b0; sh <= sh << 1; left <= left - 1'b1;  // falling edge: next bit
                        if (left == 6'd1) busy <= 1'b0;
                    end
                    default: ;
                endcase
            end
        end
    end
endmodule
