// Controller for the Tang Nano 20K's 64 Mbit SDRAM (in the GW2AR-18 package: 2K rows x 256 cols x 4 banks
// x 32 bit). One command at a time, one 32-bit word each: ACTIVE, then READ or WRITE with auto precharge
// (burst length 1, CAS latency 2). The SDRAM clock is ~clk, so the SDRAM takes every command half a clock
// after the controller drives it. Timing limits (plan's Global Constraints) are turned into clocks of
// CLK_HZ, rounded up, at least 1. After reset: NOP for 200 us, PRECHARGE ALL, REFRESH twice, MODE
// REGISTER SET, tMRD. A REFRESH goes out every 15 us (the limit is 15.6 us), after the access in progress.
// Command port: cmd_* is taken when cmd_valid and cmd_ready are both high at a clock edge. cmd_ready is
// high only when initialised, idle and no refresh is due; it does not depend on cmd_*.
// cmd_addr = {bank[1:0], row[10:0], col[7:0]}; cmd_wmask bit j = 1 writes byte j (DQM is its inverse).
// Read data: dq_i is taken at the clock edge rd_lat clocks after the one that drove the READ, and
// rd_valid is high for the clock after it, always before cmd_ready is high again.
module sdram_ctrl #(parameter CLK_HZ = 27_000_000) (
    input             clk,
    input             rst,
    input      [2:0]  rd_lat,
    input             cmd_valid,
    output            cmd_ready,
    input             cmd_write,
    input      [20:0] cmd_addr,
    input      [31:0] cmd_wdata,
    input      [3:0]  cmd_wmask,
    output reg        rd_valid = 1'b0,
    output reg [31:0] rd_data = 32'd0,
    output reg        init_done = 1'b0,
    output            sdram_clk,
    output            sdram_cke,
    output            sdram_cs_n,
    output            sdram_ras_n,
    output            sdram_cas_n,
    output            sdram_we_n,
    output reg [1:0]  sdram_ba = 2'd0,
    output reg [10:0] sdram_a = 11'd0,
    output reg [3:0]  sdram_dqm = 4'd0,
    output reg [31:0] dq_o = 32'd0,
    output reg        dq_oe = 1'b0,
    input      [31:0] dq_i
);
    function integer ns2clk(input integer ns);  // ceil(ns * CLK_HZ / 1e9), at least 1 (kHz keeps it in 32 bits)
        begin
            ns2clk = (ns * (CLK_HZ / 1000) + 999_999) / 1_000_000;
            if (ns2clk < 1) ns2clk = 1;
        end
    endfunction
    function integer max(input integer a, input integer b);
        max = a > b ? a : b;
    endfunction

    localparam integer T_RP = ns2clk(18), T_RCD = ns2clk(18), T_RC = ns2clk(60), T_RAS = ns2clk(42);
    localparam integer T_WR = max(ns2clk(12), 2), T_MRD = 2;  // write recovery: ESMT parts give tRDL = 2 CLK
    localparam integer T_INIT = (CLK_HZ / 1000) * 200 / 1000 + 1;  // 200 us and a clock of margin
    localparam integer T_REFI = (CLK_HZ / 1000) * 15 / 1000;       // 15 us, rounded down
    // ACTIVE to READ/WRITE: tRCD, and late enough that auto precharge (1 clock after a READ, tWR after a
    // WRITE) does not start before tRAS.
    localparam integer W_RW = max(T_RCD, T_RAS - 1);
    // READ/WRITE to the next ACTIVE or REFRESH: tRP after auto precharge starts, and tRC after the ACTIVE.
    localparam integer R_POST = max(1 + T_RP, T_RC - W_RW);
    localparam integer W_POST = max(T_WR + T_RP, T_RC - W_RW);
    localparam [10:0] MODE = 11'b000_0_010_0_000;  // burst write, CAS 2, sequential, burst length 1

    localparam [3:0] C_MRS = 4'b0000, C_REF = 4'b0001, C_PRE = 4'b0010, C_ACT = 4'b0011,
                     C_WR = 4'b0100, C_RD = 4'b0101, C_NOP = 4'b0111;  // {cs_n, ras_n, cas_n, we_n}
    localparam [2:0] S_INIT = 3'd0, S_REF1 = 3'd1, S_REF2 = 3'd2, S_MRS = 3'd3, S_IDLE = 3'd4, S_RW = 3'd5;

    reg [3:0]  cmd = C_NOP;
    reg [2:0]  state = S_INIT;
    reg [15:0] cnt = T_INIT;   // clocks of NOP before the state's next command
    reg [15:0] ref_cnt = 16'd0;
    reg [2:0]  rd_left = 3'd0; // clocks until dq_i is taken
    reg        wr = 1'b0;
    reg [7:0]  col = 8'd0;
    reg [31:0] wdata = 32'd0;
    reg [3:0]  wmask = 4'd0;

    wire       ref_due = ref_cnt >= T_REFI;

    assign cmd_ready = init_done && state == S_IDLE && cnt == 16'd0 && !ref_due;
    assign sdram_clk = ~clk;
    assign sdram_cke = 1'b1;
    assign {sdram_cs_n, sdram_ras_n, sdram_cas_n, sdram_we_n} = cmd;

    always @(posedge clk) begin
        cmd <= C_NOP;
        dq_oe <= 1'b0;
        sdram_dqm <= 4'd0;
        rd_valid <= 1'b0;
        ref_cnt <= ref_cnt + 16'd1;
        if (state == S_IDLE) init_done <= 1'b1;  // MRS is out; cmd_ready also waits for tMRD (cnt)
        if (rd_left != 3'd0) begin
            rd_left <= rd_left - 3'd1;
            if (rd_left == 3'd1) begin
                rd_data <= dq_i;
                rd_valid <= 1'b1;
            end
        end
        if (rst) begin
            state <= S_INIT; cnt <= T_INIT; init_done <= 1'b0; rd_left <= 3'd0;
        end else if (cnt != 16'd0) begin
            cnt <= cnt - 16'd1;
        end else begin
            case (state)
                S_INIT: begin
                    cmd <= C_PRE; sdram_a <= 11'h400;  // A10: all banks
                    cnt <= T_RP - 1; state <= S_REF1;
                end
                S_REF1: begin
                    cmd <= C_REF; cnt <= T_RC - 1; state <= S_REF2;
                end
                S_REF2: begin
                    cmd <= C_REF; ref_cnt <= 16'd0; cnt <= T_RC - 1; state <= S_MRS;
                end
                S_MRS: begin
                    cmd <= C_MRS; sdram_ba <= 2'd0; sdram_a <= MODE;
                    cnt <= T_MRD - 1; state <= S_IDLE;
                end
                S_IDLE: begin
                    if (ref_due) begin
                        cmd <= C_REF; ref_cnt <= 16'd0; cnt <= T_RC - 1;
                    end else if (cmd_valid) begin
                        cmd <= C_ACT; sdram_ba <= cmd_addr[20:19]; sdram_a <= cmd_addr[18:8];
                        wr <= cmd_write; col <= cmd_addr[7:0]; wdata <= cmd_wdata; wmask <= cmd_wmask;
                        cnt <= W_RW - 1; state <= S_RW;
                    end
                end
                default: begin  // S_RW
                    sdram_a <= {3'b100, col};  // A10: auto precharge
                    state <= S_IDLE;
                    if (wr) begin
                        cmd <= C_WR; dq_o <= wdata; dq_oe <= 1'b1; sdram_dqm <= ~wmask;
                        cnt <= W_POST - 1;
                    end else begin
                        cmd <= C_RD; rd_left <= rd_lat;
                        if (rd_lat == 3'd0) begin
                            rd_data <= dq_i;
                            rd_valid <= 1'b1;
                        end
                        cnt <= rd_lat + 1 > R_POST - 1 ? rd_lat + 1 : R_POST - 1;
                    end
                end
            endcase
        end
    end
endmodule
