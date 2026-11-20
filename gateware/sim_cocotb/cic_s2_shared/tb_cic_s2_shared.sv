// cic_s2_shared against NS separate cic_s2 instances (receiver_ciconly.v).
//
// Strobes are generated as receiver_ciconly.v does (cnt1 /16, cnt2 /25). The
// inputs model cic_s1's output register: new values at each strobe1 edge,
// from one LFSR per stream. `quiet` limits them to +/-2^9 (8-bit magnitudes
// plus sign), as a quiet signal would be; otherwise they use all 18 bits.

`timescale 1ns/1ps

module tb_cic_s2_shared #(parameter NS = 24) (
  input  logic              clk,
  input  logic              quiet,
  output logic              ref_strobe,
  output logic [NS*24-1:0]  ref_data,
  output logic              dut_strobe,
  output logic [NS*24-1:0]  dut_data
);

  logic [3:0] cnt1 = 4'd0;
  logic [4:0] cnt2 = 5'd0;
  logic strobe1 = 1'b0, strobe2 = 1'b0;

  always @(posedge clk) begin
    if (cnt1 == 4'd15) begin cnt1 <= 4'd0; strobe1 <= 1'b1; end
    else begin cnt1 <= cnt1 + 4'd1; strobe1 <= 1'b0; end
  end
  always @(posedge clk) begin
    if (strobe1) begin
      if (cnt2 == 5'd24) begin cnt2 <= 5'd0; strobe2 <= 1'b1; end
      else begin cnt2 <= cnt2 + 5'd1; strobe2 <= 1'b0; end
    end else strobe2 <= 1'b0;
  end

  logic [NS*18-1:0] x = '0;
  logic [31:0] lfsr [0:NS-1];
  integer s;
  initial for (s = 0; s < NS; s = s + 1) lfsr[s] = 32'h1234_5678 ^ (s * 32'h9E37_79B9) | 32'h1;

  always @(posedge clk) begin
    if (strobe1) begin
      for (s = 0; s < NS; s = s + 1) begin
        lfsr[s] <= {lfsr[s][30:0], lfsr[s][31] ^ lfsr[s][21] ^ lfsr[s][1] ^ lfsr[s][0]};
        x[s*18 +: 18] <= quiet ? {{9{lfsr[s][9]}}, lfsr[s][8:0]} : lfsr[s][17:0];
      end
    end
  end

  genvar g;
  generate
    for (g = 0; g < NS; g = g + 1) begin : REF
      wire signed [23:0] y;
      cic_s2 c (.clock(clk), .in_strobe(strobe1), .out_strobe(strobe2),
                .in_data(x[g*18 +: 18]), .out_data(y));
      // receiver_nco's output register.
      always @(posedge clk) if (strobe2) ref_data[g*24 +: 24] <= y;
    end
  endgenerate
  always @(posedge clk) ref_strobe <= strobe2;

  cic_s2_shared #(.NS(NS)) dut (
    .clock(clk), .in_strobe(strobe1), .in_data(x),
    .out_strobe(dut_strobe), .out_data(dut_data));

endmodule
