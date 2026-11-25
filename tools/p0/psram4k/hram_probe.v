// P0 spike: one HyperBus transaction at a time on the GW1NSR-4C's embedded HyperRAM, slow and simple.
// CK = clk / 4 (6.75 MHz at 27 MHz); every half CK period is 2 clocks: drive DQ/RWDS, then toggle CK.
// Byte addresses from BASE:
//   +0x00 CA_HI (rw): CA[47:16]           +0x04 CA_LO (rw): CA[15:0]
//   +0x08 WDATA (rw): [15:0] word to write (first byte = [15:8])
//   +0x0C CTRL (wo): [0] start, [1] 1 = write / 0 = read, [7:4] write latency in CK cycles after CA,
//                    [15:8] CK cycles a read may run (stops early after two bytes); ignored while busy
//   +0x10 STATUS (ro): [0] busy, [1] read got two bytes, [31:16] read word
//   +0x40 + 4*i (ro): LOG[i], i < 32: {RWDS, DQ} sampled in half cycle 6 + i (just before its CK edge)
// Reads capture a byte at every RWDS transition seen after RWDS was low (edge-aligned data; with CK
// this slow the sample 74 ns after the edge is well inside the data valid window), so the read
// latency need not be known. Writes put the data at half cycles 6 + 2L and 7 + 2L, RWDS driven low;
// the transaction ends half a cycle after the last edge without another edge (CS# hold).
// Transactions here stay far below tCSM (4 us): a read of 20 CK cycles is 3 us.
// Throwaway; not part of the package.
module hram_probe #(
    parameter BASE = 32'h0000_5000
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
    output reg        ck = 1'b0,
    output reg        cs_n = 1'b1,
    output reg [7:0]  dq_o = 8'd0,
    output reg        dq_oe = 1'b0,
    input      [7:0]  dq_i,
    output reg        rwds_o = 1'b0,
    output reg        rwds_oe = 1'b0,
    input             rwds_i
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    wire [29:0] lidx = rel - 30'd16;
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 30'd48);

    reg [31:0] ca_hi = 32'd0;
    reg [15:0] ca_lo = 16'd0, wdata = 16'd0, rword = 16'd0;
    reg        busy = 1'b0, is_wr = 1'b0, got2 = 1'b0, phase = 1'b0, seen_low = 1'b0, prev = 1'b0;
    reg [3:0]  lat = 4'd0;
    reg [7:0]  maxcyc = 8'd0;
    reg [8:0]  k = 9'd0;            // half cycle
    reg [1:0]  nbytes = 2'd0;
    reg [8:0]  log [0:31];
    wire [47:0] ca = {ca_hi, ca_lo};
    wire [8:0]  wstart = 9'd6 + {lat, 1'b0};
    integer i;
    initial for (i = 0; i < 32; i = i + 1) log[i] = 9'd0;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        case (rel)
            30'd0: bus_dat_r <= hit ? ca_hi : 32'd0;
            30'd1: bus_dat_r <= hit ? {16'd0, ca_lo} : 32'd0;
            30'd2: bus_dat_r <= hit ? {16'd0, wdata} : 32'd0;
            30'd4: bus_dat_r <= hit ? {rword, 14'd0, got2, busy} : 32'd0;
            default: bus_dat_r <= (hit && rel >= 30'd16) ? {23'd0, log[lidx[4:0]]} : 32'd0;
        endcase
        if (hit && bus_stb && bus_we && !bus_ack && !busy) begin
            if (rel == 30'd0) ca_hi <= bus_dat_w;
            if (rel == 30'd1) ca_lo <= bus_dat_w[15:0];
            if (rel == 30'd2) wdata <= bus_dat_w[15:0];
            if (rel == 30'd3 && bus_dat_w[0]) begin
                busy <= 1'b1; is_wr <= bus_dat_w[1]; lat <= bus_dat_w[7:4]; maxcyc <= bus_dat_w[15:8];
                k <= 9'd0; phase <= 1'b0; nbytes <= 2'd0; got2 <= 1'b0; seen_low <= 1'b0;
                cs_n <= 1'b0;
            end
        end
        if (rst) begin
            busy <= 1'b0; cs_n <= 1'b1; ck <= 1'b0; dq_oe <= 1'b0; rwds_oe <= 1'b0;
        end else if (busy) begin
            phase <= ~phase;
            if (!phase) begin                       // drive for half cycle k
                if (k < 9'd6) begin
                    dq_oe <= 1'b1; dq_o <= ca[47 - 8 * k -: 8]; rwds_oe <= 1'b0;
                end else if (is_wr && (k == wstart || k == wstart + 1'b1)) begin
                    dq_oe <= 1'b1; dq_o <= (k == wstart) ? wdata[15:8] : wdata[7:0];
                    rwds_oe <= 1'b1; rwds_o <= 1'b0;   // RWDS low: byte written
                end else begin
                    dq_oe <= 1'b0; rwds_oe <= 1'b0;
                end
            end else if ((is_wr && k == wstart + 9'd2) || (!is_wr && (nbytes == 2'd2 || k == {maxcyc, 1'b0}))) begin
                busy <= 1'b0; cs_n <= 1'b1; ck <= 1'b0; dq_oe <= 1'b0; rwds_oe <= 1'b0;  // no further CK edge
                got2 <= !is_wr && nbytes == 2'd2;
            end else begin                          // sample what the last edge left, then toggle CK
                if (k >= 9'd6) begin
                    if (k < 9'd38) log[k - 9'd6] <= {rwds_i, dq_i};
                    if (!is_wr) begin
                        if (!rwds_i) seen_low <= 1'b1;
                        if (seen_low && rwds_i != prev && nbytes != 2'd2) begin
                            rword  <= {rword[7:0], dq_i};
                            nbytes <= nbytes + 1'b1;
                        end
                        prev <= rwds_i;
                    end
                end
                ck <= ~ck;
                k  <= k + 1'b1;
            end
        end
    end
endmodule
