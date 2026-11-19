// TX interpolation chain of hl2b5up_main, wired as in radio.v:
//
//   tx samples -> FirInterp8_1024 (x8) -> CicInterpM5 (x200) -> y2_r, y2_i
//
// The clock does not run until cocotb raises `run`, so every register and RAM is
// still at its power-up value on the first edge.  On `run` the bench loads
// stim.mem ({I[15:0], Q[15:0]} per line), then for `nclk` clock edges writes:
//
//   cic_out.bin  {y2_r, y2_i} before each edge (the value after the previous one)
//   fir_out.bin  {y1_r, y1_i} sign-extended to 32 bits each, at each CIC comb
//                event, which is the value the CIC samples
//
// Both files are raw 32-bit words, read back with numpy.  `done` rises after the
// last edge.

`timescale 1ns/1ps

module tb_tx_chain;

  localparam int NSTIM_MAX = 65536;
  localparam int RRRR = 200;   // clk_config.vh: CLK_FREQ / 384000 at 76.8 MHz
  localparam int GBITS = 31;   // clk_config.vh at 76.8 MHz

  logic        run = 1'b0;
  logic        done = 1'b0;
  logic [31:0] nclk = 32'd0;
  logic [31:0] nstim = 32'd0;
  logic        clk = 1'b0;

  always begin
    wait (run);
    #6.5 clk = ~clk;
  end

  // ------------------------------------------------------------------ stimulus
  logic [31:0] stim [0:NSTIM_MAX-1];
  logic [31:0] idx = 32'd0;
  logic signed [15:0] tx_fir_i = 16'sd0, tx_fir_q = 16'sd0;
  logic        fir_tready;

  // radio.v registers tx_tdata into tx_fir_i/q on fir_tready.
  always @(posedge clk) begin
    if (fir_tready) begin
      if (idx < nstim) {tx_fir_i, tx_fir_q} <= stim[idx];
      else             {tx_fir_i, tx_fir_q} <= 32'd0;
      idx <= idx + 32'd1;
    end
  end

  // ---------------------------------------------------------------------- DUT
  logic               req2;
  logic signed [19:0] y1_r, y1_i;
  logic signed [15:0] y2_r, y2_i;

  FirInterp8_1024 fi (clk, req2, fir_tready, tx_fir_i, tx_fir_q, y1_r, y1_i);

`ifdef TX_CIC_MEM
  CicInterpM5Mem #(.RRRR(RRRR), .IBITS(20), .OBITS(16), .GBITS(GBITS)) in2 (
    clk, 1'd1, req2, y1_r, y1_i, y2_r, y2_i);
`else
  CicInterpM5 #(.RRRR(RRRR), .IBITS(20), .OBITS(16), .GBITS(GBITS)) in2 (
    clk, 1'd1, req2, y1_r, y1_i, y2_r, y2_i);
`endif

  // ---------------------------------------------------------------- recording
  integer      cic_fd, fir_fd;
  logic [31:0] edges = 32'd0;
  logic [31:0] phase = 32'd0;   // matches in2.counter, kept here to stay black-box

  initial begin
    wait (run);
    $readmemh("stim.mem", stim);
    cic_fd = $fopen("cic_out.bin", "wb");
    fir_fd = $fopen("fir_out.bin", "wb");
  end

  always @(posedge clk) begin
    if (edges < nclk) begin
      $fwrite(cic_fd, "%u", {y2_r, y2_i});
      if (phase == RRRR - 1)
        $fwrite(fir_fd, "%u%u", 32'(y1_r), 32'(y1_i));
      phase <= (phase == RRRR - 1) ? 32'd0 : phase + 32'd1;
      edges <= edges + 32'd1;
      if (edges == nclk - 1) begin
        $fclose(cic_fd);
        $fclose(fir_fd);
        done <= 1'b1;
      end
    end
  end

endmodule
