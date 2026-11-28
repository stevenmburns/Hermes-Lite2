// Equal-delay debouncer, a candidate replacement for rtl/debounce.v.
//
// Same ports and the same msec_pulse sample tick. Keeps the last D+1 samples
// of pb in h, h[D] the oldest. On each pulse:
//   on   when the oldest sample is 1 (CONFIRM = 0), or when it is 1 and at
//        least one newer sample is also 1 (CONFIRM = 1)
//   off  when all D+1 samples are 0
//   else hold
// Both edges come out D+1 samples late: on D+1 samples after the first
// contact, off D+1 samples after the last one. The element keeps its keyed
// width; bounce only adds the time the contacts are still chattering on
// release. D must cover the longest gap inside one bounce burst, not the
// whole burst. With CONFIRM = 1 a lone 1 ms spike never turns it on; a press
// whose first contact is followed by D open samples starts at its next
// contact instead.

module debounce_hold #(
  parameter D       = 4,   // hold window is D+1 samples, D >= 1
  parameter CONFIRM = 1
) (
  output reg clean_pb = 1'b0,
  input      pb,
  input      clk,
  input      msec_pulse
);

reg [D:0] h = {(D+1){1'b0}};

wire start = h[D] & (CONFIRM == 0 || |h[D-1:0]);

always @(posedge clk) begin
  if (msec_pulse) begin
    h <= {h[D-1:0], pb};
    if (start)    clean_pb <= 1'b1;
    else if (~|h) clean_pb <= 1'b0;
  end
end

endmodule
