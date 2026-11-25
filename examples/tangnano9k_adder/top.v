// Tang Nano 9K example for `nanopynq build`: the base design (UART link, sysinfo, LEDs, buttons) plus
// adder @0x7000 (the example's own adder.v). All 6 LEDs are the leds GPIO. LEDs are active-low.
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

    // adder sits on base_regs' external port: it reads 0 outside its window and acks every strobe.
    wire [31:0] add_dat;
    wire        add_ack, add_hit;
    wire [5:0]  leds;
    base_regs #(.LED_WIDTH(6), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(add_hit), .ext_dat_r(add_dat), .ext_ack(add_ack));

    adder #(.BASE(32'h0000_7000)) add (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(add_dat), .bus_ack(add_ack), .hit(add_hit));

    assign led = ~leds;
endmodule
