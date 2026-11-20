// Second CIC stage of receiver_ciconly.v (N=4, R=25, 18 bits in, 24 out),
// shared by NS I/Q streams with all state in block RAM.
//
// Bit for bit, it gives the same output sequence as NS separate cic_s2
// instances: every stage, width and truncation is cic_s2's. Only the output
// strobe moves: it comes about 80 clocks after the decimation frame instead
// of 2, still well inside the 400-clock output period.
//
// Timing. in_strobe is strobe1 of receiver 0: high for one clock in every 16,
// all receivers being in lockstep. cic_s2 integrates on the edge that ends
// that clock, adding the first stage's output as it stood just before the
// edge. That value is held for the whole 16-clock frame, so a lane can read
// it live at any point in the frame and apply the update early.
//
// Integrators. Each lane owns up to 14 streams. In frame phase j it reads
// stream j's four integrators (138 bits) from RAM, and in phase j+1 adds and
// writes them back. All four adds use old values, as the parallel
// cic_integrator chain does.
//
// Combs. cnt2 copies the receivers' decimation count. In the frame whose
// update coincides with strobe2, the lane also writes each stream's new last
// integrator into the comb RAM as "stage 0". It then runs the combs one stage
// per clock, stage 1 to 4, carrying each stage's old output to the next stage.
// That reproduces cic_comb's update-all-from-old-values rule. The output is
// the old stage-4 value, as receiver_nco's output register sees it.

