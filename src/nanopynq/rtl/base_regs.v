// Register slaves of the base design, shared by the UART and the JTAG bridge: sysinfo @0x0,
// leds @0x1000 (output), buttons @0x2000 (input). Unmapped addresses read 0xDEADBEEF and are
// acked, so the bus never hangs. Active-high here: 1 = LED on / button pressed.
// ext_*: add-on slaves outside base_regs share the bus; tie all three to 0 when there are none.
// npq_name: the IP names nanopynq build gives these instances (the attributes do not change the bitstream).
module base_regs #(
    parameter LED_WIDTH = 6,
    parameter BTN_WIDTH = 2,
    parameter [31:0] DESIGN_ID = 32'd0
) (
    input                  clk,
    input                  rst,
    input  [29:0]          bus_adr,
    input  [31:0]          bus_dat_w,
    input                  bus_we,
    input                  bus_stb,
    output reg [31:0]      bus_dat_r,
    output reg             bus_ack,
    output [LED_WIDTH-1:0] leds,
    input  [BTN_WIDTH-1:0] buttons,
    input                  ext_hit,
    input  [31:0]          ext_dat_r,
    input                  ext_ack
);
    wire [31:0] si_dat, led_dat, btn_dat;
    wire        si_ack, led_ack, btn_ack, si_hit, led_hit, btn_hit;
    wire [BTN_WIDTH-1:0] btn_unused_out;
    wire [LED_WIDTH-1:0] led_unused_in = {LED_WIDTH{1'b0}};

    (* npq_name = "sys" *)
    sysinfo #(.DESIGN_ID(DESIGN_ID)) si (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we),
        .bus_stb(bus_stb), .bus_dat_r(si_dat), .bus_ack(si_ack), .hit(si_hit));
    (* npq_name = "leds" *)
    regbus_gpio #(.BASE(32'h0000_1000), .WIDTH(LED_WIDTH), .IS_INPUT(0)) gpio_leds (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(led_dat), .bus_ack(led_ack), .hit(led_hit), .pins_in(led_unused_in), .pins_out(leds));
    (* npq_name = "buttons" *)
    regbus_gpio #(.BASE(32'h0000_2000), .WIDTH(BTN_WIDTH), .IS_INPUT(1)) gpio_btns (
        .clk(clk), .rst(rst), .bus_adr(bus_adr), .bus_dat_w(bus_dat_w), .bus_we(bus_we), .bus_stb(bus_stb),
        .bus_dat_r(btn_dat), .bus_ack(btn_ack), .hit(btn_hit), .pins_in(buttons), .pins_out(btn_unused_out));

    // Default slave: same 1-clock ack protocol, answers everything no one else claims.
    wire miss = !(si_hit || led_hit || btn_hit || ext_hit);
    reg  def_ack;
    always @(posedge clk) def_ack <= !rst && bus_stb && miss && !def_ack;

    always @* begin
        bus_ack   = si_ack | led_ack | btn_ack | def_ack | ext_ack;
        bus_dat_r = si_dat | led_dat | btn_dat | ext_dat_r | (def_ack ? 32'hDEAD_BEEF : 32'd0);
    end
endmodule
