// Variable-decimation CIC shared by four receivers, with comb state in block RAM.
//
// The arithmetic matches varcic.v bit for bit.  All four receivers run from the
// same strobes.  Each 172-bit memory word holds the I and Q state of two receivers,
// which takes five M9Ks side by side, and the two receiver pairs take turns on four
// shared subtractors.  One output sample takes 20 clocks, so the output period must
// be at least 21 clocks.  At 76.8 MHz the shortest period is 25 clocks.
//
// For comb stage i > 0, y[i][n] = y[i-1][n-1] - y[i-1][n-2].  Stage 0 computes
// y[0][n] = z[n] - z[n-1], where z is the last integrator's output.  Each stage
// output is kept for two output samples, in banks selected by the parity of n.
// Stages run from last to first, so y[i-1][n-2] is read before it is overwritten.

module varcic_quad (
  input                             rst_all,
  input                             clock,
  input                             in_strobe,
  input             [5:0]           decimation,
  input      signed [IN_WIDTH-1:0]  in_i0, in_q0, in_i1, in_q1,
  input      signed [IN_WIDTH-1:0]  in_i2, in_q2, in_i3, in_q3,
  output reg                        out_strobe,
  output     signed [OUT_WIDTH-1:0] out_i0, out_q0, out_i1, out_q1,
  output     signed [OUT_WIDTH-1:0] out_i2, out_q2, out_i3, out_q3
);

  parameter STAGES    = 5;
  parameter IN_WIDTH  = 16;
  parameter OUT_WIDTH = 16;
  parameter CICRATE   = 5;

  localparam ACC_WIDTH = (CICRATE == 10 || CICRATE == 13) ? 36 : (CICRATE == 5) ? 43 : 39;
  localparam WORD      = 4 * ACC_WIDTH;

  //----------------------------------------------------------------------------
  // Decimation control
  //----------------------------------------------------------------------------
  reg [15:0] sample_no = 16'd0;

  always @(posedge clock) begin
    if (rst_all) begin
      sample_no  <= 16'd0;
      out_strobe <= 1'b0;
    end else if (in_strobe) begin
      if (sample_no == {10'b0, (decimation - 6'h1)}) begin
        sample_no  <= 16'd0;
        out_strobe <= 1'b1;
      end else begin
        sample_no  <= sample_no + 16'd1;
        out_strobe <= 1'b0;
      end
    end else begin
      out_strobe <= 1'b0;
    end
  end

  //----------------------------------------------------------------------------
  // Integrators.  Channel index is {pair, receiver in pair, Q}.
  //----------------------------------------------------------------------------
  wire signed [ACC_WIDTH-1:0] integ [0:7][0:STAGES];

  assign integ[0][0] = in_i0;
  assign integ[1][0] = in_q0;
  assign integ[2][0] = in_i1;
  assign integ[3][0] = in_q1;
  assign integ[4][0] = in_i2;
  assign integ[5][0] = in_q2;
  assign integ[6][0] = in_i3;
  assign integ[7][0] = in_q3;

  genvar ch, s;
  generate
    for (ch = 0; ch < 8; ch = ch + 1) begin : CHANNEL
      for (s = 0; s < STAGES; s = s + 1) begin : STAGE
        cic_integrator #(ACC_WIDTH) integrator (
          .clock(clock), .strobe(in_strobe),
          .in_data(integ[ch][s]), .out_data(integ[ch][s+1])
        );
      end
    end
  endgenerate

  //----------------------------------------------------------------------------
  // Comb state memory, addressed {pair, bank, stage}
  //----------------------------------------------------------------------------
  (* ramstyle = "M9K" *) reg [WORD-1:0] comb_mem [0:31];
  reg  [WORD-1:0] mem_q = {WORD{1'b0}};
  reg  [4:0]      raddr;
  reg  [4:0]      waddr;
  reg             wen;
  wire [WORD-1:0] wdata;

  integer m;
  initial for (m = 0; m < 32; m = m + 1) comb_mem[m] = {WORD{1'b0}};

  always @(posedge clock) begin
    mem_q <= comb_mem[raddr];
    if (wen) comb_mem[waddr] <= wdata;
  end

  //----------------------------------------------------------------------------
  // Pipelined schedule.  Each pair issues nine reads, one per clock: A and B for
  // stages 4 to 1, then z[n-1].  A stage's write lands two clocks after its first
  // read, so writes never collide.
  //----------------------------------------------------------------------------
  localparam [1:0] OP_NONE = 2'd0, OP_A = 2'd1, OP_B = 2'd2, OP_Z = 2'd3;
  localparam [1:0] W_DIFF  = 2'd0, W_Y0 = 2'd1, W_Z  = 2'd2;

  reg        running = 1'b0;
  reg        bank    = 1'b0;
  reg  [4:0] pc      = 5'd0;

  wire       op_pair  = (pc >= 5'd9);
  wire [4:0] op_count = op_pair ? (pc - 5'd9) : pc;
  wire [3:0] op_step  = op_count[3:0];
  wire [1:0] op       = (!running || pc >= 5'd18) ? OP_NONE :
                        (op_step == 4'd8)         ? OP_Z :
                        op_step[0]                ? OP_B : OP_A;
  wire [2:0] op_stage = 3'd4 - op_step[3:1];
  wire [2:0] op_src   = op_stage - 3'd1;
  wire       start    = !running && out_strobe && !rst_all;

  reg  [1:0] op_d1    = OP_NONE;
  reg  [1:0] op_d2    = OP_NONE;
  reg        pair_d1  = 1'b0;
  reg        pair_d2  = 1'b0;
  reg  [2:0] stage_d1 = 3'd0;

  reg  [1:0] wsel;
  reg        pair_sel;
  reg        capture;

  wire latch_a = (op_d1 == OP_A);

  always @* begin
    raddr    = {op_pair, ~bank, op_src};
    waddr    = {pair_d1, bank, stage_d1};
    wen      = 1'b0;
    wsel     = W_DIFF;
    pair_sel = pair_d1;
    capture  = 1'b0;
    if (op == OP_B) raddr = {op_pair, bank, op_src};
    if (op == OP_Z) raddr = {op_pair, 1'b0, 3'd7};
    if (op_d1 == OP_B) begin
      wen     = 1'b1;
      capture = (stage_d1 == 3'd4);
    end else if (op_d1 == OP_Z) begin
      waddr = {pair_d1, bank, 3'd0};
      wsel  = W_Y0;
      wen   = 1'b1;
    end else if (op_d2 == OP_Z) begin
      waddr    = {pair_d2, 1'b0, 3'd7};
      wsel     = W_Z;
      pair_sel = pair_d2;
      wen      = 1'b1;
    end
  end

  always @(posedge clock) begin
    op_d1    <= rst_all ? OP_NONE : op;
    op_d2    <= rst_all ? OP_NONE : op_d1;
    pair_d1  <= op_pair;
    pair_d2  <= pair_d1;
    stage_d1 <= op_stage;
    if (rst_all) begin
      running <= 1'b0;
      pc      <= 5'd0;
    end else if (start) begin
      running <= 1'b1;
      pc      <= 5'd0;
      bank    <= ~bank;
    end else if (running) begin
      if (pc == 5'd19) running <= 1'b0;
      pc <= pc + 5'd1;
    end
  end

  //----------------------------------------------------------------------------
  // Output rounding, as in varcic.v
  //----------------------------------------------------------------------------
  localparam GROWTH_0 = (CICRATE == 5) ? 12 : (CICRATE == 10 || CICRATE == 13) ?  5 :  8;
  localparam GROWTH_1 = (CICRATE == 5) ? 17 : (CICRATE == 10 || CICRATE == 13) ? 10 : 13;
  localparam GROWTH_2 = (CICRATE == 5) ? 22 : (CICRATE == 10 || CICRATE == 13) ? 15 : 18;
  localparam GROWTH_3 = (CICRATE == 5) ? 27 : (CICRATE == 10 || CICRATE == 13) ? 20 : 23;

  localparam [5:0] DECIM_0 = (CICRATE == 5) ? 6'd5  : (CICRATE == 10 || CICRATE == 13) ? 6'd2 : 6'd3;
  localparam [5:0] DECIM_1 = (CICRATE == 5) ? 6'd10 : (CICRATE == 10 || CICRATE == 13) ? 6'd4 : 6'd6;
  localparam [5:0] DECIM_2 = (CICRATE == 5) ? 6'd20 : (CICRATE == 10 || CICRATE == 13) ? 6'd8 : 6'd12;

  localparam LSB_0 = IN_WIDTH + GROWTH_0 - OUT_WIDTH;
  localparam LSB_1 = IN_WIDTH + GROWTH_1 - OUT_WIDTH;
  localparam LSB_2 = IN_WIDTH + GROWTH_2 - OUT_WIDTH;
  localparam LSB_3 = IN_WIDTH + GROWTH_3 - OUT_WIDTH;

  function [OUT_WIDTH-1:0] rounded;
    input [ACC_WIDTH-1:0] word;
    begin
      case (decimation)
        DECIM_0: rounded = word[LSB_0+OUT_WIDTH-1:LSB_0] + word[LSB_0-1];
        DECIM_1: rounded = word[LSB_1+OUT_WIDTH-1:LSB_1] + word[LSB_1-1];
        DECIM_2: rounded = word[LSB_2+OUT_WIDTH-1:LSB_2] + word[LSB_2-1];
        default: rounded = word[LSB_3+OUT_WIDTH-1:LSB_3] + word[LSB_3-1];
      endcase
    end
  endfunction

  //----------------------------------------------------------------------------
  // Datapath: four lanes, one per I or Q channel of the selected pair
  //----------------------------------------------------------------------------
  reg [ACC_WIDTH-1:0] z   [0:7];
  reg [OUT_WIDTH-1:0] out [0:7];

  integer k;
  initial for (k = 0; k < 8; k = k + 1) z[k] = {ACC_WIDTH{1'b0}};

  always @(posedge clock) begin
    if (start) for (k = 0; k < 8; k = k + 1) z[k] <= integ[k][STAGES];
  end

  genvar lane;
  generate
    for (lane = 0; lane < 4; lane = lane + 1) begin : LANE
      reg  [ACC_WIDTH-1:0] a = {ACC_WIDTH{1'b0}};
      wire [ACC_WIDTH-1:0] q      = mem_q[(lane+1)*ACC_WIDTH-1:lane*ACC_WIDTH];
      wire [ACC_WIDTH-1:0] z_lane = z[{pair_sel, lane[1:0]}];
      wire [ACC_WIDTH-1:0] diff   = a - q;

      assign wdata[(lane+1)*ACC_WIDTH-1:lane*ACC_WIDTH] =
        (wsel == W_DIFF) ? diff :
        (wsel == W_Y0)   ? z_lane - q : z_lane;

      always @(posedge clock) begin
        if (latch_a) a <= q;
        if (capture) out[{pair_sel, lane[1:0]}] <= rounded(diff);
      end
    end
  endgenerate

  assign out_i0 = out[0];
  assign out_q0 = out[1];
  assign out_i1 = out[2];
  assign out_q1 = out[3];
  assign out_i2 = out[4];
  assign out_q2 = out[5];
  assign out_i3 = out[6];
  assign out_q3 = out[7];

endmodule
