// DDR3 self-test engine (master b of ddr3_arb) with its control registers, for the Tang Mega 138K Pro's 1 GiB.
// Adapted from sdram_test.v (the 20K's 8 MB SDRAM): the same registers, passes and test values, 28-bit word
// addresses, and CALIB in place of RD_LAT. A pass writes LENGTH words from word address START, then reads them back
// and compares; PASSES passes run back to back. Every access moves the 8 words of one BL8 burst (master b of
// ddr3_arb); one access is in flight at a time. Byte addresses from BASE (the bus is acked one clock after every
// strobe it sees, reads give 0 unless hit):
//   +0x00 CTRL           (wo): [0] start (takes START/LENGTH/PASSES, clears ERRORS, FIRST_ERR_* and the cycle
//                              counts), [1] stop, [2] with [0]: write one word per pass inverted (START + LENGTH/2)
//   +0x04 STATUS         (ro): [0] running, [31:16] passes completed
//   +0x08 PASSES         (rw): passes to run (default 1)
//   +0x0C START          (rw): first word address [27:0] (default 0), a multiple of 8
//   +0x10 LENGTH         (rw): words per pass [28:0] (default 0x1000_0000 = 1 GiB), a multiple of 8
//   +0x14 ERRORS         (ro): mismatching words (saturates)
//   +0x18 FIRST_ERR_ADDR (ro): [31] valid, [27:0] word address of the first mismatch (the lowest of its burst)
//   +0x1C FIRST_ERR_DATA (ro): value read back
//   +0x20 FIRST_ERR_EXP  (ro): value expected
//   +0x24 CALIB          (ro): [0] init_done, [1] calib_done, [2] calib_fail, [31:8] read delay of byte lanes 0..3
//                              (6 bits each, lane l from bit 8 + 6*l: ddr3_ctrl's phy_rd_delay)
//   +0x28 WR_CYCLES      (ro): clocks spent writing since the start, all passes (saturates)
//   +0x2C RD_CYCLES      (ro): clocks spent reading since the start, all passes (saturates)
// A start is ignored (nothing runs, ERRORS etc. are kept) if calib_done = 0, calib_fail = 1, PASSES = 0, LENGTH = 0,
// START or LENGTH is not a multiple of 8, START + LENGTH > 0x1000_0000, or a run is active. PASSES is 16 bits: a
// write of 0x1_0000 stores 0, so a start is then ignored. A run continues the value pattern where the previous run
// ended, so no two runs write the same values.
// Test value of the word at offset i (from START) in pass p:  p*K2 + i*K1  (mod 2^32), K1 and K2 odd (see
// sdram_test.v). Bursts are always written whole (wmask = all ones).
module ddr3_test #(
    parameter BASE = 32'h0000_3000
) (
    input              clk,
    input              rst,
    input      [29:0]  bus_adr,
    input      [31:0]  bus_dat_w,
    input              bus_we,
    input              bus_stb,
    output reg [31:0]  bus_dat_r = 32'd0,
    output reg         bus_ack = 1'b0,
    output             hit,
    input              init_done,
    input              calib_done,
    input              calib_fail,
    input      [23:0]  rd_delay,
    output             m_valid,
    input              m_ready,
    output             m_write,
    output     [27:0]  m_addr,
    output     [255:0] m_wdata,
    output     [31:0]  m_wmask,
    input              m_rd_valid,
    input      [255:0] m_rd_data
);
    localparam [31:0] K1 = 32'h9E37_79B1, K2 = 32'h85EB_CA6B, K8 = 32'h9E37_79B1 * 8;
    localparam [1:0] S_IDLE = 2'd0, S_WR = 2'd1, S_RD = 2'd2, S_WAIT = 2'd3;
    localparam [28:0] FULL = 29'h1000_0000;  // words in 1 GiB

    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 12);

    reg [15:0] passes = 16'd1;
    reg [27:0] start_w = 28'd0;
    reg [28:0] length = FULL;
    reg [31:0] errors = 32'd0, e_addr = 32'd0, e_data = 32'd0, e_exp = 32'd0;
    reg [31:0] wr_cyc = 32'd0, rd_cyc = 32'd0;
    reg [15:0] done = 16'd0;
    reg        run = 1'b0;

    // taken at start
    reg [15:0] t_passes = 16'd0;
    reg [27:0] t_start = 28'd0;
    reg [28:0] t_len = 29'd0;
    reg        t_inj = 1'b0;

    reg [1:0]  state = S_IDLE;
    reg [28:0] idx = 29'd0;     // offset of the first word of the current burst
    reg [31:0] exp = 32'd0;     // test value of that word
    reg [31:0] pbase = 32'd0;   // test value of offset 0 in the current pass

    wire last    = idx == t_len - 29'd8;
    wire [28:0] inj_at = t_len >> 1;  // the inverted word
    wire inject  = t_inj && idx[28:3] == inj_at[28:3];
    wire [27:0] addr = t_start + idx[27:0];
    wire go      = bus_stb && bus_we && hit && !bus_ack;
    wire fits    = {2'b00, start_w} + {1'b0, length} <= {1'b0, FULL};  // the range stays inside the 1 GiB
    wire start_c = go && rel[3:0] == 4'd0 && bus_dat_w[0] && !run && calib_done && !calib_fail && passes != 16'd0
                   && length != 29'd0 && start_w[2:0] == 3'd0 && length[2:0] == 3'd0 && fits;
    wire stop_c  = go && rel[3:0] == 4'd0 && bus_dat_w[1];

    // the 8 words of the current burst: their test values, what is written, and which read back wrong
    wire [255:0] want;
    wire [7:0]   bad;
    genvar j;
    generate
        for (j = 0; j < 8; j = j + 1) begin : g_word
            wire [31:0] k = K1 * j;
            assign want[32*j +: 32]    = exp + k;
            assign m_wdata[32*j +: 32] = (inject && inj_at[2:0] == j) ? ~want[32*j +: 32] : want[32*j +: 32];
            assign bad[j] = m_rd_data[32*j +: 32] != want[32*j +: 32];
        end
    endgenerate

    reg [3:0] nbad;  // mismatching words of the burst
    reg [2:0] first; // the lowest of them
    integer i;
    always @* begin
        nbad = 4'd0;
        first = 3'd0;
        for (i = 7; i >= 0; i = i - 1) begin
            nbad = nbad + bad[i];
            if (bad[i]) first = i;
        end
    end

    assign m_valid = state == S_WR || state == S_RD;
    assign m_write = state == S_WR;
    assign m_addr  = addr;
    assign m_wmask = 32'hFFFF_FFFF;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[3:0])
            4'd1:    bus_dat_r <= {done, 15'd0, run};
            4'd2:    bus_dat_r <= {16'd0, passes};
            4'd3:    bus_dat_r <= {4'd0, start_w};
            4'd4:    bus_dat_r <= {3'd0, length};
            4'd5:    bus_dat_r <= errors;
            4'd6:    bus_dat_r <= e_addr;
            4'd7:    bus_dat_r <= e_data;
            4'd8:    bus_dat_r <= e_exp;
            4'd9:    bus_dat_r <= {rd_delay, 5'd0, calib_fail, calib_done, init_done};
            4'd10:   bus_dat_r <= wr_cyc;
            4'd11:   bus_dat_r <= rd_cyc;
            default: bus_dat_r <= 32'd0;
        endcase
        if (rst) begin
            passes <= 16'd1; start_w <= 28'd0; length <= FULL;
            errors <= 32'd0; e_addr <= 32'd0; e_data <= 32'd0; e_exp <= 32'd0; done <= 16'd0;
            wr_cyc <= 32'd0; rd_cyc <= 32'd0;
            run <= 1'b0; state <= S_IDLE;
        end else begin
            if (go)
                case (rel[3:0])
                    4'd2: passes <= bus_dat_w[15:0];
                    4'd3: start_w <= bus_dat_w[27:0];
                    4'd4: length <= bus_dat_w[28:0];
                    default: ;
                endcase
            if (state == S_WR && wr_cyc != 32'hFFFF_FFFF) wr_cyc <= wr_cyc + 32'd1;
            if ((state == S_RD || state == S_WAIT) && rd_cyc != 32'hFFFF_FFFF) rd_cyc <= rd_cyc + 32'd1;
            case (state)
                S_IDLE: if (start_c) begin
                    t_passes <= passes; t_start <= start_w; t_len <= length; t_inj <= bus_dat_w[2];
                    errors <= 32'd0; e_addr <= 32'd0; e_data <= 32'd0; e_exp <= 32'd0; done <= 16'd0;
                    wr_cyc <= 32'd0; rd_cyc <= 32'd0;
                    idx <= 29'd0; exp <= pbase;  // pbase carries over: a new run does not repeat the last run's values
                    run <= 1'b1; state <= S_WR;
                end
                S_WR: if (m_ready) begin
                    exp <= exp + K8;
                    if (last) begin  // read phase: same values again from offset 0
                        idx <= 29'd0; exp <= pbase; state <= S_RD;
                    end else idx <= idx + 29'd8;
                end
                S_RD: if (m_ready) state <= S_WAIT;
                default: if (m_rd_valid) begin  // S_WAIT
                    if (nbad != 4'd0) begin
                        errors <= errors > 32'hFFFF_FFFF - nbad ? 32'hFFFF_FFFF : errors + nbad;
                        if (!e_addr[31]) begin
                            e_addr <= {1'b1, 3'd0, addr + first};
                            e_data <= m_rd_data[32*first +: 32]; e_exp <= want[32*first +: 32];
                        end
                    end
                    exp <= exp + K8;
                    if (!last) begin
                        idx <= idx + 29'd8; state <= S_RD;
                    end else begin  // pass done
                        done <= done + 16'd1;
                        idx <= 29'd0; pbase <= pbase + K2; exp <= pbase + K2;
                        if (done + 16'd1 == t_passes) begin
                            run <= 1'b0; state <= S_IDLE;
                        end else state <= S_WR;
                    end
                end
            endcase
            if (stop_c) begin
                run <= 1'b0; state <= S_IDLE; pbase <= pbase + K2;  // the next run starts on a fresh pattern
            end
        end
    end
endmodule
