// cic_fir_shared bench. strobe1 is generated as receiver_ciconly.v does (one
// clock in 16). The test writes x_next during each frame; it is latched on the
// strobe1 edge, as cic_s1's output register is.

`timescale 1ns/1ps

module tb_cic_fir #(parameter NS = 24) (
  input  logic              clk,
  input  logic [NS*18-1:0]  x_next,
  output logic              strobe1,
  output logic              dut_strobe,
  output logic [NS*24-1:0]  dut_data
);

  logic [3:0] cnt1 = 4'd0;
  initial strobe1 = 1'b0;
  always @(posedge clk) begin
    if (cnt1 == 4'd15) begin cnt1 <= 4'd0; strobe1 <= 1'b1; end
    else begin cnt1 <= cnt1 + 4'd1; strobe1 <= 1'b0; end
  end

  logic [NS*18-1:0] x = '0;
  always @(posedge clk) if (strobe1) x <= x_next;

  cic_fir_shared #(.NS(NS)) dut (
    .clock(clk), .in_strobe(strobe1), .in_data(x),
    .out_strobe(dut_strobe), .out_data(dut_data));

endmodule
