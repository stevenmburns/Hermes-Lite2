// Confirm-then-lockout debouncer, a candidate replacement for rtl/debounce.v.
//
// Same ports and the same msec_pulse sample tick. On each pulse:
//   IDLE   pb differs from clean_pb: start confirming (or switch at once if
//          CONFIRM is 1).
//   CHECK  pb went back: drop it (a spike shorter than CONFIRM samples).
//          pb has differed for CONFIRM samples in a row: switch clean_pb.
//   LOCK   ignore pb for LOCKOUT samples after a switch, so contact bounce
//          that follows the edge cannot switch it back.
// clean_pb changes on the CONFIRM-th agreeing sample, CONFIRM-1 samples after
// the first one; spikes shorter than CONFIRM samples never reach it.

module debounce_cl #(
  parameter CONFIRM = 2,   // samples that must agree before a switch, 1..15
  parameter LOCKOUT = 6    // samples ignored after a switch, 1..16
) (
  output reg clean_pb = 1'b0,
  input      pb,
  input      clk,
  input      msec_pulse
);

localparam [1:0] IDLE = 2'd0, CHECK = 2'd1, LOCK = 2'd2;

reg [1:0] state = IDLE;
reg [3:0] cnt   = 4'd0;

always @(posedge clk) begin
  if (msec_pulse) begin
    case (state)
      IDLE:
        if (pb != clean_pb) begin
          if (CONFIRM <= 1) begin
            clean_pb <= pb;
            state    <= LOCK;
            cnt      <= 4'd0;
          end else begin
            state    <= CHECK;
            cnt      <= 4'd1;
          end
        end
      CHECK:
        if (pb == clean_pb) begin
          state <= IDLE;
        end else if (cnt == CONFIRM - 1) begin
          clean_pb <= pb;
          state    <= LOCK;
          cnt      <= 4'd0;
        end else begin
          cnt <= cnt + 4'd1;
        end
      LOCK:
        if (cnt == LOCKOUT - 1) state <= IDLE;
        else                    cnt   <= cnt + 4'd1;
      default:
        state <= IDLE;
    endcase
  end
end

endmodule
