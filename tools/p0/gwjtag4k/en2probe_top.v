(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

// Checks which signal the chipdb wire for enable_er2_o (Q1 at (0,0)) carries.
// The 27 MHz clock oversamples the GW_JTAG outputs and counts their rising edges.
// ER1 (IR 0x42) reads a 32-bit status word, same shift timing as userdr_open.v:
//   [31:24] rising edges of enable_er2_o   [23:16] rising edges of enable_er1_o
//   [15:8]  rising edges of run_test_idle_er2_o
//   [7:0]   live {pause_dr_o, test_logic_reset_o, run_test_idle_er2_o, run_test_idle_er1_o,
//                 update_dr_o, en2 seen high while en1 high, enable_er2_o, enable_er1_o}
// ER2 (IR 0x43) returns enable_er2_o & ~enable_er1_o on TDO.
module top(input clk, output led);
    wire tck, tdi, tlr, rti1, rti2, sdr, pdr, udr, en1, en2;
    (* keep *) GW_JTAG u_gw_jtag(.tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr),
        .run_test_idle_er1_o(rti1), .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr),
        .pause_dr_o(pdr), .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(sr[0]), .tdo_er2_i(en2 & ~en1));

    reg [2:0] tck_s = 0;
    reg [1:0] tdi_s = 0, sdr_s = 0, udr_s = 0, en1_s = 0, en2_s = 0, rti1_s = 0, rti2_s = 0,
              tlr_s = 0, pdr_s = 0;
    reg en2_q = 0, en1_q = 0, rti2_q = 0, both = 0, sdr_n = 0;
    reg [7:0] c_en2 = 0, c_en1 = 0, c_rti2 = 0;
    reg [31:0] sr = 0;
    wire tck_fall = tck_s[2] & ~tck_s[1];
    wire shifting = en1_s[1] & sdr_s[1];
    wire [31:0] status = {c_en2, c_en1, c_rti2,
        pdr_s[1], tlr_s[1], rti2_s[1], rti1_s[1], udr_s[1], both, en2_s[1], en1_s[1]};
    always @(posedge clk) begin
        tck_s <= {tck_s[1:0], tck};
        tdi_s <= {tdi_s[0], tdi};   sdr_s <= {sdr_s[0], sdr};   udr_s <= {udr_s[0], udr};
        en1_s <= {en1_s[0], en1};   en2_s <= {en2_s[0], en2};
        rti1_s <= {rti1_s[0], rti1}; rti2_s <= {rti2_s[0], rti2};
        tlr_s <= {tlr_s[0], tlr};   pdr_s <= {pdr_s[0], pdr};
        en2_q <= en2_s[1]; en1_q <= en1_s[1]; rti2_q <= rti2_s[1];
        if (en2_s[1] & ~en2_q) c_en2 <= c_en2 + 1'b1;
        if (en1_s[1] & ~en1_q) c_en1 <= c_en1 + 1'b1;
        if (rti2_s[1] & ~rti2_q) c_rti2 <= c_rti2 + 1'b1;
        if (en1_s[1] & en2_s[1]) both <= 1'b1;
        if (tck_fall) begin
            sdr_n <= shifting;
            if (shifting | sdr_n) sr <= {tdi_s[1], sr[31:1]};
        end else if (!(shifting | sdr_n))
            sr <= status;           // outside Shift-DR the register follows the status
    end
    assign led = ~en2_s[1];         // LED on while enable_er2_o is high
endmodule
