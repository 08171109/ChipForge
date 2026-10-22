module tt_um_cf_sobel_fast (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // ---------------------------------------------------------------
    // window9_v1 : binary sobel
    //   IDLE: window starts only when in_valid && start_window
    //   9 accepted bytes row-major 3x3, valid gaps allowed
    //   out_valid pulse at L = 2 after the 9th accepted byte
    //   back to IDLE at the pulse edge -> II = 11
    //   active-low SYNCHRONOUS reset (single clock edge), ena=0 aborts
    // ---------------------------------------------------------------

    localparam [1:0] S_IDLE  = 2'd0,
                     S_COLL  = 2'd1,
                     S_CALC1 = 2'd2,   // cycle 1 after 9th sample
                     S_OUT   = 2'd3;   // cycle 2 : out_valid pulse

    reg [1:0] state;
    reg [3:0] cnt;
    reg [7:0] p0, p1, p2, p3, p4, p5, p6, p7, p8;
    reg [7:0] uo_r;
    reg       out_valid_r;

    wire in_valid  = uio_in[0];
    wire start_win = uio_in[1];
    // uio_in[3:2] = mode : ignored per frozen spec

    wire aborted    = (!rst_n) | (!ena);
    wire collecting = (state == S_COLL);

    wire ready  = (~aborted) & ((state == S_IDLE) | collecting);
    wire busy   = (~aborted) & (state != S_IDLE);
    wire accept = ready & in_valid;

    // ---- sobel arithmetic, |G| <= 1020 -> 12 bits ----
    wire signed [11:0] gx = ($signed({4'b0000, p2}) - $signed({4'b0000, p0}))
                          + (($signed({4'b0000, p5}) - $signed({4'b0000, p3})) <<< 1)
                          + ($signed({4'b0000, p8}) - $signed({4'b0000, p6}));

    wire signed [11:0] gy = ($signed({4'b0000, p0}) - $signed({4'b0000, p6}))
                          + (($signed({4'b0000, p1}) - $signed({4'b0000, p7})) <<< 1)
                          + ($signed({4'b0000, p2}) - $signed({4'b0000, p8}));

    wire [11:0] ax  = gx[11] ? (~gx + 12'd1) : gx;
    wire [11:0] ay  = gy[11] ? (~gy + 12'd1) : gy;
    wire [12:0] mag = {1'b0, ax} + {1'b0, ay};

    wire [7:0] cmp_pix = (mag > 13'd160) ? 8'hFF : 8'h00;   // strict >

    initial begin
        state       = S_IDLE;
        cnt         = 4'd0;
        p0 = 8'd0; p1 = 8'd0; p2 = 8'd0;
        p3 = 8'd0; p4 = 8'd0; p5 = 8'd0;
        p6 = 8'd0; p7 = 8'd0; p8 = 8'd0;
        uo_r        = 8'd0;
        out_valid_r = 1'b0;
    end

    always @(posedge clk) begin
        if (aborted) begin
            state       <= S_IDLE;
            cnt         <= 4'd0;
            p0 <= 8'd0; p1 <= 8'd0; p2 <= 8'd0;
            p3 <= 8'd0; p4 <= 8'd0; p5 <= 8'd0;
            p6 <= 8'd0; p7 <= 8'd0; p8 <= 8'd0;
            uo_r        <= 8'd0;
            out_valid_r <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    out_valid_r <= 1'b0;
                    if (accept && start_win) begin
                        p0    <= ui_in;           // p00
                        cnt   <= 4'd1;
                        state <= S_COLL;
                    end
                end

                S_COLL: begin
                    out_valid_r <= 1'b0;
                    if (accept && start_win) begin
                        // new start replaces the partial window
                        p0    <= ui_in;
                        cnt   <= 4'd1;
                    end else if (accept) begin
                        case (cnt)
                            4'd1: p1 <= ui_in;
                            4'd2: p2 <= ui_in;
                            4'd3: p3 <= ui_in;
                            4'd4: p4 <= ui_in;
                            4'd5: p5 <= ui_in;
                            4'd6: p6 <= ui_in;
                            4'd7: p7 <= ui_in;
                            4'd8: p8 <= ui_in;
                            default: ;
                        endcase
                        if (cnt == 4'd8) begin
                            state <= S_CALC1;     // 9th accepted byte
                        end else begin
                            cnt <= cnt + 4'd1;
                        end
                    end
                end

                S_CALC1: begin                    // cycle 1 after 9th sample
                    uo_r        <= cmp_pix;
                    out_valid_r <= 1'b0;
                    state       <= S_OUT;
                end

                S_OUT: begin                      // cycle 2 : pulse
                    out_valid_r <= 1'b1;
                    state       <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    assign uio_oe  = 8'hF0;                                    // 240
    assign uio_out = {1'b0, busy, out_valid_r, ready, 4'b0000};
    assign uo_out  = out_valid_r ? uo_r : 8'h00;

endmodule
