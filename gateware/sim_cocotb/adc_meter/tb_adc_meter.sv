// adc_meter bench: the meter at the ADC clock, and sync_qualifier carrying
// its output into a 2.5 MHz control clock, as hermeslite_core wires them.
// After `go`, rx_data replays stim.mem (12-bit hex) once, then holds 0.

`timescale 1ps/1ps

module tb_adc_meter #(
  parameter WINDOW_LOG2 = 12,
  parameter STIM_LEN    = 4096
) (
  input  logic        go,
  output logic        clk_ad,
  output logic        clk_ctrl,
  output logic [31:0] clk_count,
  output logic [31:0] go_count,
  output logic [31:0] meter,
  output logic        meter_toggle,
  output logic [31:0] meter_ctrl,
  output logic        meter_ctrl_valid
);

  initial begin
    clk_ad   = 1'b0;
    clk_ctrl = 1'b0;
  end
  always #6510 clk_ad = ~clk_ad;            // 76.8 MHz (13.02 ns)
  always #200000 clk_ctrl = ~clk_ctrl;      // 2.5 MHz, unrelated phase

  logic [11:0] stim [0:STIM_LEN-1];
  initial $readmemh("stim.mem", stim);

  logic [11:0] rx_data = 12'h0;
  logic [31:0] idx = 32'd0;
  logic        started = 1'b0;
  initial begin
    clk_count = 32'd0;
    go_count  = 32'd0;
  end
  always @(posedge clk_ad) begin
    clk_count <= clk_count + 32'd1;
    if (go) begin
      if (!started) go_count <= clk_count;
      started <= 1'b1;
      rx_data <= (idx < STIM_LEN) ? stim[idx] : 12'h0;
      idx     <= idx + 32'd1;
    end
  end

  adc_meter #(.WINDOW_LOG2(WINDOW_LOG2)) dut (
    .clk          (clk_ad),
    .rx_data      (rx_data),
    .meter        (meter),
    .meter_toggle (meter_toggle)
  );

  sync_qualifier #(.WIDTH(32)) sync_i (
    .clock           (clk_ctrl),
    .data_in         (meter),
    .data_valid      (meter_toggle),
    .data_valid_sync (meter_ctrl_valid),
    .data_out        (meter_ctrl)
  );

endmodule
