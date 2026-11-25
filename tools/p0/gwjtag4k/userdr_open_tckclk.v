(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

// ER1 user DR: 32-bit shift register (timing found empirically on GW1NS-4, see report).
//  - shift on the falling edge of tck_o, taking tdi_o directly
//  - shift_dr_capture_dr_o has already dropped at the edge that leaves Shift-DR, so the
//    condition is also held for one half cycle (shift_l) to catch the last bit
//  - TDO is sr[0] directly
module top(output led);
    wire tck, tdi, tlr, rti1, rti2, sdr, pdr, udr, en1, en2;
    reg [31:0] sr = 32'hC0FFEE42;
    reg held = 1'b0, shift_l = 1'b0;
    GW_JTAG u_gw_jtag(.tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr),
        .run_test_idle_er1_o(rti1), .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr),
        .pause_dr_o(pdr), .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(sr[0]), .tdo_er2_i(1'b1));
    always @(posedge tck) begin
        shift_l <= en1 & sdr;
        if (en1 & udr) held <= sr[0];
    end
    always @(negedge tck)
        if ((en1 & sdr) | shift_l) sr <= {tdi, sr[31:1]};
    assign led = ~held;
endmodule
