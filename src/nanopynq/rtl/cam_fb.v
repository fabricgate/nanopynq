// Camera frame buffer in the HyperRAM, for fb_display (reports/report_4k_peripherals.md 3.6, 3.7).
// Camera side (wclk = PCLK): the kept bytes of dvp_frontend's write port fill one W-byte line at a time
// into a BSRAM half (128 32-bit entries, pixel x in byte x%4; line k in half k[0]); each full line toggles
// line_t with its number. Line breaks come from the byte count since wstart, not from HREF.
// clk side: one job at a time on hyperram_ctrl, a job being one line = W/16 bursts of 8 words:
//   - display read (first): on a request from fb_display, read that line of the displayed buffer into
//     the display's line buffer (lb_*, entry {line[0], x/4}). The line-0 request switches the displayed
//     buffer to the last completed one. Nothing is read before the first completed frame (the display is black then).
//   - camera write: line 0 picks the buffer to write, one that is neither the completed nor the
//     displayed one (3 buffers, so the picture never tears). At the frame end the frame becomes the
//     completed one if it had W*H bytes and all H lines were written, else BAD counts it.
// Lines that arrive before the first line 0 after enable, or after a disable, are dropped silently.
// Buffers are STRIDE words apart; every burst starts at a multiple of 8 words (no 512-word boundary).
// Byte addresses from BASE:
//   +0x00 CTRL    (rw): [0] enable camera writes
//   +0x04 FRAMES  (ro): frames completed
//   +0x08 BAD     (ro): frames dropped (wrong byte count, line overrun)
//   +0x0C HFRAMES (ro): display frames (frame_t toggles from fb_display)
//   +0x10 STATUS  (ro): [1:0] completed buffer, [3:2] displayed buffer, [5:4] buffer being written,
//                       [8] a frame has been completed
module cam_fb #(
    parameter BASE   = 32'h0000_6000,
    parameter W      = 320,     // bytes per line, a multiple of 16, at most 512
    parameter H      = 240,     // lines, at most 255
    parameter STRIDE = 65536    // words between buffers, at least W*H/2
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
    // camera (wclk domain)
    input             wclk,
    input             wstart,
    input             wvalid,
    input      [7:0]  wdata,
    input             wend,
    // hyperram_ctrl
    output reg        cmd_valid = 1'b0,
    input             cmd_ready,
    output reg        cmd_write = 1'b0,
    output reg [21:0] cmd_addr = 22'd0,
    output     [3:0]  cmd_len,
    input             wd_ready,
    output     [15:0] wd_data,
    input             rd_valid,
    input      [15:0] rd_data,
    input             done,
    // fb_display
    input             req_t,
    input      [7:0]  req_line,
    input             frame_t,
    output reg        lb_we = 1'b0,
    output reg [7:0]  lb_addr = 8'd0,
    output reg [31:0] lb_data = 32'd0,
    output reg        have_frame = 1'b0
);
    localparam BPL = W / 16;  // bursts per line
    localparam WPL = W / 2;   // words per line
    assign cmd_len = 4'd8;

    // ---------------- camera side (wclk) ----------------
    reg [31:0] cam_mem [0:255];
    reg [23:0] acc = 24'd0;
    reg [1:0]  bsel = 2'd0;
    reg [6:0]  eidx = 7'd0;
    reg [8:0]  lbytes = 9'd0;
    reg [7:0]  line_cnt = 8'd0, line_no = 8'd0;
    reg [16:0] bcnt = 17'd0, fcount = 17'd0;
    reg        line_t = 1'b0, fend_t = 1'b0;
    always @(posedge wclk) begin
        if (wstart) begin
            bcnt <= 17'd0; lbytes <= 9'd0; bsel <= 2'd0; eidx <= 7'd0; line_cnt <= 8'd0;
        end else if (wvalid) begin
            bcnt <= bcnt + 1'b1;
            bsel <= bsel + 1'b1;
            case (bsel)
                2'd0: acc[7:0]   <= wdata;
                2'd1: acc[15:8]  <= wdata;
                2'd2: acc[23:16] <= wdata;
                default: begin cam_mem[{line_cnt[0], eidx}] <= {wdata, acc}; eidx <= eidx + 1'b1; end
            endcase
            if (lbytes == W - 1) begin
                lbytes <= 9'd0; eidx <= 7'd0; line_no <= line_cnt; line_cnt <= line_cnt + 1'b1;
                line_t <= ~line_t;
            end else lbytes <= lbytes + 1'b1;
        end
        if (wend) begin fcount <= bcnt; fend_t <= ~fend_t; end
    end

    // ---------------- clk side ----------------
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 5);

    reg        en = 1'b0;
    reg [31:0] frames = 32'd0, bad = 32'd0, hframes = 32'd0;
    reg [1:0]  completed = 2'd0, displayed = 2'd0, writing = 2'd0;
    reg [2:0]  line_s = 3'd0, fend_s = 3'd0, req_s = 3'd0, ft_s = 3'd0;
    reg        wpend = 1'b0, fpend = 1'b0, rpend = 1'b0, infr = 1'b0, fbad = 1'b0;
    reg [7:0]  wline = 8'd0, rline = 8'd0, lines_done = 8'd0;

    // jobs
    localparam S_IDLE = 2'd0, S_PREP = 2'd1, S_CMD = 2'd2, S_XFER = 2'd3;
    reg [1:0]  st = S_IDLE;
    reg        jw = 1'b0, wsel = 1'b0, rsel = 1'b0;
    reg [7:0]  jline = 8'd0;
    reg [1:0]  jbuf = 2'd0;
    reg [4:0]  k = 5'd0;
    reg [7:0]  cam_ra = 8'd0;
    reg [6:0]  lb_idx = 7'd0;
    reg [15:0] lo16 = 16'd0;
    reg [31:0] cam_q = 32'd0;
    always @(posedge clk) cam_q <= cam_mem[cam_ra];
    assign wd_data = wsel ? cam_q[31:16] : cam_q[15:0];

    // a buffer that is neither completed nor displayed (with nothing completed yet, both read 0)
    wire [1:0] free_buf = (completed != 2'd0 && displayed != 2'd0) ? 2'd0 :
                          (completed != 2'd1 && displayed != 2'd1) ? 2'd1 : 2'd2;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[2:0])
            3'd0:    bus_dat_r <= {31'd0, en};
            3'd1:    bus_dat_r <= frames;
            3'd2:    bus_dat_r <= bad;
            3'd3:    bus_dat_r <= hframes;
            default: bus_dat_r <= {23'd0, have_frame, 2'd0, writing, displayed, completed};
        endcase

        line_s <= {line_s[1:0], line_t};
        fend_s <= {fend_s[1:0], fend_t};
        req_s  <= {req_s[1:0], req_t};
        ft_s   <= {ft_s[1:0], frame_t};
        lb_we  <= 1'b0;

        if (rst) begin
            en <= 1'b0; frames <= 32'd0; bad <= 32'd0; hframes <= 32'd0; have_frame <= 1'b0;
            completed <= 2'd0; displayed <= 2'd0; writing <= 2'd0;
            wpend <= 1'b0; fpend <= 1'b0; rpend <= 1'b0; infr <= 1'b0; st <= S_IDLE; cmd_valid <= 1'b0;
        end else begin
            if (bus_stb && bus_we && hit && !bus_ack && rel[2:0] == 3'd0) begin
                en <= bus_dat_w[0];
                if (!bus_dat_w[0]) infr <= 1'b0;
            end
            if (ft_s[2] ^ ft_s[1]) hframes <= hframes + 1'b1;
            if (req_s[2] ^ req_s[1]) begin rpend <= 1'b1; rline <= req_line; end
            if (line_s[2] ^ line_s[1]) begin
                if (wpend) fbad <= 1'b1;  // the previous line was not taken yet
                wpend <= 1'b1; wline <= line_no;
            end
            if (fend_s[2] ^ fend_s[1]) fpend <= 1'b1;

            case (st)
                S_IDLE:
                    if (rpend) begin
                        rpend <= 1'b0;
                        if (have_frame) begin
                            jw <= 1'b0; jline <= rline; k <= 5'd0; lb_idx <= 7'd0; rsel <= 1'b0;
                            jbuf <= (rline == 8'd0) ? completed : displayed;
                            if (rline == 8'd0) displayed <= completed;
                            st <= S_CMD;
                        end
                    end else if (wpend) begin
                        wpend <= 1'b0;
                        if (en && wline == 8'd0) begin
                            infr <= 1'b1; fbad <= 1'b0; lines_done <= 8'd0; writing <= free_buf;
                            jw <= 1'b1; jline <= 8'd0; jbuf <= free_buf; k <= 5'd0; st <= S_PREP;
                        end else if (en && infr && wline < H) begin
                            jw <= 1'b1; jline <= wline; jbuf <= writing; k <= 5'd0; st <= S_PREP;
                        end else if (en && infr) fbad <= 1'b1;  // more than H lines
                    end else if (fpend) begin
                        fpend <= 1'b0;
                        if (en && infr) begin
                            if (!fbad && fcount == W * H && lines_done == H) begin
                                completed <= writing; have_frame <= 1'b1; frames <= frames + 1'b1;
                            end else bad <= bad + 1'b1;
                        end
                        infr <= 1'b0;
                    end
                S_PREP: begin  // cam_q needs a clock after cam_ra
                    cam_ra <= {jline[0], k, 2'b00}; wsel <= 1'b0; st <= S_CMD;
                end
                S_CMD: begin
                    cmd_valid <= 1'b1; cmd_write <= jw;
                    cmd_addr  <= jbuf * STRIDE + jline * WPL + {k, 3'b000};
                    if (cmd_valid && cmd_ready) begin cmd_valid <= 1'b0; st <= S_XFER; end
                end
                S_XFER: begin
                    if (wd_ready) begin
                        wsel <= ~wsel;
                        if (wsel) cam_ra <= cam_ra + 1'b1;
                    end
                    if (rd_valid) begin
                        rsel <= ~rsel;
                        if (!rsel) lo16 <= rd_data;
                        else begin
                            lb_we <= 1'b1; lb_addr <= {jline[0], lb_idx}; lb_data <= {rd_data, lo16};
                            lb_idx <= lb_idx + 1'b1;
                        end
                    end
                    if (done) begin
                        if (k == BPL - 1) begin
                            if (jw) lines_done <= lines_done + 1'b1;
                            st <= S_IDLE;
                        end else begin
                            k <= k + 1'b1;
                            st <= jw ? S_PREP : S_CMD;
                        end
                    end
                end
            endcase
        end
    end
endmodule
