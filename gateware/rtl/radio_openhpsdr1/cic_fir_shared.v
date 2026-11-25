// Second CIC stage and a decimate-by-5 FIR for the cicfir receiver chain,
// shared by NS I/Q streams with all state in block RAM. A drop-in for
// cic_s2_shared (same ports): receiver_ciconly.v with CIC_SHARED feeds it
// cic_s1's 4.8 MHz output, and it returns 24-bit samples at 192 ksps.
//
//   cic_s1 (R=16, per receiver) -> CIC N=4 R=5, 960 kHz -> FIR /5 -> 192 kHz
//
// cic_s2_shared's R=25 CIC alone leaves about +-35 kHz free of aliases. Here
// the CIC decimates only to 960 kHz, where its images fall far from the band,
// and the FIR (cic_fir_coefs.vh, from sim_cocotb/cic_fir/design.py) removes
// everything that would fold onto +-75 kHz at 192 kHz. The output level
// matches cic_s2_shared's.
//
// Second CIC. Same scheme as cic_s2_shared: in_strobe (strobe1 of receiver 0,
// one clock in 16) starts a frame; in frame phase j each lane reads stream j's
// four integrators and in phase j+1 writes them back. Every 5th frame the lane
// also stores each stream's new last integrator, then runs the four combs for
// all its streams (5 clocks a stream). All widths are the full 28 bits
// (18 + 4*log2(5) rounded up), so the CIC is exact modulo 2^28. Its output is
// rounded to 18 bits: x * 625 / 1024.
//
// FIR. Each unit owns S streams, keeps the last 128 samples of each in one
// M9K, and has one 18x18 multiplier. All units step through the taps in
// lockstep and share one coefficient table. Every 5th CIC output starts a run
// of S * FIR_NTAPS clocks, and out_strobe follows the last stream's result.
//
// Output timing. out_data holds each result until the next run overwrites
// it, at least FIR_NTAPS clocks after the next run starts; the next run starts
// 400 clocks after this one. With NS=24 (S=3) the earliest overwrite comes
// about 180 clocks after out_strobe, and radio.v reads all receivers within
// 2*NR clocks of it.

