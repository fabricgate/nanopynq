// Bus slave: maps an 8 MB window at byte address BASE (bus_adr is a word address) onto the SDRAM through
// one master port of sdram_arb. A write is acked once the SDRAM command port took it (wmask = 4'hF), a read
// once its data came back. bus_ack is a 1 clock pulse, bus_dat_r is 0 whenever it is not acking (so it can
// be ORed with other slaves), and nothing is acked outside the window. While init_done = 0 the access is
// not sent: it is acked on the next clock (a read returns 0, a write is dropped), so the bus never hangs.
module sdram_port #(parameter BASE = 32'h0080_0000) (
    input             clk,
    input             rst,
    input      [29:0] bus_adr,
    input      [31:0] bus_dat_w,
    input             bus_we,
    input             bus_stb,
    output reg [31:0] bus_dat_r,
    output reg        bus_ack,
    output            hit,
    input             init_done,
    output            m_valid,
    input             m_ready,
    output            m_write,
    output     [20:0] m_addr,
    output     [31:0] m_wdata,
    output     [3:0]  m_wmask,
    input             m_rd_valid,
    input      [31:0] m_rd_data
);
    localparam [1:0] S_IDLE = 2'd0, S_REQ = 2'd1, S_WAIT = 2'd2;

    reg [1:0] state = S_IDLE;

    assign hit     = bus_adr[29:21] == BASE[31:23];
    assign m_valid = state == S_REQ;
    assign m_write = bus_we;
    assign m_addr  = bus_adr[20:0];
    assign m_wdata = bus_dat_w;
    assign m_wmask = 4'hF;

    always @(posedge clk) begin
        bus_ack   <= 1'b0;
        bus_dat_r <= 32'd0;
        case (state)
            S_IDLE: if (bus_stb && hit && !bus_ack) begin  // stb is still high in the clock of the ack
                if (init_done) state <= S_REQ;
                else bus_ack <= 1'b1;
            end
            S_REQ: if (m_ready) begin
                if (bus_we) begin
                    bus_ack <= 1'b1;
                    state   <= S_IDLE;
                end else state <= S_WAIT;
            end
            default: if (m_rd_valid) begin  // S_WAIT
                bus_ack   <= 1'b1;
                bus_dat_r <= m_rd_data;
                state     <= S_IDLE;
            end
        endcase
        if (rst) begin
            state <= S_IDLE; bus_ack <= 1'b0; bus_dat_r <= 32'd0;
        end
    end
endmodule
