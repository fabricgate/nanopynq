// Two masters onto one sdram_ctrl command port. Master a has priority over b; a master's command is taken
// when its valid and ready are both high at a clock edge (ready = the controller's cmd_ready, and for b
// also "a is not asking"). sdram_ctrl takes one command at a time and always returns a read's rd_valid
// before cmd_ready is high again, so remembering the owner of the last accepted read is enough to steer
// rd_valid. Reset with the same rst as the controller.
module sdram_arb (
    input             clk,
    input             rst,
    // master a (priority)
    input             a_valid,
    output            a_ready,
    input             a_write,
    input      [20:0] a_addr,
    input      [31:0] a_wdata,
    input      [3:0]  a_wmask,
    output            a_rd_valid,
    output     [31:0] a_rd_data,
    // master b
    input             b_valid,
    output            b_ready,
    input             b_write,
    input      [20:0] b_addr,
    input      [31:0] b_wdata,
    input      [3:0]  b_wmask,
    output            b_rd_valid,
    output     [31:0] b_rd_data,
    // to sdram_ctrl
    output            c_valid,
    input             c_ready,
    output            c_write,
    output     [20:0] c_addr,
    output     [31:0] c_wdata,
    output     [3:0]  c_wmask,
    input             c_rd_valid,
    input      [31:0] c_rd_data
);
    reg owner_b = 1'b0;  // the last accepted read came from b

    assign c_valid = a_valid | b_valid;
    assign c_write = a_valid ? a_write : b_write;
    assign c_addr  = a_valid ? a_addr  : b_addr;
    assign c_wdata = a_valid ? a_wdata : b_wdata;
    assign c_wmask = a_valid ? a_wmask : b_wmask;
    assign a_ready = c_ready;
    assign b_ready = c_ready & ~a_valid;

    assign a_rd_valid = c_rd_valid & ~owner_b;
    assign b_rd_valid = c_rd_valid & owner_b;
    assign a_rd_data  = c_rd_data;
    assign b_rd_data  = c_rd_data;

    always @(posedge clk) begin
        if (rst) owner_b <= 1'b0;
        else if (c_valid && c_ready && !c_write) owner_b <= !a_valid;
    end
endmodule
