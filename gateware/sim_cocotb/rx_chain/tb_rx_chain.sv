// Production receive chain for hl2b5up_main: two mix2 serving four receiver_nco
// channels, wired and parameterised as radio.v does for a 76.8 MHz clock.
//
// The stimulus and clocks live here rather than in Python, so the simulator runs
// millions of ADC clocks at native speed.  Both clocks change in one process so
// their rising edges coincide, as they do when they come from the same PLL.

`timescale 1ps/1ps

module tb_rx_chain (
  input  logic               rst,
  input  logic               load_stim,
  input  logic        [31:0] phi0,
  input  logic        [31:0] phi1,
  input  logic        [31:0] phi2,
  input  logic        [31:0] phi3,
  input  logic        [ 5:0] rate,
  output logic               clk,
  output logic               clk_2x,
  output logic               out_strobe,
  output logic signed [23:0] ch0_i,
  output logic signed [23:0] ch0_q,
  output logic signed [23:0] ch1_i,
  output logic signed [23:0] ch1_q,
  output logic signed [23:0] ch2_i,
  output logic signed [23:0] ch2_q,
  output logic signed [23:0] ch3_i,
  output logic signed [23:0] ch3_q,
  // Stage probes, used to report where a mismatch first appears
  output logic signed [17:0] mix0_i,
  output logic signed [17:0] mix0_q,
  output logic signed [17:0] mix1_i,
  output logic signed [17:0] mix1_q,
  output logic        [31:0] clk_count
);

  localparam CICRATE  = 5;   // clk_config.vh at CLK_FREQ = 76.8 MHz
  localparam CALCTYPE = 3;   // radio.v for NR <= 5; hl2b5up_main has NR = 4
  localparam STIM_LEN = 65536;

  logic signed [17:0] mix2_i, mix2_q, mix3_i, mix3_q;

  initial begin
    clk    = 1'b0;
    clk_2x = 1'b0;
  end

  always begin
    #3250;
    clk_2x = ~clk_2x;
    if (clk_2x) clk = ~clk;
  end

  // Stimulus replay: Python writes stim.mem, then pulses load_stim.
  logic signed [11:0] stim [0:STIM_LEN-1];
  logic        [15:0] stim_index = 16'd0;
  logic signed [11:0] adc = 12'sd0;
  logic               rst_r = 1'b1;

  always @(posedge load_stim) $readmemh("stim.mem", stim);

  always @(posedge clk) begin
    rst_r <= rst;
    if (rst_r) begin
      stim_index <= 16'd0;
      adc        <= 12'sd0;
      clk_count  <= 32'd0;
    end else begin
      stim_index <= stim_index + 16'd1;
      adc        <= stim[stim_index];
      clk_count  <= clk_count + 32'd1;
    end
  end

  mix2 #(.CALCTYPE(CALCTYPE)) mixer (
    .clk       (clk),
    .clk_2x    (clk_2x),
    .rst       (rst_r),
    .phi0      (phi0),
    .phi1      (phi1),
    .adc       (adc),
    .mixdata0_i(mix0_i),
    .mixdata0_q(mix0_q),
    .mixdata1_i(mix1_i),
    .mixdata1_q(mix1_q)
  );

  mix2 #(.CALCTYPE(CALCTYPE)) mixer2 (
    .clk       (clk),
    .clk_2x    (clk_2x),
    .rst       (rst_r),
    .phi0      (phi2),
    .phi1      (phi3),
    .adc       (adc),
    .mixdata0_i(mix2_i),
    .mixdata0_q(mix2_q),
    .mixdata1_i(mix3_i),
    .mixdata1_q(mix3_q)
  );

`ifdef VARCIC_QUAD
  wire               cic_strobe [0:3];
  wire signed [15:0] cic_i [0:3];
  wire signed [15:0] cic_q [0:3];
  wire               var_strobe;
  wire signed [15:0] var_i [0:3];
  wire signed [15:0] var_q [0:3];

  varcic_quad #(.CICRATE(CICRATE)) shared_varcic (
    .rst_all   (rst_r),
    .clock     (clk),
    .in_strobe (cic_strobe[0]),
    .decimation(rate),
    .in_i0(cic_i[0]), .in_q0(cic_q[0]), .in_i1(cic_i[1]), .in_q1(cic_q[1]),
    .in_i2(cic_i[2]), .in_q2(cic_q[2]), .in_i3(cic_i[3]), .in_q3(cic_q[3]),
    .out_strobe(var_strobe),
    .out_i0(var_i[0]), .out_q0(var_q[0]), .out_i1(var_i[1]), .out_q1(var_q[1]),
    .out_i2(var_i[2]), .out_q2(var_q[2]), .out_i3(var_i[3]), .out_q3(var_q[3])
  );
`endif

  receiver_nco #(.CICRATE(CICRATE)) receiver0 (
    .rst_all   (rst_r),
    .clock     (clk),
    .clock_2x  (clk_2x),
    .rate      (rate),
    .mixdata_I (mix0_i),
    .mixdata_Q (mix0_q),
    .out_strobe(out_strobe),
    .out_data_I(ch0_i),
    .out_data_Q(ch0_q),
    .debug     ()
`ifdef VARCIC_QUAD
    ,
    .cic_strobe(cic_strobe[0]),
    .cic_i     (cic_i[0]),
    .cic_q     (cic_q[0]),
    .var_strobe(var_strobe),
    .var_i     (var_i[0]),
    .var_q     (var_q[0])
`endif
  );

  receiver_nco #(.CICRATE(CICRATE)) receiver1 (
    .rst_all   (rst_r),
    .clock     (clk),
    .clock_2x  (clk_2x),
    .rate      (rate),
    .mixdata_I (mix1_i),
    .mixdata_Q (mix1_q),
    .out_strobe(),
    .out_data_I(ch1_i),
    .out_data_Q(ch1_q),
    .debug     ()
`ifdef VARCIC_QUAD
    ,
    .cic_strobe(cic_strobe[1]),
    .cic_i     (cic_i[1]),
    .cic_q     (cic_q[1]),
    .var_strobe(var_strobe),
    .var_i     (var_i[1]),
    .var_q     (var_q[1])
`endif
  );

  receiver_nco #(.CICRATE(CICRATE)) receiver2 (
    .rst_all   (rst_r),
    .clock     (clk),
    .clock_2x  (clk_2x),
    .rate      (rate),
    .mixdata_I (mix2_i),
    .mixdata_Q (mix2_q),
    .out_strobe(),
    .out_data_I(ch2_i),
    .out_data_Q(ch2_q),
    .debug     ()
`ifdef VARCIC_QUAD
    ,
    .cic_strobe(cic_strobe[2]),
    .cic_i     (cic_i[2]),
    .cic_q     (cic_q[2]),
    .var_strobe(var_strobe),
    .var_i     (var_i[2]),
    .var_q     (var_q[2])
`endif
  );

  receiver_nco #(.CICRATE(CICRATE)) receiver3 (
    .rst_all   (rst_r),
    .clock     (clk),
    .clock_2x  (clk_2x),
    .rate      (rate),
    .mixdata_I (mix3_i),
    .mixdata_Q (mix3_q),
    .out_strobe(),
    .out_data_I(ch3_i),
    .out_data_Q(ch3_q),
    .debug     ()
`ifdef VARCIC_QUAD
    ,
    .cic_strobe(cic_strobe[3]),
    .cic_i     (cic_i[3]),
    .cic_q     (cic_q[3]),
    .var_strobe(var_strobe),
    .var_i     (var_i[3]),
    .var_q     (var_q[3])
`endif
  );

endmodule
