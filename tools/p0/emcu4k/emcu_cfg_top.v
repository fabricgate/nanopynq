// EMCU configuration check (reports/report_4k_mcu_tools.md 8): every option of Gowin's EMPU IP wired by hand for
// Apicula. Firmware: emcu_cfg.c (build_fw.sh). Bitstream: build_emcu_cfg.py.
//   SRAM 16 KB (SRAM0, 4096 words, byte lanes inferred into BSRAM), GPIO0 (out[0] -> LED, in = 0xA55A),
//   UART0 looped back in the fabric (TX -> RX) with a TX edge counter, APB2 masters 1..12 (PADDR[11:8] = 4..15),
//   an AHB2 slave register bank (TARGEXP0, 0xA0000000), and the GW_JTAG bridge to read it all.
// Bridge map @0x10000 (read only): +0x00..+0x2C APB slot 1..12 register 0, +0x30..+0x38 slot 1 registers 1..3,
//   +0x40..+0x4C AHB registers 0..3, +0x50 UART0 TX falling edges, +0x54 {GPIO out enable, GPIO out}.
(* blackbox *)
module GW_JTAG(input tck_pad_i, input tms_pad_i, input tdi_pad_i, output tdo_pad_o,
    output tck_o, output tdi_o, output test_logic_reset_o, output run_test_idle_er1_o,
    output run_test_idle_er2_o, output shift_dr_capture_dr_o, output pause_dr_o,
    output update_dr_o, output enable_er1_o, output enable_er2_o,
    input tdo_er1_i, input tdo_er2_i);
endmodule

