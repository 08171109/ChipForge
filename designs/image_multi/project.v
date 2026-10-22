module tt_um_cf_image_multi (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    localparam [1:0] S_IDLE    = 2'd0;
    localparam [1:0] S_COLLECT = 2'd1;
    localparam [1:0] S_CALC1   = 2'd2;
    localparam [1:0] S_OUT     = 2'd3;

    reg  [1:0] state;
    reg  [7:0] p00, p01, p02, p10, p11, p12, p20, p21, p22;
    reg  [3:0] cnt;
    reg  [1:0] mode_r;
    reg  [7:0] uo_r;
    reg        in_ready_r, busy_r, out_valid_r;

    wire in_valid = uio_in[0];
    wire start_w  = uio_in[1];

    // Signed 12-bit views of the nine collected pixels
    wire signed [11:0] P00 = $signed({4'b0, p00});
    wire signed [11:0] P01 = $signed({4'b0, p01});
    wire signed [11:0] P02 = $signed({4'b0, p02});
    wire signed [11:0] P10 = $signed({4'b0, p10});
    wire signed [11:0] P11 = $signed({4'b0, p11});
    wire signed [11:0] P12 = $signed({4'b0, p12});
    wire signed [11:0] P20 = $signed({4'b0, p20});
    wire signed [11:0] P21 = $signed({4'b0, p21});
    wire signed [11:0] P22 = $signed({4'b0, p22});

    // ---------------- Sobel binary (mode 0) ----------------
    wire signed [11:0] gx = (P02 - P00) + (P12 - P10) + (P12 - P10) + (P22 - P20);
    wire signed [11:0] gy = (P00 - P20) + (P01 - P21) + (P01 - P21) + (P02 - P22);
    wire [11:0] agx = gx[11] ? (~gx + 12'd1) : gx[11:0];
    wire [11:0] agy = gy[11] ? (~gy + 12'd1) : gy[11:0];
    wire [12:0] mag = {1'b0, agx} + {1'b0, agy};
    wire [7:0]  sobel_px = (mag > 13'd160) ? 8'hFF : 8'h00;

    // ---------------- Gaussian blur (mode 1) ----------------
    wire [11:0] bsum = p00 + {p01, 1'b0} + p02
                     + {p10, 1'b0} + {p11, 2'b0} + {p12, 1'b0}
                     + p20 + {p21, 1'b0} + p22;
    wire [7:0]  blur_px = bsum[11:4];

    // ---------------- Sharpen (mode 2) ----------------
    wire signed [11:0] shsum = (5 * P11) - P01 - P10 - P12 - P21;
    wire [7:0]  sharp_px = (shsum < 0) ? 8'd0
                         : (shsum > 12'sd255) ? 8'hFF
                         : shsum[7:0];

    // ---------------- mode select ----------------
    wire [7:0] sel = (mode_r == 2'd0) ? sobel_px :
                     (mode_r == 2'd1) ? blur_px  :
                     (mode_r == 2'd2) ? sharp_px : 8'h00;

    // ---------------- outputs ----------------
    assign uio_oe  = 8'hF0;
    assign uio_out = {1'b0, busy_r, out_valid_r, in_ready_r, 4'b0000};
    assign uo_out  = out_valid_r ? uo_r : 8'h00;

    // ---------------- sequential ----------------
    always @(posedge clk) begin
        if (!rst_n || !ena) begin
            state       <= S_IDLE;
            cnt         <= 4'd0;
            p00 <= 8'd0; p01 <= 8'd0; p02 <= 8'd0;
            p10 <= 8'd0; p11 <= 8'd0; p12 <= 8'd0;
            p20 <= 8'd0; p21 <= 8'd0; p22 <= 8'd0;
            mode_r      <= 2'd0;
            uo_r        <= 8'd0;
            in_ready_r  <= 1'b0;
            busy_r      <= 1'b0;
            out_valid_r <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    in_ready_r  <= 1'b1;
                    busy_r      <= 1'b0;
                    out_valid_r <= 1'b0;
                    if (in_valid && in_ready_r && start_w) begin
                        p00    <= ui_in;
                        cnt    <= 4'd1;
                        mode_r <= uio_in[3:2];
                        busy_r <= 1'b1;
                        state  <= S_COLLECT;
                    end
                end

                S_COLLECT: begin
                    in_ready_r  <= 1'b1;
                    busy_r      <= 1'b1;
                    out_valid_r <= 1'b0;
                    if (in_valid && in_ready_r) begin
                        if (start_w) begin
                            // new window replaces partially collected window
                            p00    <= ui_in;
                            cnt    <= 4'd1;
                            mode_r <= uio_in[3:2];
                        end else begin
                            case (cnt)
                                4'd1: begin p01 <= ui_in; cnt <= 4'd2; end
                                4'd2: begin p02 <= ui_in; cnt <= 4'd3; end
                                4'd3: begin p10 <= ui_in; cnt <= 4'd4; end
                                4'd4: begin p11 <= ui_in; cnt <= 4'd5; end
                                4'd5: begin p12 <= ui_in; cnt <= 4'd6; end
                                4'd6: begin p20 <= ui_in; cnt <= 4'd7; end
                                4'd7: begin p21 <= ui_in; cnt <= 4'd8; end
                                default: begin // cnt == 8 -> 9th sample
                                    p22        <= ui_in;
                                    cnt        <= 4'd9;
                                    in_ready_r <= 1'b0;
                                    busy_r     <= 1'b1;
                                    state      <= S_CALC1;
                                end
                            endcase
                        end
                    end
                end

                S_CALC1: begin
                    uo_r        <= sel;
                    out_valid_r <= 1'b0;
                    in_ready_r  <= 1'b0;
                    busy_r      <= 1'b1;
                    state       <= S_OUT;
                end

                S_OUT: begin
                    out_valid_r <= 1'b1;
                    in_ready_r  <= 1'b1;
                    busy_r      <= 1'b0;
                    state       <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
