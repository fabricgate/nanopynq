// Tang Nano 20K example for `nanopynq build`, the 9K one on the 20K's pins: the base design (UART link through
// the BL616, sysinfo, LEDs, buttons) plus pwm_timer @0x7000. LEDs 0-4 are the leds GPIO; LED 5 is the PWM output.
// LEDs are active-low, buttons active-high.
module top #(
    parameter [31:0] DESIGN_ID = 32'd0  // sysinfo design_id, set by nanopynq build
) (
    input        clk,       // 27 MHz
    input        uart_rx,
    output       uart_tx,
    output [5:0] led,
    input  [1:0] btn
);
    // Power-on reset: no reset pin, hold rst for 16 clocks after configuration.
    reg [4:0] por = 5'd0;
    wire      rst = !por[4];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    wire [29:0] adr;
    wire [31:0] dat_w, dat_r;
    wire        we, stb, ack;
    uartbone_bridge #(.CLK_HZ(27_000_000), .BAUD(115200)) bridge (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));

    // pwm_timer sits on base_regs' external port: it reads 0 outside its window and acks every strobe.
    wire [31:0] pwm_dat;
    wire        pwm_ack, pwm_hit, pwm;
    wire [4:0]  leds;
    base_regs #(.LED_WIDTH(5), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(btn),
        .ext_hit(pwm_hit), .ext_dat_r(pwm_dat), .ext_ack(pwm_ack));

    (* npq_name = "pwm" *)  // the IP name in the .npq (without it: the instance name, timer)
    pwm_timer #(.BASE(32'h0000_7000)) timer (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(pwm_dat), .bus_ack(pwm_ack), .hit(pwm_hit), .pwm(pwm));

    assign led = ~{pwm, leds};
endmodule
