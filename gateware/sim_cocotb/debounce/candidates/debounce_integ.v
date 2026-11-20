// Bench-only comparison: saturating up/down counter (integrator).
// Count up on 1, down on 0, clamped to 0..MAX; switch only at the ends.
module debounce_integ #(parameter MAX = 4) (
  output reg clean_pb = 1'b0,
  input      pb,
  input      clk,
  input      msec_pulse
);
reg [3:0] cnt = 4'd0;
wire [3:0] cnt_next = pb ? ((cnt == MAX) ? cnt : cnt + 4'd1)
                         : ((cnt == 0)   ? cnt : cnt - 4'd1);
always @(posedge clk) begin
  if (msec_pulse) begin
    cnt <= cnt_next;
    if (cnt_next == MAX) clean_pb <= 1'b1;
    if (cnt_next == 0)   clean_pb <= 1'b0;
  end
end
endmodule