module cic_fir_shared #(
  parameter NS = 24                       // I/Q streams, 1..36
) (
  input                       clock,
  input                       in_strobe,  // strobe1 of receiver 0
  input      [NS*18-1:0]      in_data,    // stream s at [s*18 +: 18]
  output reg                  out_strobe = 1'b0,
  output     [NS*24-1:0]      out_data    // stream s at [s*24 +: 24]
);

  //------------------------------------------------------------- second CIC
  // A lane takes at most 12 streams: its comb run (5 clocks a stream, from
  // phase L + 2) must end before the next decimation frame, 80 clocks later.
  localparam LANES = (NS + 11) / 12;
  localparam L     = (NS + LANES - 1) / LANES;

  reg [3:0] ph = 4'd0;      // frame phase, saturates at 15
  reg [2:0] cnt2 = 3'd0;    // frame count mod 5

  always @(posedge clock) begin
    if (in_strobe) begin
      ph   <= 4'd0;
      cnt2 <= (cnt2 == 3'd4) ? 3'd0 : cnt2 + 3'd1;
    end else if (ph != 4'd15) begin
      ph <= ph + 4'd1;
    end
  end

  wire dec_frame = (cnt2 == 3'd4);

  wire [NS*18-1:0] c2_data;
  wire [LANES-1:0] lane_done;

  genvar g;
  generate
    for (g = 0; g < LANES; g = g + 1) begin : LANE
      localparam FIRST = g * L;
      localparam COUNT = (NS - FIRST < L) ? NS - FIRST : L;
      cic_r5_lane #(.L(COUNT)) lane (
        .clock    (clock),
        .ph       (ph),
        .dec_frame(dec_frame),
        .in_data  (in_data[FIRST*18 +: COUNT*18]),
        .out_data (c2_data[FIRST*18 +: COUNT*18]),
        .done     (lane_done[g])
      );
    end
  endgenerate

  //-------------------------------------------------------------------- FIR
  `include "cic_fir_coefs.vh"

  localparam S     = 3;                          // streams per FIR unit
  localparam UNITS = (NS + S - 1) / S;
  localparam NSP   = UNITS * S;                  // padded stream count

  // Pad the CIC output so every unit has S streams; extra streams read zero.
  wire [NSP*18-1:0] fir_in;
  assign fir_in[NS*18-1:0] = c2_data;
  generate
    if (NSP > NS) begin : PAD
      assign fir_in[NSP*18-1:NS*18] = {(NSP - NS) * 18{1'b0}};
    end
  endgenerate

  // Write side: after each CIC output, write stream j of every unit in clock j.
  reg       wr_run = 1'b0;
  reg [1:0] wr_j = 2'd0;
  reg [6:0] wp = 7'd0;                           // where the next sample goes
  reg [2:0] dcnt = 3'd0;                         // CIC outputs mod 5
  reg       run_go = 1'b0;

  always @(posedge clock) begin
    run_go <= 1'b0;
    if (lane_done[0]) begin
      wr_run <= 1'b1;
      wr_j   <= 2'd0;
    end else if (wr_run) begin
      if (wr_j == S - 1) begin
        wr_run <= 1'b0;
        wp     <= wp + 7'd1;
        dcnt   <= (dcnt == 3'd4) ? 3'd0 : dcnt + 3'd1;
        run_go <= (dcnt == 3'd4);
      end
      wr_j <= wr_j + 2'd1;
    end
  end

  // Run sequencer, shared by all units: stream j, tap k, reading x[base - k].
  reg       run = 1'b0;
  reg [1:0] rj = 2'd0;
  reg [6:0] rk = 7'd0;
  reg [6:0] base = 7'd0;

  wire rlast = run && (rj == S - 1) && (rk == FIR_NTAPS - 1);

  always @(posedge clock) begin
    if (run_go) begin
      run  <= 1'b1;
      rj   <= 2'd0;
      rk   <= 7'd0;
      base <= wp - 7'd1;                         // newest sample
    end else if (run) begin
      if (rk == FIR_NTAPS - 1) begin
        rk <= 7'd0;
        rj <= rj + 2'd1;
      end else begin
        rk <= rk + 7'd1;
      end
      if (rlast) run <= 1'b0;
    end
  end

  wire [8:0] raddr = {rj, base - rk};

  // Pipeline: t0 address, t1 RAM/ROM out, t2 product, t3 accumulate.
  reg signed [17:0] coef_q = 18'sd0;
  reg        v1 = 1'b0, v2 = 1'b0;
  reg        f1 = 1'b0, f2 = 1'b0;               // first tap
  reg        l1 = 1'b0, l2 = 1'b0;               // last tap
  reg [1:0]  j1 = 2'd0, j2 = 2'd0;
  reg        fin_strobe = 1'b0;

  always @(posedge clock) begin
    coef_q <= fir_coef(rk);
    v1 <= run;             v2 <= v1;
    f1 <= run && rk == 0;  f2 <= f1;
    l1 <= run && rk == FIR_NTAPS - 1; l2 <= l1;
    j1 <= rj;              j2 <= j1;
    fin_strobe <= v2 && l2 && (j2 == S - 1);
    out_strobe <= fin_strobe;
  end

  wire [NSP*24-1:0] fir_out;

  generate
    for (g = 0; g < UNITS; g = g + 1) begin : UNIT
      cic_fir_unit #(.S(S), .SHIFT(FIR_SHIFT)) unit (
        .clock  (clock),
        .wr_en  (wr_run),
        .wr_addr({wr_j, wp}),
        .wr_data(fir_in[(g*S + wr_j)*18 +: 18]),
        .raddr  (raddr),
        .coef   (coef_q),
        .v2(v2), .f2(f2), .l2(l2), .j2(j2),
        .out_data(fir_out[g*S*24 +: S*24])
      );
    end
  endgenerate

  assign out_data = fir_out[NS*24-1:0];

endmodule


// One FIR unit: S streams' delay lines in one RAM and one multiply-accumulate.
module cic_fir_unit #(
  parameter S = 3,
  parameter SHIFT = 13
) (
  input                    clock,
  input                    wr_en,
  input      [8:0]         wr_addr,
  input      [17:0]        wr_data,
  input      [8:0]         raddr,
  input  signed [17:0]     coef,          // already registered, aligned with RAM output
  input                    v2, f2, l2,    // product stage: valid, first tap, last tap
  input      [1:0]         j2,            // product stage: stream
  output reg [S*24-1:0]    out_data = {S*24{1'b0}}
);

  (* ramstyle = "M9K" *) reg [17:0] mem [0:511];
  integer k;
  initial for (k = 0; k < 512; k = k + 1) mem[k] = 18'd0;

  reg signed [17:0] x = 18'sd0;
  always @(posedge clock) begin
    if (wr_en) mem[wr_addr] <= wr_data;
    x <= mem[raddr];
  end

  reg signed [35:0] prod = 36'sd0;
  reg signed [43:0] acc = 44'sd0;
  always @(posedge clock) prod <= x * coef;

  // acc_next is the sum including this product; on the last tap it is the result.
  wire signed [43:0] acc_next = (f2 ? 44'sd0 : acc) + {{8{prod[35]}}, prod};
  wire signed [43:0] rounded  = acc_next + (44'sd1 <<< (SHIFT - 1));
  wire signed [43-SHIFT:0] y  = rounded >>> SHIFT;
  localparam signed [43-SHIFT:0] YMAX = 8388607;
  localparam signed [43-SHIFT:0] YMIN = -8388608;
  wire [23:0] ysat = (y > YMAX) ? 24'h7fffff : (y < YMIN) ? 24'h800000 : y[23:0];

  always @(posedge clock) begin
    if (v2) begin
      acc <= acc_next;
      if (l2) out_data[j2*24 +: 24] <= ysat;
    end
  end

endmodule


// One lane of the shared second CIC: N=4, R=5, 28 bits throughout.
module cic_r5_lane #(
  parameter L = 12                        // streams in this lane, 1..12
) (
  input                     clock,
  input       [3:0]         ph,
  input                     dec_frame,
  input       [L*18-1:0]    in_data,
  output reg  [L*18-1:0]    out_data = {L*18{1'b0}},
  output reg                done = 1'b0
);

  localparam AW = (L > 8) ? 4 : (L > 4) ? 3 : (L > 2) ? 2 : 1;

  //--------------------------------------------------------------- integrators
  // Word: {i4, i3, i2, i1}, 28 bits each
  (* ramstyle = "M9K" *) reg [111:0] imem [0:(1<<AW)-1];
  reg [111:0] iq = 112'd0;
  integer k;
  initial for (k = 0; k < (1 << AW); k = k + 1) imem[k] = 112'd0;

  wire          rd_slot = (ph < L);
  wire [AW-1:0] rd_idx  = ph[AW-1:0];

  reg               upd = 1'b0;
  reg [AW-1:0]      upd_idx = {AW{1'b0}};
  reg signed [17:0] x = 18'sd0;
  reg               upd_dec = 1'b0;

  always @(posedge clock) begin
    iq      <= imem[rd_idx];
    upd     <= rd_slot;
    upd_idx <= rd_idx;
    upd_dec <= dec_frame;
    x       <= in_data[rd_idx*18 +: 18];
  end

  wire [27:0] i1 = iq[27:0];
  wire [27:0] i2 = iq[55:28];
  wire [27:0] i3 = iq[83:56];
  wire [27:0] i4 = iq[111:84];

  // All four adds use old values, as a chain of registered integrators does.
  wire [27:0] i1n = i1 + {{10{x[17]}}, x};
  wire [27:0] i2n = i2 + i1;
  wire [27:0] i3n = i3 + i2;
  wire [27:0] i4n = i4 + i3;

  always @(posedge clock) begin
    if (upd) imem[upd_idx] <= {i4n, i3n, i2n, i1n};
  end

  //--------------------------------------------------------------------- combs
  // Address {stream, stage}: stage 0 holds the new last integrator; stages
  // 1..4 hold each comb's previous input. Each comb takes the new output of
  // the one before it, so the four combs act as (1 - z^-1)^4 with no delay.
  (* ramstyle = "M9K" *) reg [27:0] cmem [0:(1<<(AW+3))-1];
  reg [27:0] cq = 28'd0;
  initial for (k = 0; k < (1 << (AW + 3)); k = k + 1) cmem[k] = 28'd0;

  reg          crun = 1'b0;
  reg [AW-1:0] cs = {AW{1'b0}};
  reg [2:0]    ck = 3'd0;
  reg          cv = 1'b0;
  reg [AW-1:0] cs_d = {AW{1'b0}};
  reg [2:0]    ck_d = 3'd0;
  reg [27:0]   carry = 28'd0;

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

  wire [27:0]        diff = carry - cq;
  wire signed [27:0] dsg  = diff;
  // Round to 18 bits: |x * 625| < 2^27, so the result fits after >> 10.
  wire signed [27:0] drnd = dsg + 28'sd512;

  always @(posedge clock) begin
    if (upd && upd_dec) begin
      cmem[{upd_idx, 3'd0}] <= i4n;
    end else if (cv && ck_d != 3'd0) begin
      cmem[{cs_d, ck_d}] <= carry;
    end
  end

  always @(posedge clock) begin
    done <= 1'b0;
    if (cv) begin
      if (ck_d == 3'd0) begin
        carry <= cq;
      end else begin
        carry <= diff;
        if (ck_d == 3'd4) begin
          out_data[cs_d*18 +: 18] <= drnd[27:10];
          if (cs_d == L - 1) done <= 1'b1;
        end
      end
    end
  end

endmodule
