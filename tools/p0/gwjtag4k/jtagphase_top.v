(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

// Phase probe: when does the host sample TDO?
// ER1: TDO = parity of a counter that steps on every rising edge of tck_o in Shift-DR.
// ER2: TDO = parity of a counter that steps on every falling edge of tck_o in Shift-DR.
// Both counters clear while shift_dr_capture_dr_o is low.
module top(output led);
    wire tck, tdi, tlr, rti1, rti2, sdr, pdr, udr, en1, en2;
    reg [7:0] rc = 0, fc = 0;
    (* keep *) GW_JTAG u_gw_jtag(.tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr),
        .run_test_idle_er1_o(rti1), .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr),
        .pause_dr_o(pdr), .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(rc[0]), .tdo_er2_i(fc[0]));
    always @(posedge tck) rc <= sdr ? rc + 1'b1 : 8'd0;
    always @(negedge tck) fc <= sdr ? fc + 1'b1 : 8'd0;
    assign led = ~(rc[7] ^ fc[7]);
endmodule
