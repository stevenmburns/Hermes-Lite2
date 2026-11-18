// Production receive chain for hl2b5up_main: one mix2 serving two receiver_nco
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
  input  logic        [ 5:0] rate,
  output logic               clk,
  output logic               clk_2x,
  output logic               out_strobe,
  output logic signed [23:0] ch0_i,
  output logic signed [23:0] ch0_q,
  output logic signed [23:0] ch1_i,
  output logic signed [23:0] ch1_q,
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
  );

endmodule
