// ADC level meter: clip count and peak magnitude per fixed window.
//
// Runs in the ADC clock domain. Every 2**WINDOW_LOG2 samples (6.8 ms at
// 76.8 MHz for the default 19) it latches, for the window just ended:
//
//   meter[31:16]  samples at full scale (the stock rxclip test: 0x7ff or
//                 0x800), saturating at 65535
//   meter[15:12]  window number, wrapping, so software can tell a new window
//                 from a repeated report
//   meter[11:0]   peak |rx_data|, 0..2048 (2048 only for 0x800)
//
// meter changes once per window and meter_toggle flips with each change, the
// source side of sync_qualifier.

module adc_meter #(
  parameter WINDOW_LOG2 = 19
) (
  input                     clk,
  input  [11:0]             rx_data,
  output logic [31:0]       meter = 32'h0,
  output logic              meter_toggle = 1'b0
);

  logic [WINDOW_LOG2-1:0] sample = '0;
  logic [15:0]            clips  = 16'h0;
  logic [11:0]            peak   = 12'h0;
  logic [ 3:0]            window = 4'h0;

  // Registered input stage keeps the meter off the ADC capture path.
  logic [11:0] x = 12'h0;
  logic [11:0] mag;
  logic        clip;
  always @(posedge clk) x <= rx_data;
  assign mag  = x[11] ? (~x + 12'd1) : x;     // 0x800 -> 0x800 (2048)
  assign clip = (x == 12'h7ff) | (x == 12'h800);

  wire last = &sample;

  always @(posedge clk) begin
    sample <= sample + 1'b1;
    if (last) begin
      // Include this sample in the window that ends with it.
      meter <= {(clip & ~&clips) ? clips + 16'd1 : clips,
                window,
                (mag > peak) ? mag : peak};
      meter_toggle <= ~meter_toggle;
      window <= window + 4'd1;
      clips  <= 16'h0;
      peak   <= 12'h0;
    end else begin
      if (clip & ~&clips) clips <= clips + 16'd1;
      if (mag > peak)     peak  <= mag;
    end
  end

endmodule
