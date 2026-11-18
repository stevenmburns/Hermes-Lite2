// Variable-decimation CIC for one I/Q pair, with the comb section in block RAM.
//
// The arithmetic matches two instances of varcic.v bit for bit.  The integrators
// run at the input rate and stay in registers.  The combs only run once per output
// sample, so one pair of subtractors shares their state from an M9K memory.
//
// In varcic.v every comb stage registers its output, so for stage i > 0:
//
//     y[i][n] = y[i-1][n-1] - y[i-1][n-2]
//     y[0][n] = z[n] - z[n-1]        (z is the last integrator's output)
//
// Each stage output is kept for two output samples, in two banks selected by the
// parity of n.  Stages are processed from last to first, so y[i-1][n-2] is read
// before y[i-1][n] overwrites it.
//
// One output sample takes 3 * (STAGES - 1) + 3 clocks, which is 15 for five stages.
// The fastest supported output period is 20 clocks (CICRATE 10, decimation 2).

module varcic_mem (
  input                             rst_all,
  input                             clock,
  input                             in_strobe,
  input             [5:0]           decimation,
  input      signed [IN_WIDTH-1:0]  in_i,
  input      signed [IN_WIDTH-1:0]  in_q,
  output reg                        out_strobe,
  output reg signed [OUT_WIDTH-1:0] out_i,
  output reg signed [OUT_WIDTH-1:0] out_q
);

  parameter STAGES    = 5;
  parameter IN_WIDTH  = 16;
  parameter ACC_WIDTH = 43;
  parameter OUT_WIDTH = 16;
  parameter CICRATE   = 5;

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
  // Integrators
  //----------------------------------------------------------------------------
  wire signed [ACC_WIDTH-1:0] integ_i [0:STAGES];
  wire signed [ACC_WIDTH-1:0] integ_q [0:STAGES];

  assign integ_i[0] = in_i;
  assign integ_q[0] = in_q;

  genvar s;
  generate
    for (s = 0; s < STAGES; s = s + 1) begin : INTEGRATORS
      cic_integrator #(ACC_WIDTH) integrator_i (
        .clock(clock), .strobe(in_strobe), .in_data(integ_i[s]), .out_data(integ_i[s+1])
      );
      cic_integrator #(ACC_WIDTH) integrator_q (
        .clock(clock), .strobe(in_strobe), .in_data(integ_q[s]), .out_data(integ_q[s+1])
      );
    end
  endgenerate

  //----------------------------------------------------------------------------
  // Comb state memory: {bank, stage} holds stage outputs, Z_ADDR holds z[n-1]
  //----------------------------------------------------------------------------
  localparam [4:0] Z_ADDR = 5'd16;

  (* ramstyle = "M9K" *) reg [2*ACC_WIDTH-1:0] comb_mem [0:31];
  reg  [2*ACC_WIDTH-1:0] mem_q = {2*ACC_WIDTH{1'b0}};
  reg  [4:0]             raddr;
  reg  [4:0]             waddr;
  reg  [2*ACC_WIDTH-1:0] wdata;
  reg                    wen;

  integer m;
  initial for (m = 0; m < 32; m = m + 1) comb_mem[m] = {2*ACC_WIDTH{1'b0}};

  always @(posedge clock) begin
    mem_q <= comb_mem[raddr];
    if (wen) comb_mem[waddr] <= wdata;
  end

  //----------------------------------------------------------------------------
  // Comb sequencer
  //----------------------------------------------------------------------------
  localparam [2:0] IDLE     = 3'd0,
                   READ_A   = 3'd1,  // y[stage-1][n-1]
                   READ_B   = 3'd2,  // y[stage-1][n-2]
                   WRITE_Y  = 3'd3,
                   READ_Z   = 3'd4,  // z[n-1]
                   WRITE_Y0 = 3'd5,
                   WRITE_Z  = 3'd6;

  reg [2:0]           state = IDLE;
  reg [2:0]           stage = 3'd0;
  reg                 bank  = 1'b0;
  reg [ACC_WIDTH-1:0] z_i   = {ACC_WIDTH{1'b0}};
  reg [ACC_WIDTH-1:0] z_q   = {ACC_WIDTH{1'b0}};
  reg [ACC_WIDTH-1:0] a_i   = {ACC_WIDTH{1'b0}};
  reg [ACC_WIDTH-1:0] a_q   = {ACC_WIDTH{1'b0}};

  wire [ACC_WIDTH-1:0] q_i = mem_q[2*ACC_WIDTH-1:ACC_WIDTH];
  wire [ACC_WIDTH-1:0] q_q = mem_q[ACC_WIDTH-1:0];
  wire [2:0]           source_stage = stage - 3'd1;

  always @* begin
    raddr = {1'b0, ~bank, source_stage};
    waddr = {1'b0, bank, stage};
    wdata = {a_i - q_i, a_q - q_q};
    wen   = 1'b0;
    case (state)
      READ_B:   raddr = {1'b0, bank, source_stage};
      WRITE_Y:  wen   = 1'b1;
      READ_Z:   raddr = Z_ADDR;
      WRITE_Y0: begin
        waddr = {1'b0, bank, 3'd0};
        wdata = {z_i - q_i, z_q - q_q};
        wen   = 1'b1;
      end
      WRITE_Z:  begin
        waddr = Z_ADDR;
        wdata = {z_i, z_q};
        wen   = 1'b1;
      end
      default: ;
    endcase
  end

  always @(posedge clock) begin
    if (rst_all) begin
      state <= IDLE;
    end else begin
      case (state)
        IDLE: if (out_strobe) begin
          z_i   <= integ_i[STAGES];
          z_q   <= integ_q[STAGES];
          bank  <= ~bank;
          stage <= STAGES - 1;
          state <= READ_A;
        end
        READ_A: state <= READ_B;
        READ_B: begin
          a_i   <= q_i;
          a_q   <= q_q;
          state <= WRITE_Y;
        end
        WRITE_Y: begin
          stage <= stage - 3'd1;
          state <= (stage == 3'd1) ? READ_Z : READ_A;
        end
        READ_Z:   state <= WRITE_Y0;
        WRITE_Y0: state <= WRITE_Z;
        default:  state <= IDLE;
      endcase
    end
  end

  //----------------------------------------------------------------------------
  // Output rounding, as in varcic.v
  //----------------------------------------------------------------------------
  localparam GROWTH_0 = (CICRATE == 5) ? 12 : (CICRATE == 10 || CICRATE == 13) ?  5 :  8;
  localparam GROWTH_1 = (CICRATE == 5) ? 17 : (CICRATE == 10 || CICRATE == 13) ? 10 : 13;
  localparam GROWTH_2 = (CICRATE == 5) ? 22 : (CICRATE == 10 || CICRATE == 13) ? 15 : 18;
  localparam GROWTH_3 = (CICRATE == 5) ? 27 : (CICRATE == 10 || CICRATE == 13) ? 20 : 23;

  localparam [5:0] DECIM_0 = (CICRATE == 5) ?  5 : (CICRATE == 10 || CICRATE == 13) ? 2 :  3;
  localparam [5:0] DECIM_1 = (CICRATE == 5) ? 10 : (CICRATE == 10 || CICRATE == 13) ? 4 :  6;
  localparam [5:0] DECIM_2 = (CICRATE == 5) ? 20 : (CICRATE == 10 || CICRATE == 13) ? 8 : 12;

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

  // The last stage is computed first.  Its result reaches the output after the
  // FIR has captured the previous value, which is the delay varcic.v produces with
  // its output register.
  always @(posedge clock) begin
    if (state == WRITE_Y && stage == STAGES - 1) begin
      out_i <= rounded(a_i - q_i);
      out_q <= rounded(a_q - q_q);
    end
  end

endmodule
