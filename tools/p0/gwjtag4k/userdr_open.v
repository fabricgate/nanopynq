(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

// ER1 user DR: 32-bit shift register driven from the board clock, not from tck_o.
// tck_o is not on a low-skew clock network, so using it as a clock lets a shift register
// race with itself (measured). Instead the 27 MHz clock oversamples the GW_JTAG outputs
// (2 flip-flops each) and acts on the falling edge of TCK:
//  - tdi_o and shift_dr_capture_dr_o change on the rising edge of TCK, so they are stable here
//  - shift_dr_capture_dr_o drops at the edge that leaves Shift-DR, so the last TDI bit is
//    taken one falling edge later (sdr_n)
//  - the host samples TDO while TCK is high, and TDO (= sr[0]) only changes after a falling edge
// Needs the oversampling clock to be several times faster than TCK (BL702: about 2 MHz).
module top(input clk, output led);
    wire tck, tdi, tlr, rti1, rti2, sdr, pdr, udr, en1, en2;
    reg [31:0] sr = 32'hC0FFEE42;
    reg held = 1'b0, sdr_n = 1'b0;
    reg [2:0] tck_s = 0;
    reg [1:0] tdi_s = 0, sdr_s = 0, udr_s = 0, en1_s = 0;
    (* keep *) GW_JTAG u_gw_jtag(.tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr),
        .run_test_idle_er1_o(rti1), .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr),
        .pause_dr_o(pdr), .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(sr[0]), .tdo_er2_i(1'b1));
    wire tck_fall = tck_s[2] & ~tck_s[1];
    wire shifting = en1_s[1] & sdr_s[1];
    always @(posedge clk) begin
        tck_s <= {tck_s[1:0], tck};
        tdi_s <= {tdi_s[0], tdi};
        sdr_s <= {sdr_s[0], sdr};
        udr_s <= {udr_s[0], udr};
        en1_s <= {en1_s[0], en1};
        if (tck_fall) begin
            sdr_n <= shifting;
            if (shifting | sdr_n) sr <= {tdi_s[1], sr[31:1]};
            if (en1_s[1] & udr_s[1]) held <= sr[0];
        end
    end
    assign led = ~held;
endmodule
