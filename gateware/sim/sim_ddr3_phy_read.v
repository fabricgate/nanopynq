// Two ddr3_phy_slow (IOBFF, as the Tang Mega 138K Pro's ddr3_top used it in stage 1) on one DQ bus: plain capture registers
// (IDDR=0) and IDDR in the IO blocks (IDDR=1). test_ddr3_phy_read.py drives DQ and checks that both read the
// same beats for every read delay.
module sim_ddr3_phy_read (
    input              clk,
    input              phy_rd,
    input       [11:0] phy_rd_delay,
    input       [31:0] tb_dq,
    input              tb_dq_en,
    output             ce,
    output             rvalid0,
    output             rvalid1,
    output     [255:0] rdata0,
    output     [255:0] rdata1
);
    wire [31:0] dq;
    assign dq = tb_dq_en ? tb_dq : 32'bz;
    wire [3:0] dqs0, dqs_n0, dqs1, dqs_n1;
    wire       ce1;

    ddr3_phy_slow #(.DQ_W(32), .ROW_W(15), .BA_W(3), .CL(6), .CWL(6), .DW(3), .IOBFF(1), .IDDR(0)) phy0 (
        .clk(clk), .ce(ce), .dqs_in(),
        .phy_reset_n(1'b1), .phy_cke(1'b1), .phy_odt(1'b0), .phy_cmd(3'b111), .phy_addr(15'd0), .phy_ba(3'd0),
        .phy_wr(1'b0), .phy_wr_ph(2'd0), .phy_wdata(256'd0), .phy_wmask(32'd0),
        .phy_rd(phy_rd), .phy_rd_ph(2'd0), .phy_rd_delay(phy_rd_delay), .phy_wr_shift(2'd0),
        .phy_rvalid(rvalid0), .phy_rdata(rdata0), .phy_ready(),
        .ddr_ck(), .ddr_ck_n(), .ddr_reset_n(), .ddr_cke(), .ddr_cs_n(), .ddr_ras_n(), .ddr_cas_n(), .ddr_we_n(),
        .ddr_odt(), .ddr_ba(), .ddr_addr(), .ddr_dm(), .ddr_dqs(dqs0), .ddr_dqs_n(dqs_n0), .ddr_dq(dq));

    ddr3_phy_slow #(.DQ_W(32), .ROW_W(15), .BA_W(3), .CL(6), .CWL(6), .DW(3), .IOBFF(1), .IDDR(1)) phy1 (
        .clk(clk), .ce(ce1), .dqs_in(),
        .phy_reset_n(1'b1), .phy_cke(1'b1), .phy_odt(1'b0), .phy_cmd(3'b111), .phy_addr(15'd0), .phy_ba(3'd0),
        .phy_wr(1'b0), .phy_wr_ph(2'd0), .phy_wdata(256'd0), .phy_wmask(32'd0),
        .phy_rd(phy_rd), .phy_rd_ph(2'd0), .phy_rd_delay(phy_rd_delay), .phy_wr_shift(2'd0),
        .phy_rvalid(rvalid1), .phy_rdata(rdata1), .phy_ready(),
        .ddr_ck(), .ddr_ck_n(), .ddr_reset_n(), .ddr_cke(), .ddr_cs_n(), .ddr_ras_n(), .ddr_cas_n(), .ddr_we_n(),
        .ddr_odt(), .ddr_ba(), .ddr_addr(), .ddr_dm(), .ddr_dqs(dqs1), .ddr_dqs_n(dqs_n1), .ddr_dq(dq));
endmodule
