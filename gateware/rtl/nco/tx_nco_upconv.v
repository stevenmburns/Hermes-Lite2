// TX upconverter built from the sincos NCO and multipliers.
//
// A drop-in replacement for cpl_cordic #(.OUT_WIDTH(16)) as radio.v uses it:
// the same ports, phase accumulator, gain (CORDIC gain / 4 = 0.41169), delay
// (out after edge t + 19 for the input sampled on edge t) and rotation:
//
//   out_I + j out_Q = 0.41169 * (in_I + j in_Q) * exp(j 2 pi phase / 2^32)
//
// It is not bit-exact with the CORDIC; tx_chain measures the difference.
//
// sincos needs LEAD clocks from angle to signed sine and cosine, so it is fed
// the phase LEAD clocks ahead, phase + LEAD * frequency, instead of delaying
// the input data. That is exact while the frequency is constant; for LEAD
// clocks after a change the angle is off by LEAD * (new - old) frequency.
// Output registers then add OUT_DELAY clocks to match the CORDIC's delay.

module tx_nco_upconv (
  input                clock,
  input  signed [31:0] frequency,
  input  signed [15:0] in_data_I,
  input  signed [15:0] in_data_Q,
  output signed [15:0] out_data_I,
  output signed [15:0] out_data_Q
);

parameter CALCTYPE  = 3;
parameter LEAD      = 6;
parameter OUT_DELAY = 15;
// Gain trim. sin and cos are scaled to 2^17, so p = (I cos - Q sin) / 2^16 is
// 2 * in * cos, and out = p * GAIN_K / 2^19 gives 0.41169 * in for
// GAIN_K = round(0.41169006 * 2^19 / 2).
parameter signed [17:0] GAIN_K = 18'sd107923;

// --------------------------------------------------------------- phase
// Identical to cpl_cordic: zero frequency holds the phase at zero.
reg [31:0] phase = 32'd0;
always @(posedge clock) begin
  if (frequency == 32'sd0) phase <= 32'd0;
  else                     phase <= phase + frequency;
end

// sincos takes the top 20 bits. The dropped bits give phase-truncation spurs
// near -101 dBc (measured in tx_chain); rounding would not reduce them, only
// remove their mean.
wire [31:0] lead_phase = phase + LEAD * frequency;

logic [18:0] sin_sm, cos_sm;   // sign-magnitude, 18-bit magnitude
sincos #(.CALCTYPE(CALCTYPE)) sincos_i (
  .clk(clock),
  .angle(lead_phase[31:12]),
  .cos(cos_sm),
  .sin(sin_sm)
);

// Sign-magnitude to 18-bit signed, magnitude rounded to 17 bits.
function automatic signed [17:0] to_signed18(input [18:0] sm);
  reg [17:0] mag;
  begin
    mag = {1'b0, sm[17:1]} + sm[0];
    if (mag[17]) mag = 18'h1ffff;            // saturate the one rounding overflow
    to_signed18 = sm[18] ? -$signed(mag) : $signed(mag);
  end
endfunction

reg signed [17:0] c18 = 0, s18 = 0;
always @(posedge clock) begin
  c18 <= to_signed18(cos_sm);
  s18 <= to_signed18(sin_sm);
end

// ----------------------------------------------------------- rotation
reg signed [33:0] ic = 0, qs = 0, sc = 0, qc = 0;
reg signed [34:0] e_i = 0, e_q = 0;
reg signed [17:0] p_i = 0, p_q = 0;
reg signed [35:0] k_i = 0, k_q = 0;
reg signed [15:0] r_i = 0, r_q = 0;

always @(posedge clock) begin
  ic <= in_data_I * c18;
  qs <= in_data_Q * s18;
  sc <= in_data_I * s18;
  qc <= in_data_Q * c18;
  e_i <= ic - qs;
  e_q <= sc + qc;
  p_i <= (e_i + 35'sd32768) >>> 16;
  p_q <= (e_q + 35'sd32768) >>> 16;
  k_i <= p_i * GAIN_K;
  k_q <= p_q * GAIN_K;
  r_i <= (k_i + 36'sd262144) >>> 19;
  r_q <= (k_q + 36'sd262144) >>> 19;
end

// ------------------------------------------------------- delay match
reg signed [15:0] d_i [0:OUT_DELAY];
reg signed [15:0] d_q [0:OUT_DELAY];
integer k;
initial for (k = 0; k <= OUT_DELAY; k = k + 1) begin d_i[k] = 0; d_q[k] = 0; end
always @(posedge clock) begin
  d_i[0] <= r_i;
  d_q[0] <= r_q;
  for (k = 1; k <= OUT_DELAY; k = k + 1) begin
    d_i[k] <= d_i[k-1];
    d_q[k] <= d_q[k-1];
  end
end

assign out_data_I = (OUT_DELAY == 0) ? r_i : d_i[OUT_DELAY-1];
assign out_data_Q = (OUT_DELAY == 0) ? r_q : d_q[OUT_DELAY-1];

endmodule
