// Base design with the UART link: UARTBone bridge + base_regs (address map in base_regs.v).
module base_soc #(
    parameter CLK_HZ         = 27_000_000,
    parameter BAUD           = 115200,
    parameter TIMEOUT_CYCLES = CLK_HZ / 10,
    parameter LED_WIDTH      = 6,
    parameter BTN_WIDTH      = 2,
    parameter [31:0] DESIGN_ID = 32'd0
) (
    input                  clk,
    input                  rst,
    input                  uart_rx,
    output                 uart_tx,
    output [LED_WIDTH-1:0] leds,
    input  [BTN_WIDTH-1:0] buttons
);
    wire [29:0] adr;
    wire [31:0] dat_w, dat_r;
    wire        we, stb, ack;

    uartbone_bridge #(.CLK_HZ(CLK_HZ), .BAUD(BAUD), .TIMEOUT_CYCLES(TIMEOUT_CYCLES)) bridge (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));
    base_regs #(.LED_WIDTH(LED_WIDTH), .BTN_WIDTH(BTN_WIDTH), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(buttons),
        .ext_hit(1'b0), .ext_dat_r(32'd0), .ext_ack(1'b0));
endmodule
