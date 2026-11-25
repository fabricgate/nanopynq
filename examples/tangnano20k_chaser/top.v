// Tang Nano 20K example for `nanopynq build`, the 9K one on the 20K's pins: the base design (UART link through
// the BL616, sysinfo, LEDs, buttons) plus chaser @0x7000 (the 9K example's chaser.v). The 6 LEDs show the chaser
// while it runs, else the leds GPIO. LEDs are active-low, buttons active-high.
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

    // chaser sits on base_regs' external port: it reads 0 outside its window and acks every strobe.
    wire [31:0] ch_dat;
    wire        ch_ack, ch_hit, ch_run;
    wire [5:0]  ch_leds;
    wire [5:0]  leds;
    base_regs #(.LED_WIDTH(6), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(btn),
        .ext_hit(ch_hit), .ext_dat_r(ch_dat), .ext_ack(ch_ack));

    chaser #(.BASE(32'h0000_7000), .WIDTH(6), .CLK_HZ(27_000_000)) chase (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(ch_dat), .bus_ack(ch_ack), .hit(ch_hit), .run(ch_run), .current(ch_leds));

    assign led = ~(ch_run ? ch_leds : leds);
endmodule
