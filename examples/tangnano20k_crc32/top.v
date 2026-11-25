// Tang Nano 20K example for `nanopynq build`, the 9K one on the 20K's pins: the base design (UART link through
// the BL616, sysinfo, LEDs, buttons) plus crc @0x7000 (the 9K example's crc32.v), a CRC-32 calculator. All 6 LEDs
// are the leds GPIO. LEDs are active-low, buttons active-high.
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

    // crc sits on base_regs' external port: it reads 0 outside its window and acks every strobe.
    wire [31:0] crc_dat;
    wire        crc_ack, crc_hit;
    wire [5:0]  leds;
    base_regs #(.LED_WIDTH(6), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(btn),
        .ext_hit(crc_hit), .ext_dat_r(crc_dat), .ext_ack(crc_ack));

    crc32 #(.BASE(32'h0000_7000)) crc (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(crc_dat), .bus_ack(crc_ack), .hit(crc_hit));

    assign led = ~leds;
endmodule
