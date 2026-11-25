// Read-only window on the GW1NS-4 user flash (FLASH256K: 256 Kbit, the Cortex-M3's program flash).
// BASE + 4*w reads word w (0..8191) with XADR = w[12:6], YADR = w[5:0], the split Gowin's EMPU uses
// (M3 byte address 4*w). Writes are acked and ignored: PROG / ERASE / NVSTR / DIN are tied to 0 here
// and never reach the bus.
// One read (UG295 table 3-9 / fig. 3-7; FLASH256K timing = FLASH64KZ): the strobe's clock latches w
// and raises XE = YE, the next clock raises SE (Tas), the next drops it (Tpws >= 5 ns), the next
// samples DOUT 2 clocks after SE rose (Tacc <= 25 ns, plus the LUT inverters nextpnr puts on every
// flash port when there is no EMCU), acks and drops XE / YE (Tah >= 25 ns). Needs clk <= 40 MHz.
// The ack comes 4 clocks after the strobe; the other slaves on this bus ack every strobe after one
// clock and the bridge takes the first ack, so the top must keep bus_stb from them while hit is high
// (stb & !hit, as camhdmi_top.v does for bus_cdc).
// GW1NS-4 (reports/report_4k_peripherals.md 3.8): never without an EMCU in the design (nextpnr then inverts
// every FLASH256K port, so PROG / ERASE / NVSTR reach the flash as 1; the Gowin IDE refuses it, PA2090).
// With an EMCU (tools/p0/uflash4k/uflash_emcu_top.v) it is safe but reads only zeros: on the GW1NSR-4C the
// flash data reaches the M3 alone, the fabric DOUT wires read 0 (also with a Gowin IDE bitstream).
module uflash_reader #(
    parameter BASE = 32'h0001_0000
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r = 32'd0,
    output reg        bus_ack = 1'b0,
    output            hit
);
    localparam WORDS = 8192;
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < WORDS);

    reg [12:0] w = 13'd0;
    reg        xe = 1'b0, se = 1'b0;
    reg [1:0]  step = 2'd0;  // 0 idle, 1 SE up, 2 SE down, 3 sample + ack
    wire [31:0] dout;

    FLASH256K flash (
        .XADR(w[12:6]), .YADR(w[5:0]), .XE(xe), .YE(xe), .SE(se),
        .ERASE(1'b0), .PROG(1'b0), .NVSTR(1'b0), .DIN(32'd0), .DOUT(dout));

    always @(posedge clk) begin
        bus_ack   <= 1'b0;
        bus_dat_r <= 32'd0;  // OR-ed into the shared read bus
        if (rst) begin
            xe <= 1'b0; se <= 1'b0; step <= 2'd0;
        end else if (step != 2'd0) begin
            step <= step + 1'b1;
            case (step)
                2'd1: se <= 1'b1;
                2'd2: se <= 1'b0;
                default: begin bus_dat_r <= dout; bus_ack <= 1'b1; xe <= 1'b0; end
            endcase
        end else if (bus_stb && hit && !bus_ack) begin
            if (bus_we) bus_ack <= 1'b1;
            else begin w <= rel[12:0]; xe <= 1'b1; step <= 2'd1; end
        end
    end
endmodule
