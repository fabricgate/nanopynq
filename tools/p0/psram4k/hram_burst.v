// Hardware check of src/nanopynq/rtl/hyperram_ctrl.v: a register front for one burst at a time.
// Byte addresses from BASE:
//   +0x00 ADDR (rw): [21:0] first 16-bit word
//   +0x04 CTRL (wo): [0] start, [1] 1 = write / 0 = read, [7:4] words (1..8); ignored while busy
//   +0x08 STATUS (ro): [0] busy, [11:8] words the last read got
//   +0x0C CYCLES (ro): clocks from the command to the end of the last burst (CS# low time + 1)
//   +0x20 + 4*i (rw): WBUF[i], i < 8, word i to write
//   +0x40 + 4*i (ro): RBUF[i], word i read
// Throwaway; not part of the package.
module hram_burst #(
    parameter BASE = 32'h0000_5000
) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r,
    output reg        bus_ack,
    output            hit,
    output            ck,
    output            cs_n,
    output     [7:0]  dq_o,
    output            dq_oe,
    input      [7:0]  dq_i,
    output            rwds_o,
    output            rwds_oe,
    input             rwds_i
);
    wire [29:0] rel = bus_adr - BASE[31:2];
    assign hit = (bus_adr >= BASE[31:2]) && (rel < 30'd24);

    reg [21:0] addr = 22'd0;
    reg [15:0] wbuf [0:7];
    reg [15:0] rbuf [0:7];
    reg        go = 1'b0, wr = 1'b0, busy = 1'b0;
    reg [3:0]  len = 4'd0, widx = 4'd0, ridx = 4'd0;
    reg [15:0] cyc = 16'd0;
    wire       cmd_ready, wd_ready, rd_valid, done;
    wire [15:0] rd_data;

    hyperram_ctrl ctrl (
        .clk(clk), .rst(rst), .cmd_valid(go), .cmd_ready(cmd_ready), .cmd_write(wr), .cmd_addr(addr),
        .cmd_len(len), .wd_ready(wd_ready), .wd_data(wbuf[widx[2:0]]), .rd_valid(rd_valid), .rd_data(rd_data),
        .done(done), .ck(ck), .cs_n(cs_n), .dq_o(dq_o), .dq_oe(dq_oe), .dq_i(dq_i),
        .rwds_o(rwds_o), .rwds_oe(rwds_oe), .rwds_i(rwds_i));

    always @(posedge clk) begin
        bus_ack <= !rst && bus_stb && !bus_ack;
        if (rel == 30'd0)                    bus_dat_r <= hit ? {10'd0, addr} : 32'd0;
        else if (rel == 30'd2)               bus_dat_r <= hit ? {20'd0, ridx, 7'd0, busy} : 32'd0;
        else if (rel == 30'd3)               bus_dat_r <= hit ? {16'd0, cyc} : 32'd0;
        else if (rel >= 30'd8 && rel < 30'd16) bus_dat_r <= hit ? {16'd0, wbuf[rel[2:0]]} : 32'd0;
        else if (rel >= 30'd16)              bus_dat_r <= hit ? {16'd0, rbuf[rel[2:0]]} : 32'd0;
        else                                 bus_dat_r <= 32'd0;
        if (hit && bus_stb && bus_we && !bus_ack && !busy) begin
            if (rel == 30'd0) addr <= bus_dat_w[21:0];
            if (rel >= 30'd8 && rel < 30'd16) wbuf[rel[2:0]] <= bus_dat_w[15:0];
            if (rel == 30'd1 && bus_dat_w[0]) begin
                go <= 1'b1; busy <= 1'b1; wr <= bus_dat_w[1]; len <= bus_dat_w[7:4]; widx <= 4'd0; ridx <= 4'd0;
                cyc <= 16'd0;
            end
        end
        if (go && cmd_ready) go <= 1'b0;
        if (wd_ready) widx <= widx + 1'b1;
        if (rd_valid) begin
            rbuf[ridx[2:0]] <= rd_data; ridx <= ridx + 1'b1;
        end
        if (busy && !done) cyc <= cyc + 1'b1;
        if (done) busy <= 1'b0;
        if (rst) begin
            go <= 1'b0; busy <= 1'b0;
        end
    end
endmodule
