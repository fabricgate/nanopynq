(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

// Diagnostic logic analyser for GW_JTAG outputs.
// The 27 MHz clock samples {en2, en1, udr, sdr, tdi, tck} (via 2 flip-flops). Each change is
// stored as {timestamp[15:0], state[5:0]} until NEV entries are full; recording starts when
// en1 first goes high. ER2 (IR 0x43) reads the entries back: every Update-DR loads the next
// entry into a 32-bit shift register (same shift timing as userdr_open.v).
module top(input clk, output led);
    localparam NEV = 48;
    wire tck, tdi, tlr, rti1, rti2, sdr, pdr, udr, en1, en2;
    GW_JTAG u_gw_jtag(.tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr),
        .run_test_idle_er1_o(rti1), .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr),
        .pause_dr_o(pdr), .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(1'b0), .tdo_er2_i(sr2[0]));

    // ---- capture side (27 MHz) ----
    reg [5:0] s1 = 0, s2 = 0, last = 0;
    reg [15:0] ts = 0;
    reg armed = 0;
    reg [5:0] wr = 0;
    reg [21:0] mem [0:NEV-1];
    wire [5:0] now = {en2, en1, udr, sdr, tdi, tck};
    always @(posedge clk) begin
        s1 <= now; s2 <= s1;
        if (!armed) begin
            if (s2[4]) begin armed <= 1; ts <= 0; last <= s2; mem[0] <= {16'd0, s2}; wr <= 1; end
        end else begin
            ts <= ts + 1'b1;
            if (s2 != last && wr < NEV) begin
                mem[wr] <= {ts + 1'b1, s2};
                wr <= wr + 1'b1;
                last <= s2;
            end
        end
    end
    assign led = ~(wr == NEV);   // LED on when the buffer is full

    // ---- readout via ER2 ----
    reg [31:0] sr2 = 32'hDEADBEEF;
    reg [5:0] rd = 0;
    reg shift2_l = 0, ld = 0, ld_done = 0;
    always @(posedge tck) begin
        shift2_l <= en2 & sdr;
        ld <= en2 & udr;
    end
    always @(negedge tck) begin
        ld_done <= ld;
        if (ld & ~ld_done) begin
            sr2 <= {4'hA, rd, mem[rd]};
            rd <= (rd == NEV - 1) ? 6'd0 : rd + 1'b1;
        end else if ((en2 & sdr) | shift2_l)
            sr2 <= {tdi, sr2[31:1]};
    end
endmodule
