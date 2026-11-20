// Bench-only comparison: switch after N agreeing samples in a row.
// This is the sampled form of the common restart-on-change timer.
module debounce_run #(parameter N = 4) (
  output reg clean_pb = 1'b0,
  input      pb,
  input      clk,
  input      msec_pulse
);
reg       last = 1'b0;
reg [3:0] run  = 4'd0;
wire [3:0] run_next = (pb != last) ? 4'd1 : (run == N) ? run : run + 4'd1;
always @(posedge clk) begin
  if (msec_pulse) begin
    last <= pb;
    run  <= run_next;
    if (run_next == N) clean_pb <= pb;
  end
end
endmodule
