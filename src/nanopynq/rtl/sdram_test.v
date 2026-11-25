// SDRAM self-test engine (master b of sdram_arb) with its control registers. A pass writes LENGTH words from
// word address START, then reads them back and compares; PASSES passes run back to back. One command is in
// flight at a time. Byte addresses from BASE (the bus is acked one clock after every strobe it sees, reads
// give 0 unless hit):
//   +0x00 CTRL           (wo): [0] start (takes START/LENGTH/PASSES, clears ERRORS and FIRST_ERR_*),
//                              [1] stop, [2] with [0]: write one word per pass inverted (START + LENGTH/2)
//   +0x04 STATUS         (ro): [0] running, [31:16] passes completed
//   +0x08 PASSES         (rw): passes to run (default 1)
//   +0x0C START          (rw): first word address [20:0] (default 0)
//   +0x10 LENGTH         (rw): words per pass [21:0] (default 0x20_0000 = 8 MB)
//   +0x14 ERRORS         (ro): mismatching words (saturates)
//   +0x18 FIRST_ERR_ADDR (ro): [31] valid, [20:0] word address of the first mismatch
//   +0x1C FIRST_ERR_DATA (ro): value read back
//   +0x20 FIRST_ERR_EXP  (ro): value expected
//   +0x24 RD_LAT         (rw): [2:0] read latency for sdram_ctrl (default 2)
// A start is ignored (nothing runs, ERRORS etc. are kept) if PASSES = 0, LENGTH = 0, START + LENGTH > 0x20_0000,
// or a run is active. PASSES is 16 bits: a write of 0x1_0000 stores 0, so a start is then ignored.
// A run continues the value pattern where the previous run ended, so no two runs write the same values.
// Test value of the word at offset i (from START) in pass p:  p*K2 + i*K1  (mod 2^32), K1 and K2 odd.
// K1 odd makes i -> value one to one, so two different addresses in a pass never hold the same value (a
// stuck or shorted address line shows up); K2 odd (and nonzero) makes every word differ from one pass to
// the next. Both are plain running sums, no multiplier. Word writes are always all 4 bytes (wmask = F).
module sdram_test #(
    parameter BASE = 32'h0000_3000
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
    output     [2:0]  rd_lat,
    output            m_valid,
    input             m_ready,
    output            m_write,
    output     [20:0] m_addr,
    output     [31:0] m_wdata,
    output     [3:0]  m_wmask,
    input             m_rd_valid,
    input      [31:0] m_rd_data
);
    localparam [31:0] K1 = 32'h9E37_79B1, K2 = 32'h85EB_CA6B;
    localparam [1:0] S_IDLE = 2'd0, S_WR = 2'd1, S_RD = 2'd2, S_WAIT = 2'd3;

    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 10);

    reg [15:0] passes = 16'd1;
    reg [20:0] start_w = 21'd0;
    reg [21:0] length = 22'h20_0000;
    reg [2:0]  lat = 3'd2;
    reg [31:0] errors = 32'd0, e_addr = 32'd0, e_data = 32'd0, e_exp = 32'd0;
    reg [15:0] done = 16'd0;
    reg        run = 1'b0;

    // taken at start
    reg [15:0] t_passes = 16'd0;
    reg [20:0] t_start = 21'd0;
    reg [21:0] t_len = 22'd0;
    reg        t_inj = 1'b0;

    reg [1:0]  state = S_IDLE;
    reg [21:0] idx = 22'd0;     // offset of the current word
    reg [31:0] exp = 32'd0;     // test value of the current word
    reg [31:0] pbase = 32'd0;   // test value of offset 0 in the current pass

    wire last    = idx == t_len - 22'd1;
    wire inject  = t_inj && idx == (t_len >> 1);
    wire [20:0] addr = t_start + idx[20:0];
    wire go      = bus_stb && bus_we && hit && !bus_ack;
    wire fits    = {2'b00, start_w} + {1'b0, length} <= 23'h20_0000;  // the range stays inside the 8 MB
    wire start_c = go && rel[3:0] == 4'd0 && bus_dat_w[0] && !run && passes != 16'd0 && length != 22'd0 && fits;
    wire stop_c  = go && rel[3:0] == 4'd0 && bus_dat_w[1];

    assign m_valid = state == S_WR || state == S_RD;
    assign m_write = state == S_WR;
    assign m_addr  = addr;
    assign m_wdata = inject ? ~exp : exp;
    assign m_wmask = 4'hF;
    assign rd_lat  = lat;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[3:0])
            4'd1:    bus_dat_r <= {done, 15'd0, run};
            4'd2:    bus_dat_r <= {16'd0, passes};
            4'd3:    bus_dat_r <= {11'd0, start_w};
            4'd4:    bus_dat_r <= {10'd0, length};
            4'd5:    bus_dat_r <= errors;
            4'd6:    bus_dat_r <= e_addr;
            4'd7:    bus_dat_r <= e_data;
            4'd8:    bus_dat_r <= e_exp;
            4'd9:    bus_dat_r <= {29'd0, lat};
            default: bus_dat_r <= 32'd0;
        endcase
        if (rst) begin
            passes <= 16'd1; start_w <= 21'd0; length <= 22'h20_0000; lat <= 3'd2;
            errors <= 32'd0; e_addr <= 32'd0; e_data <= 32'd0; e_exp <= 32'd0; done <= 16'd0;
            run <= 1'b0; state <= S_IDLE;
        end else begin
            if (go)
                case (rel[3:0])
                    4'd2: passes <= bus_dat_w[15:0];
                    4'd3: start_w <= bus_dat_w[20:0];
                    4'd4: length <= bus_dat_w[21:0];
                    4'd9: lat <= bus_dat_w[2:0];
                    default: ;
                endcase
            case (state)
                S_IDLE: if (start_c) begin
                    t_passes <= passes; t_start <= start_w; t_len <= length; t_inj <= bus_dat_w[2];
                    errors <= 32'd0; e_addr <= 32'd0; e_data <= 32'd0; e_exp <= 32'd0; done <= 16'd0;
                    idx <= 22'd0; exp <= pbase;  // pbase carries over: a new run does not repeat the last run's values
                    run <= 1'b1; state <= S_WR;
                end
                S_WR: if (m_ready) begin
                    exp <= exp + K1;
                    if (last) begin  // read phase: same values again from offset 0
                        idx <= 22'd0; exp <= pbase; state <= S_RD;
                    end else idx <= idx + 22'd1;
                end
                S_RD: if (m_ready) state <= S_WAIT;
                default: if (m_rd_valid) begin  // S_WAIT
                    if (m_rd_data != exp) begin
                        if (errors != 32'hFFFF_FFFF) errors <= errors + 32'd1;
                        if (!e_addr[31]) begin
                            e_addr <= {1'b1, 10'd0, addr};
                            e_data <= m_rd_data; e_exp <= exp;
                        end
                    end
                    exp <= exp + K1;
                    if (!last) begin
                        idx <= idx + 22'd1; state <= S_RD;
                    end else begin  // pass done
                        done <= done + 16'd1;
                        idx <= 22'd0; pbase <= pbase + K2; exp <= pbase + K2;
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
