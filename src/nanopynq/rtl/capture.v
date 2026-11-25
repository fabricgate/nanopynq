// Frame capture buffer: takes one whole frame from a byte write port into block RAM, read through a
// window. Usable by any source with the same write port (DVP camera, ADC, logic analyser).
// Byte addresses from BASE:
//   +0x0    CTRL (wo): [0] arm (capture the next whole frame: from the next wstart to wend)
//   +0x4    STATUS (ro): [0] armed (not finished yet), [1] done, [2] overflow
//   +0x8    LENGTH (ro): bytes captured (stops at the capacity on overflow)
//   +0xC    CAPACITY (ro): DEPTH * 4 bytes
//   +0x8000 window: word i holds bytes 4i..4i+3 (byte 0 in [7:0]); reading does not change it
// Write port (wclk domain): wstart / wend 1-clock pulses, wvalid / wdata per byte.
// arm crosses to wclk and done back to clk as toggles through 2 flip-flops; LENGTH and overflow are
// stable from before done toggles until the next arm. Bytes are packed into 32-bit words so the RAM
// is 32 bits wide on both ports. The window reads the RAM synchronously with bus_adr as the address,
// so the data is there in the ack cycle.
module capture #(
    parameter BASE  = 32'h0001_0000,
    parameter DEPTH = 5120
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output     [31:0] bus_dat_r,
    output reg        bus_ack,
    output            hit,
    input             wclk,
    input             wstart,
    input             wvalid,
    input      [7:0]  wdata,
    input             wend
);
    localparam AW = $clog2(DEPTH);
    localparam [29:0] RBASE = BASE[31:2], WBASE = RBASE + 30'h2000;  // registers, window (+0x8000)

    wire reg_hit = (bus_adr >= RBASE) && (bus_adr < RBASE + 30'd4);
    wire win_hit = (bus_adr >= WBASE) && (bus_adr < WBASE + DEPTH);
    assign hit = reg_hit || win_hit;

    reg [31:0] mem [0:DEPTH-1];
    reg [31:0] mem_q;
    reg [31:0] reg_q = 32'd0;
    reg        win_q = 1'b0;
    assign bus_dat_r = win_q ? mem_q : reg_q;

    // clk domain
    reg        arm_t = 1'b0, armed = 1'b0, done = 1'b0, ovf_c = 1'b0;
    reg [2:0]  done_s = 3'd0;
    reg [31:0] len_c = 32'd0;
    wire [AW-1:0] widx_r = bus_adr - WBASE;
    // wclk domain
    reg [2:0]  arm_s = 3'd0;
    reg        pending = 1'b0, active = 1'b0, ovf_w = 1'b0, done_t = 1'b0;
    reg [31:0] count = 32'd0, len_w = 32'd0;
    reg [23:0] pack = 24'd0;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        mem_q   <= mem[widx_r];
        win_q   <= win_hit;
        case (bus_adr - RBASE)
            30'd1:   reg_q <= reg_hit ? {29'd0, ovf_c, done, armed} : 32'd0;
            30'd2:   reg_q <= reg_hit ? len_c : 32'd0;
            30'd3:   reg_q <= reg_hit ? DEPTH * 4 : 32'd0;
            default: reg_q <= 32'd0;
        endcase
        done_s <= {done_s[1:0], done_t};
        if (rst) begin
            armed <= 1'b0; done <= 1'b0;
        end else if (reg_hit && bus_adr == RBASE && bus_stb && bus_we && !bus_ack && bus_dat_w[0]) begin
            arm_t <= ~arm_t; armed <= 1'b1; done <= 1'b0;
        end else if (done_s[2] ^ done_s[1]) begin
            armed <= 1'b0; done <= 1'b1; len_c <= len_w; ovf_c <= ovf_w;
        end
    end

    always @(posedge wclk) begin
        arm_s <= {arm_s[1:0], arm_t};
        if (arm_s[2] ^ arm_s[1]) pending <= 1'b1;
        if (wstart && (pending || (arm_s[2] ^ arm_s[1]))) begin
            pending <= 1'b0; active <= 1'b1; count <= 32'd0; ovf_w <= 1'b0;
        end else if (active && wend) begin
            if (count[1:0] != 2'd0 && !ovf_w) mem[count[AW+1:2]] <= {8'd0, pack};
            active <= 1'b0; len_w <= count; done_t <= ~done_t;
        end else if (active && wvalid) begin
            if (count == DEPTH * 4) begin
                ovf_w <= 1'b1;
            end else begin
                case (count[1:0])
                    2'd0: pack[7:0]   <= wdata;
                    2'd1: pack[15:8]  <= wdata;
                    2'd2: pack[23:16] <= wdata;
                    2'd3: mem[count[AW+1:2]] <= {wdata, pack};
                endcase
                count <= count + 1'b1;
            end
        end
    end
endmodule
