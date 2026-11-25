// Tang Nano 4K SPI flash check: the base design (GW_JTAG link, sysinfo, LED, buttons) plus spi_master
// @0x8000 on the configuration SPI pins, which the board wires to its P25Q32 flash (IDE pin table,
// GW1NSR-4C QFN48P: 1 MCLK, 2 MCS_N, 47 MI, 48 MO). The host builds the flash commands
// (tools/p0/flash4k/flash_check.py). Pins 8 (JTAGSEL_N) and 9 (DONE), reportedly the flash WP# / HOLD#, are not
// touched. gowin_pack needs --mspi_as_gpio (in boards.yaml). Built with the patched toolchain like the base top.
(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

module top #(
    parameter [31:0] DESIGN_ID = 32'd0  // sysinfo design_id, set at build time
) (
    input        clk,       // 27 MHz
    output       led,
    input  [1:0] btn,
    output       flash_sck,
    output       flash_cs_n,
    output       flash_mosi,
    input        flash_miso
);
    reg [4:0] por = 5'd0;
    wire      rst = !por[4];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    wire tck, tdi, sdr, udr, en1, tdo;
    wire tlr, rti1, rti2, pdr, en2;  // unused GW_JTAG outputs
    (* keep *) GW_JTAG u_gw_jtag (
        .tck_o(tck), .tdi_o(tdi), .test_logic_reset_o(tlr), .run_test_idle_er1_o(rti1),
        .run_test_idle_er2_o(rti2), .shift_dr_capture_dr_o(sdr), .pause_dr_o(pdr),
        .update_dr_o(udr), .enable_er1_o(en1), .enable_er2_o(en2),
        .tdo_er1_i(tdo), .tdo_er2_i(1'b1));

    wire [29:0] adr;
    wire [31:0] dat_w, dat_r;
    wire        we, stb, ack;
    jtag_bridge bridge (
        .clk(clk), .rst(rst), .jtag_tck(tck), .jtag_tdi(tdi), .jtag_shift_dr(sdr),
        .jtag_update_dr(udr), .jtag_enable(en1), .jtag_tdo(tdo),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));

    wire [31:0] spi_dat;
    wire        spi_ack, spi_hit, leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2), .DESIGN_ID(DESIGN_ID)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(spi_hit), .ext_dat_r(spi_dat), .ext_ack(spi_ack));
    assign led = ~leds;

    spi_master #(.BASE(32'h0000_8000)) flash (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(spi_dat), .bus_ack(spi_ack), .hit(spi_hit),
        .sck(flash_sck), .cs_n(flash_cs_n), .mosi(flash_mosi), .miso(flash_miso));
endmodule
