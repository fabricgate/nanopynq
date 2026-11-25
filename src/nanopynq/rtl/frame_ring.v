// Frame ring in the HyperRAM: whole frames from a byte write port (the same as capture's: DVP camera,
// ADC, logic analyser) go into fixed-size slots, one frame per slot; the host copies a slot piece by
// piece into a window in block RAM and reads it there. Drives hyperram_ctrl's command port.
// Byte addresses from BASE:
//   +0x00 CTRL (wo): [0] on (frames that start from now on are taken), [1] WSEQ, RSEQ, DROPPED and
//         STATUS[1] to 0, and the frame still being written (taken before the ring was turned off) is
//         thrown away, so the next run starts from slot 0 with its own frames
//   +0x04 WSEQ (ro): frames written so far        +0x08 RSEQ (rw): frames the host has read (host writes)
//   +0x0C DROPPED (ro): frames thrown away because the ring was full
//   +0x10 FETCH (wo): [21:0] first 16-bit word, [31:24] how many 8-word units (1..64) to copy into the
//         window; ignored while fetching
//   +0x14 STATUS (ro): [0] fetching, [1] the write FIFO has overflowed (some frame was marked bad),
//         [2] a read of the last FETCH did not get all its words (the window is not to be trusted)
//   +0x18 SLOT_LEN (ro): bytes of the last frame written
//   +0x1C SLOT_INFO (ro): [15:0] 16-bit words per slot, [31:16] slots
//   +0x1000 window: 1 KB; word i holds bytes 4i..4i+3 of what was fetched (byte 0 in [7:0])
// Slot n starts at word n * SLOT_WORDS. Its first 32 bits (bytes 0-3) are a header: [15:0] frame bytes,
// [30:16] WSEQ of the frame (low bits), [31] bad (the FIFO overflowed or the frame did not fit in the
// slot). The frame's bytes follow from byte 4; 16-bit word k holds bytes 2k ([7:0]) and 2k+1 ([15:8]).
// The slot WSEQ mod NSLOTS is written only while WSEQ - RSEQ < NSLOTS; a frame arriving when the ring
// is full is thrown away and counted in DROPPED, so the slot the host is reading (RSEQ mod NSLOTS) is
// never written. WSEQ goes up once the header is written. NSLOTS and SLOT_WORDS are powers of two.
//
// wclk side: bytes are packed 4 to a 32-bit entry (bytes 0-3 = [7:0]..[31:24], so [15:0] and [31:16] are
// two 16-bit words) and go into a FIFO (one BSRAM, both ports 32 bits like capture's; gray-coded entry
// pointers, moved by at most 1 per clock, through 2 flip-flops). A frame's last entry may hold 1 word.
// At the frame end the words and bytes put in and an overflow flag are held and handed to clk with a
// toggle (capture's done); clk
// toggles an ack back once it has finished that frame. A frame that starts before the ack (the previous
// frame not finished yet: cannot happen at camera frame rates) is not taken and counts as dropped, so
// the FIFO only ever holds one frame and clk knows where it ends.
// clk side: takes or throws away a frame when its first entry (or its end) arrives, writes it in 8-word
// bursts from slot word 2, then writes the header. Until the frame end is seen it leaves the newest entry
// alone (it may be the partial last one, its pointer crossing before the end toggle). Writes go before window fetches, which are 4-word
// reads (21 CK cycles each, under tCSM). The window is read synchronously with bus_adr as the address,
// so the data is there in the ack cycle.
module frame_ring #(
    parameter BASE       = 32'h0002_0000,
    parameter SLOT_WORDS = 16384,  // 16-bit words per slot (32 KB)
    parameter NSLOTS     = 256,
    parameter SEQW       = 32,     // WSEQ/RSEQ width; smaller only to reach the wrap in simulation
    parameter FIFO_AW    = 9       // write FIFO of 2^FIFO_AW 32-bit entries (2 KB)
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
    input             wend,
    output reg        cmd_valid = 1'b0,
    input             cmd_ready,
    output reg        cmd_write = 1'b0,
    output reg [21:0] cmd_addr = 22'd0,
    output reg [3:0]  cmd_len = 4'd0,
    input             wd_ready,
    output     [15:0] wd_data,
    input             rd_valid,
    input      [15:0] rd_data,
    input             done
);
    localparam FD = 1 << FIFO_AW;
    localparam SB = $clog2(SLOT_WORDS), NB = $clog2(NSLOTS);
    localparam [23:0] CAP = SLOT_WORDS - 2;          // data words per slot
    localparam [15:0] SW16 = SLOT_WORDS, NS16 = NSLOTS;
    localparam WIN = 256;                            // window: 256 x 32 bits = 64 units of 8 words
    localparam [29:0] RBASE = BASE[31:2], WBASE = RBASE + 30'h400;
    localparam [1:0] S_IDLE = 2'd0, S_RUN = 2'd1, S_HDR = 2'd2;
    localparam [1:0] OP_DATA = 2'd0, OP_HDR = 2'd1, OP_READ = 2'd2;

    function [FIFO_AW:0] g2b(input [FIFO_AW:0] g);
        integer i;
        begin
            g2b[FIFO_AW] = g[FIFO_AW];
            for (i = FIFO_AW - 1; i >= 0; i = i - 1) g2b[i] = g2b[i + 1] ^ g[i];
        end
    endfunction

    wire [29:0] rel = bus_adr - RBASE;
    wire reg_hit = (bus_adr >= RBASE) && (rel < 30'd8);
    wire win_hit = (bus_adr >= WBASE) && (bus_adr < WBASE + WIN);
    assign hit = reg_hit || win_hit;

    reg [31:0] fifo [0:FD-1];
    reg [31:0] win [0:WIN-1];

    // clk-side state the wclk side looks at
    reg en = 1'b0, ack_t = 1'b0;
    reg [FIFO_AW:0] rp = 0, rp_g = 0;

    // ---- wclk side ----
    reg [2:0]  en_w = 3'd0, ack_w = 3'd0;
    reg        active = 1'b0, ovf = 1'b0, end_t = 1'b0, skip_t = 1'b0, fr_bad = 1'b0;
    reg [23:0] pack = 24'd0;
    reg [23:0] nbytes = 24'd0, nwords = 24'd0, fr_bytes = 24'd0, fr_words = 24'd0;
    reg [FIFO_AW:0] wp = 0, wp_g = 0, rp_g1 = 0, rp_g2 = 0;
    wire [FIFO_AW:0] rp_w = g2b(rp_g2);
    wire [FIFO_AW:0] fill = wp - rp_w;              // modulo 2^(FIFO_AW+1), not in 32 bits
    wire full = fill == FD;
    wire [1:0] nb = nbytes[1:0];
    wire push = active && (wend ? nb != 2'd0 : wvalid && nb == 2'd3);  // an entry is complete, or the last one
    wire put  = push && !full;
    wire [1:0]  nw = (wend && nb != 2'd3) ? 2'd1 : 2'd2;  // 16-bit words in the entry
    wire [31:0] entry = !wend ? {wdata, pack} : nb == 2'd1 ? {24'd0, pack[7:0]}
                      : nb == 2'd2 ? {16'd0, pack[15:0]} : {8'd0, pack};
    wire [FIFO_AW:0] wp_n = wp + put;

    always @(posedge wclk) begin
        en_w  <= {en_w[1:0], en};
        ack_w <= {ack_w[1:0], ack_t};
        rp_g1 <= rp_g;
        rp_g2 <= rp_g1;
        if (put) fifo[wp[FIFO_AW-1:0]] <= entry;
        wp   <= wp_n;
        wp_g <= wp_n ^ (wp_n >> 1);
        if (!active) begin
            if (wstart && en_w[2]) begin
                if (end_t == ack_w[2]) begin           // the previous frame is finished on the clk side
                    active <= 1'b1; ovf <= 1'b0; nbytes <= 24'd0; nwords <= 24'd0;
                end else begin
                    skip_t <= ~skip_t;
                end
            end
        end else if (wend) begin
            active <= 1'b0; end_t <= ~end_t;
            fr_bytes <= nbytes; fr_words <= nwords + (put ? nw : 2'd0); fr_bad <= ovf || (push && full);
        end else if (wvalid) begin
            nbytes <= nbytes + 1'b1;
            case (nb)
                2'd0: pack[7:0]   <= wdata;
                2'd1: pack[15:8]  <= wdata;
                2'd2: pack[23:16] <= wdata;
                2'd3: ;
            endcase
            nwords <= nwords + (put ? 2'd2 : 2'd0);
            if (push && full) ovf <= 1'b1;
        end
    end

    // ---- clk side ----
    reg [FIFO_AW:0] wp_g1 = 0, wp_g2 = 0;
    reg [2:0]  end_s = 3'd0, skip_s = 3'd0;
    reg [31:0] fifo_q = 32'd0;
    reg [SEQW-1:0] wseq = 0, rseq = 0;
    reg [31:0] dropped = 32'd0, reg_q = 32'd0, win_q = 32'd0;
    reg [23:0] slot_len = 24'd0, taken = 24'd0;
    reg [1:0]  st = S_IDLE, op = OP_DATA;
    reg        accept = 1'b0, cut = 1'b0, inflight = 1'b0, hdr_idx = 1'b0, sticky = 1'b0, win_sel = 1'b0;
    reg        void = 1'b0;                          // CTRL[1] came during this frame: do not keep it
    reg        ferr = 1'b0;                          // a fetch read came back short
    reg [2:0]  rcnt = 3'd0;                          // words of the current 4-word read
    reg [21:0] slot_base = 22'd0, waddr = 22'd0, faddr = 22'd0;
    reg [7:0]  fleft = 8'd0;                         // 4-word reads still to issue
    reg [8:0]  widx = 9'd0;                          // 16-bit word in the window
    reg [15:0] rlo = 16'd0;

    wire [FIFO_AW:0] wp_c = g2b(wp_g2);
    wire [FIFO_AW:0] avail = wp_c - rp;              // entries
    wire        pending = end_s[1] ^ ack_t;          // the current frame has ended on the wclk side
    wire [23:0] rem = fr_words - taken;              // words, valid while pending
    wire [FIFO_AW+1:0] w_all = {avail, 1'b0} - taken[0];               // words in the FIFO
    wire [FIFO_AW+1:0] w_safe = (w_all >= 2) ? w_all - 2'd2 : 0;       // without the newest entry
    wire [3:0]  n_av = (w_all >= 8) ? 4'd8 : w_all[3:0];
    wire [3:0]  n_go = !pending ? ((w_safe >= 8) ? 4'd8 : 4'd0) : (rem < n_av) ? rem[3:0] : n_av;
    wire        last = pending && taken == fr_words - 1'b1;
    wire [23:0] room = CAP - taken;
    wire [3:0]  n_wr = (room < n_go) ? room[3:0] : n_go;
    wire [SEQW-1:0] used = wseq - rseq;
    wire        busy_f = fleft != 8'd0 || (inflight && op == OP_READ);
    wire [31:0] wseq32 = wseq, rseq32 = rseq;
    wire [31:0] hdr = {fr_bad || cut, wseq32[14:0], fr_bytes[15:0]};
    wire        decide = st == S_IDLE && (avail != 0 || pending);
    wire        skip_e = skip_s[2] ^ skip_s[1];
    wire [7:0]  widx_r = bus_adr - WBASE;
    wire        take = inflight && op == OP_DATA && wd_ready;
    wire        acc = accept && !void;
    wire        toss = st == S_RUN && (!acc || cut) && (pending ? w_all != 0 && rem != 0 : w_safe != 0);
    wire        wr_now = bus_stb && bus_we && !bus_ack && reg_hit;
    assign wd_data = op == OP_HDR ? (hdr_idx ? hdr[31:16] : hdr[15:0]) : taken[0] ? fifo_q[31:16] : fifo_q[15:0];
    assign bus_dat_r = win_sel ? win_q : reg_q;

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        win_sel <= win_hit;
        win_q   <= win[widx_r];
        case (rel[2:0])
            3'd1:    reg_q <= reg_hit ? wseq32 : 32'd0;
            3'd2:    reg_q <= reg_hit ? rseq32 : 32'd0;
            3'd3:    reg_q <= reg_hit ? dropped : 32'd0;
            3'd5:    reg_q <= reg_hit ? {29'd0, ferr, sticky, busy_f} : 32'd0;
            3'd6:    reg_q <= reg_hit ? {8'd0, slot_len} : 32'd0;
            3'd7:    reg_q <= reg_hit ? {NS16, SW16} : 32'd0;
            default: reg_q <= 32'd0;
        endcase

        wp_g1  <= wp_g;
        wp_g2  <= wp_g1;
        end_s  <= {end_s[1:0], end_t};
        skip_s <= {skip_s[1:0], skip_t};
        fifo_q <= fifo[rp[FIFO_AW-1:0]];
        if ((take || toss) && (taken[0] || last)) rp <= rp + 1'b1;  // the entry is used up
        rp_g <= rp ^ (rp >> 1);
        if (take || toss) taken <= taken + 1'b1;
        dropped <= dropped + skip_e + (decide && !(used < NSLOTS));

        // frames
        if (decide) begin
            st <= S_RUN; taken <= 24'd0; cut <= 1'b0; void <= 1'b0;
            if (used < NSLOTS) begin
                accept <= 1'b1;
                slot_base <= wseq[NB-1:0] << SB;
                waddr <= (wseq[NB-1:0] << SB) + 22'd2;
            end else begin
                accept <= 1'b0;                         // full: counted in DROPPED above
            end
        end else if (st == S_RUN && pending && rem == 24'd0 && !inflight && !cmd_valid) begin
            if (!void) sticky <= sticky | fr_bad;
            if (acc) begin                              // last: the header
                st <= S_HDR; op <= OP_HDR; hdr_idx <= 1'b0; inflight <= 1'b1;
                cmd_valid <= 1'b1; cmd_write <= 1'b1; cmd_addr <= slot_base; cmd_len <= 4'd2;
            end else begin
                st <= S_IDLE; ack_t <= ~ack_t;
            end
        end else if (st == S_RUN && acc && !cut && n_go != 4'd0 && !inflight && !cmd_valid) begin
            if (room == 24'd0) begin
                cut <= 1'b1;                            // the slot is full: throw the rest away
            end else begin
                op <= OP_DATA; inflight <= 1'b1;
                cmd_valid <= 1'b1; cmd_write <= 1'b1; cmd_addr <= waddr; cmd_len <= n_wr;
                waddr <= waddr + n_wr;
            end
        end else if (fleft != 8'd0 && !inflight && !cmd_valid) begin
            op <= OP_READ; inflight <= 1'b1; rcnt <= 3'd0;
            cmd_valid <= 1'b1; cmd_write <= 1'b0; cmd_addr <= faddr; cmd_len <= 4'd4;
            faddr <= faddr + 22'd4; fleft <= fleft - 1'b1;
        end
        if (cmd_valid && cmd_ready) cmd_valid <= 1'b0;
        if (inflight && op == OP_HDR && wd_ready) hdr_idx <= 1'b1;
        if (rd_valid && inflight && op == OP_READ) begin
            if (widx[0]) win[widx[8:1]] <= {rd_data, rlo};
            else rlo <= rd_data;
            widx <= widx + 1'b1; rcnt <= rcnt + 1'b1;
        end
        if (done) begin
            inflight <= 1'b0;
            if (op == OP_HDR) begin
                st <= S_IDLE; ack_t <= ~ack_t;
                if (!void) begin
                    wseq <= wseq + 1'b1; slot_len <= fr_bytes;
                end
            end
            if (op == OP_READ && rcnt != 3'd4) ferr <= 1'b1;
        end

        // registers
        if (wr_now && rel == 30'd0) begin
            en <= bus_dat_w[0];
            if (bus_dat_w[1]) begin
                wseq <= 0; rseq <= 0; dropped <= 32'd0; sticky <= 1'b0; void <= 1'b1;
            end
        end
        if (wr_now && rel == 30'd2) rseq <= bus_dat_w[SEQW-1:0];
        if (wr_now && rel == 30'd4 && !busy_f && bus_dat_w[31:24] != 8'd0) begin
            faddr <= bus_dat_w[21:0]; widx <= 9'd0; ferr <= 1'b0;
            fleft <= (bus_dat_w[31:24] > 8'd64) ? 8'd128 : {bus_dat_w[30:24], 1'b0};
        end
        if (rst) begin
            en <= 1'b0; cmd_valid <= 1'b0; inflight <= 1'b0; fleft <= 8'd0;
        end
    end
endmodule
