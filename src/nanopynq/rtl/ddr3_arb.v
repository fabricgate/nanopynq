// Two masters and the refresh onto e-karge's ddr3_ctrl (src/nanopynq/rtl/ddr3/ddr3_ctrl.sv), which takes one
// request at a time: a one-clock pulse on rd, wr or refresh while busy is low. The pulses come from registers, and
// none is sent in the clock right after one (busy rises only then), so a request is never sent twice.
// Master a has priority over b (a master a that never lets go of valid starves b); a master's request is taken when
// its valid and ready are both high at a clock edge.
// A read's data comes back on data_ready; the master that sent the last read gets it (the controller finishes one
// access before it takes the next). A refresh is due every REFRESH_CYCLES clocks (tREFI, 7.8 us) and goes before
// the masters; an access in flight delays it by at most one access. Nothing is sent while ready (calibration done and passed) is low.
// Addresses are 32-bit word addresses {bank, row, column}: 28 bits for the Tang Mega 138K Pro's 1 GiB.
// Master a moves one word per access. Master b moves the 8 words of an aligned BL8 burst (the low 3 bits of b_addr
// are not used): b_wdata / b_rd_data hold word j in bits 32*j +: 32, b_wmask bit 4*j + l enables byte l of word j
// (1 = write). To write one word, enable only its 4 bits; a read gives the whole burst.
module ddr3_arb #(
    parameter REFRESH_CYCLES = 390  // 7.8 us at 50 MHz
) (
    input             clk,
    input             rst,
    input             ready,
    // master a (priority)
    input             a_valid,
    output            a_ready,
    input             a_write,
    input      [27:0] a_addr,
    input      [31:0] a_wdata,
    input      [3:0]  a_wmask,
    output            a_rd_valid,
    output     [31:0] a_rd_data,
    // master b
    input             b_valid,
    output            b_ready,
    input             b_write,
    input      [27:0]  b_addr,
    input      [255:0] b_wdata,
    input      [31:0]  b_wmask,
    output             b_rd_valid,
    output     [255:0] b_rd_data,
    // to ddr3_ctrl
    output reg        rd = 1'b0,
    output reg        wr = 1'b0,
    output reg        refresh = 1'b0,
    output reg [27:0] addr = 28'd0,
    output reg [31:0] din = 32'd0,
    output reg [3:0]  be = 4'd0,
    output reg        burst = 1'b0,
    output reg [255:0] din_burst = 256'd0,
    output reg [31:0] be_burst = 32'd0,
    input      [31:0] dout,
    input      [255:0] dout_burst,
    input             data_ready,
    input             busy
);
    localparam CW = $clog2(REFRESH_CYCLES);

    reg [CW-1:0] ref_cnt = {CW{1'b0}};
    reg          ref_due = 1'b0;
    reg          owner_b = 1'b0;  // the last read came from b

    // a request can go now: the controller is idle and no pulse went out in the last clock
    wire free  = ready && !busy && !(rd || wr || refresh);
    wire take  = free && !ref_due;
    assign a_ready = take;
    assign b_ready = take && !a_valid;

    assign a_rd_valid = data_ready && !owner_b;
    assign b_rd_valid = data_ready && owner_b;
    assign a_rd_data  = dout;
    assign b_rd_data  = dout_burst;

    always @(posedge clk) begin
        rd      <= 1'b0;
        wr      <= 1'b0;
        refresh <= 1'b0;
        if (rst) begin
            ref_cnt <= {CW{1'b0}};
            ref_due <= 1'b0;
            owner_b <= 1'b0;
        end else begin
            if (ref_cnt == REFRESH_CYCLES - 1) begin
                ref_cnt <= {CW{1'b0}};
                ref_due <= 1'b1;
            end else begin
                ref_cnt <= ref_cnt + 1'b1;
            end
            if (free && ref_due) begin
                refresh <= 1'b1;
                ref_due <= 1'b0;
            end else if (take && (a_valid || b_valid)) begin
                rd   <= a_valid ? !a_write : !b_write;
                wr   <= a_valid ? a_write : b_write;
                addr <= a_valid ? a_addr : b_addr;
                din  <= a_wdata;
                be   <= a_wmask;
                burst <= !a_valid && b_write;
                din_burst <= b_wdata;
                be_burst  <= b_wmask;
                if (a_valid ? !a_write : !b_write) owner_b <= !a_valid;
            end
        end
    end
endmodule
