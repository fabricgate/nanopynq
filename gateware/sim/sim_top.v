// Simulation top: 4 clocks per UART bit (1 MHz / 250 kbaud), bridge timeout 2000 clocks
// (test_bridge.py TIMEOUT_CYCLES must match).
module sim_top (
    input        clk,
    input        rst,
    input        uart_rx,
    output       uart_tx,
    output [5:0] leds,
    input  [1:0] buttons
);
    base_soc #(.CLK_HZ(1_000_000), .BAUD(250_000), .TIMEOUT_CYCLES(2000), .LED_WIDTH(6), .BTN_WIDTH(2),
               .DESIGN_ID(32'hABF7_8D8C)) soc (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx), .leds(leds), .buttons(buttons));
endmodule