module cic_s2_shared #(
  parameter NS = 24                       // I/Q streams, 1..28
) (
  input                       clock,
  input                       in_strobe,  // strobe1 of receiver 0
  input      [NS*18-1:0]      in_data,    // stream s at [s*18 +: 18]
  output reg                  out_strobe = 1'b0,
  output     [NS*24-1:0]      out_data    // stream s at [s*24 +: 24]
);

  // A lane takes at most 14 streams: its comb run starts at phase L + 1 <= 15.
  localparam LANES = (NS + 13) / 14;
  localparam L     = (NS + LANES - 1) / LANES;   // streams per lane

  // Frame phase: 0 on the clock after a strobe1 edge, 15 on the strobe clock.
  // It saturates so a partial frame at power-up does not wrap.
  reg [3:0] ph = 4'd0;
  // Copy of the receivers' strobe2 counter (cnt2 in receiver_ciconly.v).
  reg [4:0] cnt2 = 5'd0;

  always @(posedge clock) begin
    if (in_strobe) begin
      ph   <= 4'd0;
      cnt2 <= (cnt2 == 5'd24) ? 5'd0 : cnt2 + 5'd1;
    end else if (ph != 4'd15) begin
      ph <= ph + 4'd1;
    end
  end

  // The update applied in this frame lands on the next strobe1 edge, which
  // drives strobe2 when cnt2 is 24.
  wire dec_frame = (cnt2 == 5'd24);

  wire [LANES-1:0] lane_done;

  genvar g;
  generate
    for (g = 0; g < LANES; g = g + 1) begin : LANE
      localparam FIRST = g * L;
      localparam COUNT = (NS - FIRST < L) ? NS - FIRST : L;
      cic_s2_lane #(.L(COUNT)) lane (
        .clock    (clock),
        .ph       (ph),
        .dec_frame(dec_frame),
        .in_data  (in_data [FIRST*18 +: COUNT*18]),
        .out_data (out_data[FIRST*24 +: COUNT*24]),
        .done     (lane_done[g])
      );
    end
  endgenerate

  always @(posedge clock) out_strobe <= lane_done[0];

endmodule


module cic_s2_lane #(
  parameter L = 12                        // streams in this lane, 1..14
) (
  input                     clock,
  input       [3:0]         ph,
  input                     dec_frame,
  input       [L*18-1:0]    in_data,
  output reg  [L*24-1:0]    out_data = {L*24{1'b0}},
  output reg                done = 1'b0
);

  localparam AW = (L > 8) ? 4 : (L > 4) ? 3 : (L > 2) ? 2 : 1;

  //--------------------------------------------------------------- integrators
  // Word: {i4[29:0], i3[33:0], i2[36:0], i1[36:0]}
  (* ramstyle = "M9K" *) reg [137:0] imem [0:(1<<AW)-1];
  reg [137:0] iq = 138'd0;
  integer k;
  initial for (k = 0; k < (1 << AW); k = k + 1) imem[k] = 138'd0;

  wire         rd_slot = (ph < L);
  wire [AW-1:0] rd_idx = ph[AW-1:0];

  reg              upd = 1'b0;      // iq holds stream upd_idx's state
  reg [AW-1:0]     upd_idx = {AW{1'b0}};
  reg signed [17:0] x = 18'sd0;
  reg              upd_dec = 1'b0;

  always @(posedge clock) begin
    iq      <= imem[rd_idx];
    upd     <= rd_slot;
    upd_idx <= rd_idx;
    upd_dec <= dec_frame;
    x       <= in_data[rd_idx*18 +: 18];
  end

  wire signed [36:0] i1 = iq[36:0];
  wire signed [36:0] i2 = iq[73:37];
  wire signed [33:0] i3 = iq[107:74];
  wire signed [29:0] i4 = iq[137:108];

  // cic_s2: i1 += x; i2 += i1; i3 += i2[36-:34]; i4 += i3[33-:30]
  wire signed [36:0] i1n = i1 + {{19{x[17]}}, x};
  wire signed [36:0] i2n = i2 + i1;
  wire signed [33:0] i3n = i3 + i2[36:3];
  wire signed [29:0] i4n = i4 + i3[33:4];

  always @(posedge clock) begin
    if (upd) imem[upd_idx] <= {i4n, i3n, i2n, i1n};
  end

  //--------------------------------------------------------------------- combs
  // Address {stream, stage}: stage 0 holds the new last integrator; stages
  // 1..4 hold {out[28:0], prev[28:0]} at each stage's own width.
  (* ramstyle = "M9K" *) reg [57:0] cmem [0:(1<<(AW+3))-1];
  reg [57:0] cq = 58'd0;
  initial for (k = 0; k < (1 << (AW + 3)); k = k + 1) cmem[k] = 58'd0;

  reg          crun = 1'b0;
  reg [AW-1:0] cs = {AW{1'b0}};     // stream being read
  reg [2:0]    ck = 3'd0;           // stage being read, 0..4
  reg          cv = 1'b0;           // cq is valid for (cs_d, ck_d)
  reg [AW-1:0] cs_d = {AW{1'b0}};
  reg [2:0]    ck_d = 3'd0;
  reg signed [29:0] carry = 30'sd0; // previous stage's old output (or i4)

  // Start once the last integrator write of the decimation frame is done.
  wire cstart = dec_frame && (ph == L + 1) && !crun;
  wire clast  = crun && (cs == L - 1) && (ck == 3'd4);

  always @(posedge clock) begin
    if (cstart) begin
      crun <= 1'b1;
      cs   <= {AW{1'b0}};
      ck   <= 3'd0;
    end else if (crun) begin
      if (ck == 3'd4) begin
        ck <= 3'd0;
        cs <= cs + 1'b1;
      end else begin
        ck <= ck + 3'd1;
      end
      if (clast) crun <= 1'b0;
    end
    cq   <= cmem[{cs, ck}];
    cv   <= crun;
    cs_d <= cs;
    ck_d <= ck;
  end

  // Old output and previous input of the stage just read, sign-extended.
  wire signed [28:0] old_out = cq[57:29];
  wire signed [28:0] prev    = cq[28:0];

  // Stage input from the carry, at the stage's width (cic_s2 truncations):
  // stage 1: i4[29-:29], 2: out1[28-:28], 3: out2[27-:27], 4: out3[26-:26].
  reg signed [28:0] in_k;
  reg signed [28:0] out_k;
  always @* begin
    case (ck_d)
      3'd1:    in_k = carry[29:1];
      3'd2:    in_k = {{1{carry[28]}}, carry[28:1]};
      3'd3:    in_k = {{2{carry[27]}}, carry[27:1]};
      default: in_k = {{3{carry[26]}}, carry[26:1]};
    endcase
    out_k = in_k - prev;
  end

  // The stage widths are 29, 28, 27 and 26 bits; arithmetic at 29 bits with
  // sign-extended operands gives the same low bits, and each stage stores and
  // reads back only its own width.
  function automatic signed [28:0] at_width(input [2:0] stage,
                                           input signed [28:0] v);
    case (stage)
      3'd1:    at_width = v;
      3'd2:    at_width = {{1{v[27]}}, v[27:0]};
      3'd3:    at_width = {{2{v[26]}}, v[26:0]};
      default: at_width = {{3{v[25]}}, v[25:0]};
    endcase
  endfunction

  wire [AW+2:0] cwaddr = {cs_d, ck_d};

  always @(posedge clock) begin
    if (upd && upd_dec) begin
      // Integrator side: new last integrator into stage 0.
      cmem[{upd_idx, 3'd0}] <= {28'd0, i4n};
    end else if (cv && ck_d != 3'd0) begin
      cmem[cwaddr] <= {at_width(ck_d, out_k), at_width(ck_d, in_k)};
    end
  end

  always @(posedge clock) begin
    done <= 1'b0;
    if (cv) begin
      if (ck_d == 3'd0) begin
        carry <= cq[29:0];                          // i4 for stage 1
      end else begin
        carry <= {{1{old_out[28]}}, at_width(ck_d, old_out)};
        if (ck_d == 3'd4) begin
          // receiver_nco registers comb4[25-:24] as it was before this update.
          out_data[cs_d*24 +: 24] <= old_out[25:2];
          if (cs_d == L - 1) done <= 1'b1;
        end
      end
    end
  end

endmodule
