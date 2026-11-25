// Tang Nano 9K base design. LEDs and buttons are assumed active-low (to be confirmed on hardware).
module top #(
    parameter [31:0] DESIGN_ID = 32'd0  // sysinfo design_id, set at build time
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

    wire [5:0] leds;
    base_soc #(.CLK_HZ(27_000_000), .BAUD(115200), .LED_WIDTH(6), .BTN_WIDTH(2),
               .DESIGN_ID(DESIGN_ID)) soc (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx), .leds(leds), .buttons(~btn));
    assign led = ~leds;
endmodule
