// PWM / timer: a counter that runs over PERIOD clocks; pwm is high for the first DUTY of them.
// PERIOD and DUTY written by the host take effect at the next period start (no short pulses), and
// at once while disabled. Byte addresses from BASE:
//   +0x0  CTRL   (rw): [0] enable. Disabling drives pwm low and clears COUNT and WRAPS.
//   +0x4  PERIOD (rw): clocks per period (0 and 1 both mean every clock)
//   +0x8  DUTY   (rw): clocks high per period (0 = always low, >= PERIOD = always high)
//   +0xC  COUNT  (ro): position in the current period, 0 .. PERIOD-1
//   +0x10 WRAPS  (ro): periods completed since enable (the timer: time = WRAPS * PERIOD / f_clk)
module pwm_timer #(
    parameter BASE = 32'h0000_7000
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
    output reg        pwm = 1'b0
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 5);

    reg        en = 1'b0, run = 1'b0;
    reg [31:0] period = 32'd0, duty = 32'd0;  // as written by the host
    reg [31:0] d_cur = 32'd0, p_cur = 32'd0;  // in effect for the current period
    reg [31:0] cnt = 32'd0, wraps = 32'd0;
    wire       last = ({1'b0, cnt} + 33'd1) >= {1'b0, p_cur};

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (!hit) bus_dat_r <= 32'd0;
        else case (rel[2:0])
            3'd0:    bus_dat_r <= {31'd0, en};
            3'd1:    bus_dat_r <= period;
            3'd2:    bus_dat_r <= duty;
            3'd3:    bus_dat_r <= cnt;
            default: bus_dat_r <= wraps;
        endcase
        if (rst) begin
            en <= 1'b0; run <= 1'b0; period <= 32'd0; duty <= 32'd0;
            cnt <= 32'd0; wraps <= 32'd0; pwm <= 1'b0;
        end else begin
            if (bus_stb && bus_we && hit && !bus_ack)
                case (rel[2:0])
                    3'd0: en <= bus_dat_w[0];
                    3'd1: period <= bus_dat_w;
                    3'd2: duty <= bus_dat_w;
                    default: ;
                endcase
            run <= en;
            if (!en) begin
                cnt <= 32'd0; wraps <= 32'd0; pwm <= 1'b0;
            end else if (!run || last) begin  // a period starts: take the host's values
                cnt <= 32'd0; p_cur <= period; d_cur <= duty; pwm <= (duty != 32'd0);
                if (run) wraps <= wraps + 1'b1;
            end else begin
                cnt <= cnt + 1'b1; pwm <= (cnt + 1'b1) < d_cur;
            end
        end
    end
endmodule