module top (
    input  clk,  // 27 MHz, also the M3's FCLK
    output led   // GPIO0[0]
);
    reg [4:0] por = 5'd0;
    wire      rst = !por[4];
    always @(posedge clk) if (rst) por <= por + 1'b1;

    // ---------------- JTAG bridge
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

    // ---------------- EMCU
    wire [15:0] gpio_out, gpio_oen;
    wire        uart0_tx;
    wire [12:0] sram_addr;
    wire        sram_cs;
    wire [3:0]  sram_wren;
    wire [31:0] sram_wdata;
    reg  [31:0] sram_rdata;
    wire        hsel, hwrite, hreadymux;
    wire [31:0] haddr, hwdata;
    wire [1:0]  htrans;
    wire [2:0]  hsize;
    reg  [31:0] hrdata = 0;
    wire        psel, penable, pwrite;
    wire [11:0] paddr;
    wire [31:0] pwdata;
    reg  [31:0] prdata;

    wire        fhsel, flash_ready;
    wire [31:0] fdout;  // hard-wired to the M3 (nextpnr drops HRDATA); connecting it keeps FLASH256K
    wire [1:0]  fhtrans;
    wire [28:0] fhaddr;

    (* keep *) EMCU cpu (
        .FCLK(clk), .PORESETN(1'b0), .SYSRESETN(1'b0), .RTCSRCCLK(1'b0), .MTXREMAP(4'b0),
        .IOEXPOUTPUTO(gpio_out), .IOEXPOUTPUTENO(gpio_oen), .IOEXPINPUTI(16'hA55A),
        .UART0TXDO(uart0_tx), .UART0RXDI(uart0_tx), .UART1RXDI(1'b1),
        .SRAM0ADDR(sram_addr), .SRAM0CS(sram_cs), .SRAM0WREN(sram_wren), .SRAM0WDATA(sram_wdata),
        .SRAM0RDATA(sram_rdata),
        .TARGFLASH0HRDATA(fdout), .TARGFLASH0HRUSER(3'd0), .TARGFLASH0HRESP(1'b0), .TARGFLASH0EXRESP(1'b0),
        .TARGFLASH0HREADYOUT(flash_ready), .TARGFLASH0HSEL(fhsel), .TARGFLASH0HTRANS(fhtrans),
        .TARGFLASH0HADDR(fhaddr),
        .TARGEXP0HSEL(hsel), .TARGEXP0HADDR(haddr), .TARGEXP0HTRANS(htrans), .TARGEXP0HWRITE(hwrite),
        .TARGEXP0HSIZE(hsize), .TARGEXP0HWDATA(hwdata), .TARGEXP0HREADYMUX(hreadymux),
        .TARGEXP0HRDATA(hrdata), .TARGEXP0HREADYOUT(1'b1), .TARGEXP0HRESP(1'b0), .TARGEXP0EXRESP(1'b0),
        .TARGEXP0HRUSER(3'd0),
        .INITEXP0HSEL(1'b0), .INITEXP0HADDR(32'd0), .INITEXP0HTRANS(2'd0),
        .INITEXP0HWRITE(1'b0), .INITEXP0HSIZE(3'd0), .INITEXP0HBURST(3'd0), .INITEXP0HPROT(4'd0),
        .INITEXP0MEMATTR(2'd0), .INITEXP0EXREQ(1'b0), .INITEXP0HMASTER(4'd0), .INITEXP0HWDATA(32'd0),
        .INITEXP0HMASTLOCK(1'b0), .INITEXP0HAUSER(1'b0), .INITEXP0HWUSER(4'd0),
        .APBTARGEXP2PSEL(psel), .APBTARGEXP2PENABLE(penable), .APBTARGEXP2PWRITE(pwrite),
        .APBTARGEXP2PADDR(paddr), .APBTARGEXP2PWDATA(pwdata),
        .APBTARGEXP2PRDATA(prdata), .APBTARGEXP2PREADY(1'b1), .APBTARGEXP2PSLVERR(1'b0),
        .GPINT(5'd0), .DAPSWDITMS(1'b0), .DAPTDI(1'b0), .DAPNTRST(1'b0), .DAPSWCLKTCK(1'b0),
        .FLASHERR(1'b0), .FLASHINT(1'b0));
    assign led = gpio_out[0];

    // ---------------- flash read port (as Apicula's emcu-blinky: SE for one clock, ready again two later)
    reg  [1:0]  fstate = 2'd0;
    reg         fse = 1'b0;
    reg  [12:0] faddr = 13'd0;
    always @(posedge clk) begin
        fse <= 1'b0;
        case (fstate)
            2'd0: if (fhsel && fhtrans[1]) begin fstate <= 2'd1; faddr <= fhaddr[14:2]; fse <= 1'b1; end
            2'd1: fstate <= (fhsel && fhtrans[1]) ? 2'd2 : 2'd0;
            default: if (fhsel && fhtrans[1]) fstate <= 2'd0;
        endcase
    end
    assign flash_ready = fstate == 2'd0;
    FLASH256K flash (
        .XADR(faddr[12:6]), .YADR(faddr[5:0]), .XE(1'b1), .YE(1'b1), .SE(fse),
        .ERASE(1'b0), .PROG(1'b0), .NVSTR(1'b0), .DIN(32'd0), .DOUT(fdout));

    // ---------------- SRAM: 4096 words, one inferred RAM per byte lane (expect 8 BSRAM)
    reg [7:0] lane0 [0:4095], lane1 [0:4095], lane2 [0:4095], lane3 [0:4095];
    wire [11:0] sa = sram_addr[11:0];
    always @(posedge clk) begin if (sram_cs && sram_wren[0]) lane0[sa] <= sram_wdata[7:0];   sram_rdata[7:0]   <= lane0[sa]; end
    always @(posedge clk) begin if (sram_cs && sram_wren[1]) lane1[sa] <= sram_wdata[15:8];  sram_rdata[15:8]  <= lane1[sa]; end
    always @(posedge clk) begin if (sram_cs && sram_wren[2]) lane2[sa] <= sram_wdata[23:16]; sram_rdata[23:16] <= lane2[sa]; end
    always @(posedge clk) begin if (sram_cs && sram_wren[3]) lane3[sa] <= sram_wdata[31:24]; sram_rdata[31:24] <= lane3[sa]; end

    // ---------------- APB2: masters 1..12 at PADDR[11:8] = 4..15, one register each, slot 1 has four
    reg [31:0] apb [0:11];
    reg [31:0] s1 [1:3];
    wire [3:0] slot = paddr[11:8] - 4'd4;
    wire       apb_hit = paddr[11:8] >= 4'd4;
    integer i;
    initial begin for (i = 0; i < 12; i = i + 1) apb[i] = 0; s1[1] = 0; s1[2] = 0; s1[3] = 0; end
    always @(posedge clk)
        if (psel && penable && pwrite && apb_hit) begin
            if (paddr[3:2] == 2'd0) apb[slot] <= pwdata;
            else if (slot == 4'd0) s1[paddr[3:2]] <= pwdata;
        end
    always @* prdata = !apb_hit ? 32'd0 : paddr[3:2] == 2'd0 ? apb[slot] : slot == 4'd0 ? s1[paddr[3:2]] : 32'd0;

    // ---------------- AHB2 slave (TARGEXP0): four registers, zero wait states
    reg [31:0] ahb [0:3];
    reg        dwrite = 1'b0;
    reg [1:0]  didx = 2'd0;
    initial begin ahb[0] = 0; ahb[1] = 0; ahb[2] = 0; ahb[3] = 0; end
    always @(posedge clk) begin
        if (dwrite) ahb[didx] <= hwdata;                       // data phase of the previous write
        if (hsel && htrans[1] && hreadymux) begin              // address phase
            dwrite <= hwrite;
            didx   <= haddr[3:2];
            hrdata <= (dwrite && didx == haddr[3:2]) ? hwdata : ahb[haddr[3:2]];
        end else dwrite <= 1'b0;
    end

    // ---------------- UART0 TX activity
    reg tx_d = 1'b1;
    reg [31:0] tx_falls = 0;
    always @(posedge clk) begin tx_d <= uart0_tx; if (tx_d && !uart0_tx) tx_falls <= tx_falls + 1'b1; end

    // ---------------- bridge slave @0x10000 (1-clock ack, data gated by hit)
    wire [29:0] rel = adr - 30'h4000;
    wire        cf_hit = (adr >= 30'h4000) && (rel < 22);
    reg  [31:0] cf_dat = 0;
    reg         cf_ack = 1'b0;
    always @(posedge clk) begin
        cf_ack <= !rst && stb && !cf_ack;
        if (!cf_hit) cf_dat <= 32'd0;
        else if (rel < 12) cf_dat <= apb[rel[3:0]];
        else if (rel < 15) cf_dat <= s1[rel[3:0] - 4'd11];
        else if (rel == 15) cf_dat <= 32'd0;
        else if (rel < 20) cf_dat <= ahb[rel[1:0]];
        else if (rel == 20) cf_dat <= tx_falls;
        else cf_dat <= {gpio_oen, gpio_out};
    end
    wire leds;
    base_regs #(.LED_WIDTH(1), .BTN_WIDTH(2)) regs (
        .clk(clk), .rst(rst), .bus_adr(adr), .bus_dat_w(dat_w), .bus_we(we), .bus_stb(stb),
        .bus_dat_r(dat_r), .bus_ack(ack), .leds(leds), .buttons(2'b00),
        .ext_hit(cf_hit), .ext_dat_r(cf_dat), .ext_ack(cf_ack));
endmodule
