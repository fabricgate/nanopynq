// HyperBus controller for the GW1NSR-4C's SiP HyperRAM: one command = one CS# low transaction of 1..MAXW
// 16-bit words, linear burst, memory space. Timing as measured with tools/p0/psram4k/hram_probe.v
// (reports/report_p0_psram4k.md): CK = clk / 4 (6.75 MHz at 27 MHz); every half CK period is 2 clocks,
// "drive DQ/RWDS, then toggle CK". The CA goes out on half cycles 0-5. Writes put word j on half cycles
// 6 + 2*WLAT + 2j and +1 (first byte = [15:8]) with RWDS driven low (written). Reads take a byte at
// every RWDS transition seen after RWDS was low (edge-aligned data, sampled 74 ns after the edge), so
// the read latency need not be known; a read that does not get its bytes gives up after 26 CK cycles.
// The transaction ends half a cycle after the last edge (CS# hold), and CS# stays high at least 2 clocks
// before the next one. CS# low time: CA 3 + WLAT 13 + 8 words = 24 CK cycles (3.6 us) for an 8-word
// write, under tCSM (4 us); an 8-word read is 25 CK cycles with the read latency of 14 seen in P0.
// Command port: cmd_* is taken when cmd_valid and cmd_ready are both high at a clock edge.
// Write data: wd_data must hold word j in the clock where wd_ready is high (the controller takes it at
// that edge); the next word is needed 4 clocks later. Read data: rd_valid for one clock per word.
// done: one clock at the end of every transaction.
module hyperram_ctrl #(
    parameter WLAT = 13,
    parameter MAXW = 8
) (
    input             clk,
    input             rst,
    input             cmd_valid,
    output            cmd_ready,
    input             cmd_write,
    input      [21:0] cmd_addr,
    input      [3:0]  cmd_len,
    output            wd_ready,
    input      [15:0] wd_data,
    output reg        rd_valid = 1'b0,
    output reg [15:0] rd_data = 16'd0,
    output reg        done = 1'b0,
    output reg        ck = 1'b0,
    output reg        cs_n = 1'b1,
    output reg [7:0]  dq_o = 8'd0,
    output reg        dq_oe = 1'b0,
    input      [7:0]  dq_i,
    output reg        rwds_o = 1'b0,
    output reg        rwds_oe = 1'b0,
    input             rwds_i
);
    localparam [6:0] WS = 7'd6 + 2 * WLAT;  // first half cycle of write data
    localparam [6:0] RMAX = 7'd52;          // a read gives up here (26 CK cycles, 3.85 us)

    reg        busy = 1'b0, active = 1'b0, is_wr = 1'b0, phase = 1'b0, seen_low = 1'b0, prev = 1'b0, half = 1'b0;
    reg [47:0] ca = 48'd0;
    reg [6:0]  k = 7'd0;      // half cycle
    reg [6:0]  wend = 7'd0;   // write: first half cycle after the data
    reg [3:0]  left = 4'd0;   // read: words still to come
    reg [7:0]  lo = 8'd0;

    assign cmd_ready = !busy;
    assign wd_ready  = active && is_wr && !phase && k >= WS && k < wend && !k[0];

    always @(posedge clk) begin
        rd_valid <= 1'b0;
        done     <= 1'b0;
        if (rst) begin
            busy <= 1'b0; active <= 1'b0; cs_n <= 1'b1; ck <= 1'b0; dq_oe <= 1'b0; rwds_oe <= 1'b0;
        end else if (!busy) begin
            if (cmd_valid) begin
                busy <= 1'b1; active <= 1'b1; is_wr <= cmd_write; cs_n <= 1'b0;
                ca <= {!cmd_write, 1'b0, 1'b1, 10'd0, cmd_addr[21:3], 13'd0, cmd_addr[2:0]};
                wend <= WS + {2'd0, cmd_len, 1'b0};
                left <= cmd_len;
                k <= 7'd0; phase <= 1'b0; seen_low <= 1'b0; prev <= 1'b0; half <= 1'b0;
            end
        end else if (!active) begin
            busy <= 1'b0;                            // CS# high for this clock and the next at least
        end else begin
            phase <= ~phase;
            if (!phase) begin                        // drive for half cycle k
                if (k < 7'd6) begin
                    dq_oe <= 1'b1; dq_o <= ca[47:40]; ca <= {ca[39:0], 8'd0}; rwds_oe <= 1'b0;
                end else if (is_wr && k >= WS && k < wend) begin
                    dq_oe <= 1'b1; rwds_oe <= 1'b1; rwds_o <= 1'b0;  // RWDS low: byte written
                    if (!k[0]) begin
                        dq_o <= wd_data[15:8]; lo <= wd_data[7:0];
                    end else begin
                        dq_o <= lo;
                    end
                end else begin
                    dq_oe <= 1'b0; rwds_oe <= 1'b0;
                end
            end else if ((is_wr && k == wend) || (!is_wr && (left == 4'd0 || k == RMAX))) begin
                active <= 1'b0; done <= 1'b1;        // no further CK edge
                cs_n <= 1'b1; ck <= 1'b0; dq_oe <= 1'b0; rwds_oe <= 1'b0;
            end else begin                           // sample what the last edge left, then toggle CK
                if (!is_wr && k >= 7'd6) begin
                    if (!rwds_i) seen_low <= 1'b1;
                    if (seen_low && rwds_i != prev) begin
                        half <= ~half;
                        if (!half) begin
                            lo <= dq_i;
                        end else begin
                            rd_data <= {lo, dq_i}; rd_valid <= 1'b1; left <= left - 1'b1;
                        end
                    end
                    prev <= rwds_i;
                end
                ck <= ~ck;
                k  <= k + 1'b1;
            end
        end
    end
endmodule
