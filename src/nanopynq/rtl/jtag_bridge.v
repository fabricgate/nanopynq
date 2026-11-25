// GW_JTAG (user instruction 0x42 = ER1) <-> register-bus bridge. The jtag_* ports connect to the
// GW_JTAG outputs tck_o, tdi_o, shift_dr_capture_dr_o, update_dr_o, enable_er1_o and its input tdo_er1_i.
// One 64-bit DR scan carries one command, executed at Update-DR:
//   [63] valid, [62] write, [61:32] word address, [31:0] write data
// The next scan shifts out the response (LSB first):
//   [63] done (the last valid command got its bus ack), [62:32] 0, [31:0] read data (0 for writes)
// A scan whose valid bit is 0 sets the response to 0.
//
// tck_o is not on a low-skew clock network; clocking a shift register with it races depending on
// placement (reports/report_jtag_bridge_spike.md 13.3). So the board clock oversamples the GW_JTAG
// outputs (2 flip-flops each) and acts on the falling edge of TCK (the capture block below is
// tools/p0/gwjtag4k/userdr_open.v, measured on hardware, widened to 64 bits):
//  - tdi_o and shift_dr_capture_dr_o change on the rising edge of TCK, so they are stable here
//  - shift_dr_capture_dr_o drops at the edge that leaves Shift-DR, so the last TDI bit is
//    taken one falling edge later (sdr_n)
//  - the host samples TDO while TCK is high, and TDO (= sr[0]) only changes after a falling edge
// Needs the board clock to be several times faster than TCK (BL702: about 2 MHz vs 27 MHz).
// Bus: same as uartbone_bridge (bus_stb held until bus_ack). The response is written into sr at the
// ack, so a slave must ack before the next scan starts shifting (a few TCK periods; base_regs acks in 1 clock).
module jtag_bridge (
    input             clk,
    input             rst,
    input             jtag_tck,
    input             jtag_tdi,
    input             jtag_shift_dr,
    input             jtag_update_dr,
    input             jtag_enable,
    output            jtag_tdo,
    output reg [29:0] bus_adr,
    output reg [31:0] bus_dat_w,
    input      [31:0] bus_dat_r,
    output reg        bus_we,
    output reg        bus_stb,
    input             bus_ack
);
    reg [63:0] sr = 64'd0;
    reg sdr_n = 1'b0;
    reg [2:0] tck_s = 0;
    reg [1:0] tdi_s = 0, sdr_s = 0, udr_s = 0, en1_s = 0;
    wire tck_fall = tck_s[2] & ~tck_s[1];
    wire shifting = en1_s[1] & sdr_s[1];
    assign jtag_tdo = sr[0];

    always @(posedge clk) begin
        tck_s <= {tck_s[1:0], jtag_tck};
        tdi_s <= {tdi_s[0], jtag_tdi};
        sdr_s <= {sdr_s[0], jtag_shift_dr};
        udr_s <= {udr_s[0], jtag_update_dr};
        en1_s <= {en1_s[0], jtag_enable};
        if (tck_fall) begin
            sdr_n <= shifting;
            if (shifting | sdr_n) sr <= {tdi_s[1], sr[63:1]};
            if (en1_s[1] & udr_s[1]) begin
                if (sr[63]) begin
                    bus_adr   <= sr[61:32];
                    bus_we    <= sr[62];
                    bus_dat_w <= sr[31:0];
                    bus_stb   <= 1'b1;
                end else begin
                    sr <= 64'd0;
                end
            end
        end
        if (bus_stb && bus_ack) begin
            bus_stb <= 1'b0;
            sr      <= {1'b1, 31'd0, bus_we ? 32'd0 : bus_dat_r};
        end
        if (rst) bus_stb <= 1'b0;
    end
endmodule
