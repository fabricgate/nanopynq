// Tang Nano 4K user flash read, EMCU shape (reports/report_4k_peripherals.md 3.8). On hardware it reads only
// zeros, also after blinky.bin was written with openFPGALoader --mcufw: the fabric DOUT wires read 0.
// The base design (GW_JTAG link, sysinfo, LED, buttons) plus uflash_reader @0x10000 and a stub EMCU. With an
// EMCU, nextpnr puts no inverters on the FLASH256K pins, and the bitstream matches the Gowin IDE's EMCU builds:
// PROG / ERASE / NVSTR / DIN / INUSEN on VSS, DOUT routed into the fabric. The M3 starts after configuration
// (its reset is the GSR); TARGFLASH0HREADYOUT = 0 keeps it waiting on its first fetch.
// Build: tools/p0/uflash4k/build_emcu.py DIR (no gowin_pack -c, as Apicula's EMCU examples).
(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

module top (
    input        clk,       // 27 MHz
    output       led,
    input  [1:0] btn
);
    reg [4:0] por = 5'd0;
    wire      rst = !por[4];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    wire tck, tdi, sdr, udr, en1, tdo;
    wire tlr, rti1, rti2, pdr, en2;
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

    wire [31:0] uf_dat;
    wire        uf_ack, uf_hit, leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb & !uf_hit),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(~btn),
        .ext_hit(uf_hit), .ext_dat_r(uf_dat), .ext_ack(uf_ack));
    assign led = ~leds;

    uflash_reader #(.BASE(32'h0001_0000)) uflash (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(uf_dat), .bus_ack(uf_ack), .hit(uf_hit));

    // Stub EMCU: TARGFLASH0HREADYOUT = 0, so the M3 waits for ever on its first fetch.
    (* keep *) EMCU cpu (
        .FCLK(clk), .PORESETN(1'b0), .SYSRESETN(1'b0), .RTCSRCCLK(1'b0), .MTXREMAP(4'b0),
        .UART0RXDI(1'b1), .UART1RXDI(1'b1), .IOEXPINPUTI(16'd0), .SRAM0RDATA(32'd0),
        .TARGFLASH0HRDATA(32'd0), .TARGFLASH0HRUSER(3'd0), .TARGFLASH0HRESP(1'b0), .TARGFLASH0EXRESP(1'b0),
        .TARGFLASH0HREADYOUT(1'b0),
        .TARGEXP0HRDATA(32'd0), .TARGEXP0HREADYOUT(1'b0), .TARGEXP0HRESP(1'b0), .TARGEXP0EXRESP(1'b0),
        .TARGEXP0HRUSER(3'd0), .INITEXP0HSEL(1'b0), .INITEXP0HADDR(32'd0), .INITEXP0HTRANS(2'd0),
        .INITEXP0HWRITE(1'b0), .INITEXP0HSIZE(3'd0), .INITEXP0HBURST(3'd0), .INITEXP0HPROT(4'd0),
        .INITEXP0MEMATTR(2'd0), .INITEXP0EXREQ(1'b0), .INITEXP0HMASTER(4'd0), .INITEXP0HWDATA(32'd0),
        .INITEXP0HMASTLOCK(1'b0), .INITEXP0HAUSER(1'b0), .INITEXP0HWUSER(4'd0),
        .APBTARGEXP2PRDATA(32'd0), .APBTARGEXP2PREADY(1'b0), .APBTARGEXP2PSLVERR(1'b0),
        .GPINT(5'd0), .DAPSWDITMS(1'b0), .DAPTDI(1'b0), .DAPNTRST(1'b0), .DAPSWCLKTCK(1'b0),
        .FLASHERR(1'b0), .FLASHINT(1'b0));
endmodule
