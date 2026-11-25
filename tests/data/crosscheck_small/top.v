// A small design for the crosscheck tests: a 4-clock reset, the UART bridge and one slave (toy).
module top #(parameter [31:0] DESIGN_ID = 32'd0) (input clk, input uart_rx, output uart_tx, input [1:0] btn);
    localparam [29:0] LATE = 30'h3fff_ffff;  // tests make this word answer after a write to it (late <= 1)
    reg [2:0] por = 3'd0;
    wire rst = !por[2];
    always @(posedge clk) if (rst) por <= por + 1'b1;
    wire [29:0] adr;
    wire [31:0] dat_w;
    wire we, stb;
    reg [31:0] dat_r;
    reg ack;
    uartbone_bridge #(.CLK_HZ(27_000_000), .BAUD(115200)) bridge (
        .clk(clk), .rst(rst), .uart_rx(uart_rx), .uart_tx(uart_tx),
        .bus_adr(adr), .bus_dat_w(dat_w), .bus_dat_r(dat_r), .bus_we(we), .bus_stb(stb), .bus_ack(ack));
    reg [3:0] data;
    reg [7:0] mode;
    reg [31:0] spare;
    reg late;
    always @(posedge clk) begin
        ack <= stb && !ack;
        if (rst) begin
            ack <= 1'b0; data <= 4'd0; mode <= 8'd0; spare <= 32'd0; late <= 1'b0;
        end else if (stb && !ack && we) case (adr)
            30'h400: data <= dat_w[3:0];
            30'h402: spare <= dat_w;
            30'h403: mode <= dat_w[7:0];
            LATE: late <= 1'b0;
            default: ;
        endcase
        case (adr)
            30'h0: dat_r <= 32'h4e50_5131;
            30'h1: dat_r <= 32'h0001_0000;
            30'h400: dat_r <= {28'd0, data};
            30'h401: dat_r <= {30'd0, btn};
            30'h402: dat_r <= spare;
            30'h403: dat_r <= {24'd0, mode};
            LATE: dat_r <= late ? 32'd0 : 32'hdead_beef;
            default: dat_r <= 32'hdead_beef;
        endcase
    end
endmodule
