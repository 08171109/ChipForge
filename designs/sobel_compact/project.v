module tt_um_cf_sobel_compact (
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
    localparam [1:0] S_COMPUTE = 2'd2;

    wire in_valid     = uio_in[0];
    wire start_window = uio_in[1];

    reg [1:0]  state;
    reg [3:0]  cnt;
    reg [4:0]  step;
    reg [7:0]  uo_r;
    reg        out_valid_r;

    reg [7:0] p00, p01, p02;
    reg [7:0] p10, p11, p12;
    reg [7:0] p20, p21, p22;

    wire signed [12:0] D02_00 = $signed({1'b0, p02}) - $signed({1'b0, p00});
    wire signed [12:0] D12_10 = $signed({1'b0, p12}) - $signed({1'b0, p10});
    wire signed [12:0] D22_20 = $signed({1'b0, p22}) - $signed({1'b0, p20});
    wire signed [12:0] D00_20 = $signed({1'b0, p00}) - $signed({1'b0, p20});
    wire signed [12:0] D01_21 = $signed({1'b0, p01}) - $signed({1'b0, p21});
    wire signed [12:0] D02_22 = $signed({1'b0, p02}) - $signed({1'b0, p22});

    reg signed [12:0] acc;
    reg signed [12:0] gx_r;
    reg signed [12:0] gy_r;
    reg        [12:0] ax_r;
    reg        [12:0] ay_r;
    reg        [12:0] sum_r;
    reg        [7:0]  cmp_r;

    always @(posedge clk) begin
        if (!rst_n || !ena) begin
            state       <= S_IDLE;
            cnt         <= 4'd0;
            step        <= 5'd0;
            uo_r        <= 8'h00;
            out_valid_r <= 1'b0;
            acc         <= 13'sd0;
            gx_r        <= 13'sd0;
            gy_r        <= 13'sd0;
            ax_r        <= 13'd0;
            ay_r        <= 13'd0;
            sum_r       <= 13'd0;
            cmp_r       <= 8'd0;
        end else begin
            case (state)
                S_IDLE: begin
                    out_valid_r <= 1'b0;
                    if (in_valid && start_window) begin
                        p00   <= ui_in;
                        cnt   <= 4'd1;
                        state <= S_COLLECT;
                    end
                end

                S_COLLECT: begin
                    out_valid_r <= 1'b0;
                    if (in_valid) begin
                        if (start_window) begin
                            p00 <= ui_in;
                            cnt <= 4'd1;
                        end else begin
                            case (cnt)
                                4'd1: p01 <= ui_in;
                                4'd2: p02 <= ui_in;
                                4'd3: p10 <= ui_in;
                                4'd4: p11 <= ui_in;
                                4'd5: p12 <= ui_in;
                                4'd6: p20 <= ui_in;
                                4'd7: p21 <= ui_in;
                                4'd8: p22 <= ui_in;
                                default: ;
                            endcase
                            if (cnt == 4'd8) begin
                                state <= S_COMPUTE;
                                step  <= 5'd1;
                                cnt   <= 4'd9;
                            end else begin
                                cnt <= cnt + 4'd1;
                            end
                        end
                    end
                end

                S_COMPUTE: begin
                    step <= step + 5'd1;
                    case (step)
                        5'd1:  acc <= D02_00;
                        5'd2:  acc <= acc + (D12_10 <<< 1);
                        5'd3:  begin
                                   gx_r <= acc + D22_20;
                                   acc  <= D00_20;
                               end
                        5'd4:  acc <= acc + (D01_21 <<< 1);
                        5'd5:  gy_r <= acc + D02_22;
                        5'd6:  ax_r <= gx_r[12] ? (~gx_r + 13'd1) : gx_r;
                        5'd7:  ay_r <= gy_r[12] ? (~gy_r + 13'd1) : gy_r;
                        5'd8:  sum_r <= ax_r + ay_r;
                        5'd9:  cmp_r <= (sum_r > 13'd160) ? 8'd255 : 8'd0;
                        5'd20: uo_r <= cmp_r;
                        5'd21: begin
                                   out_valid_r <= 1'b1;
                                   state       <= S_IDLE;
                               end
                        default: ;
                    endcase
                end

                default: state <= S_IDLE;
            endcase
        end
    end

    wire in_ready  = rst_n & ena & ((state == S_IDLE) || (state == S_COLLECT));
    wire busy      = rst_n & ena & ((state == S_COLLECT) || (state == S_COMPUTE));
    wire out_valid = out_valid_r & rst_n & ena;

    assign uo_out  = out_valid ? uo_r : 8'h00;
    assign uio_out = {1'b0, busy, out_valid, in_ready, 4'b0000};
    assign uio_oe  = 8'hF0;

endmodule
