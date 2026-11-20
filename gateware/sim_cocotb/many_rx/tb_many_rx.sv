///////////////////////////////////////////////
// Many-receiver bench: the production radio.v with NR receivers.
//
// Unlike rx_chain, which wires mix2 and receiver_nco itself, this instantiates
// radio.v, so its mixer-pair mapping, frequency-register decode, channel
// arrays and upstream output multiplexer are all the production code.
// Which receiver_nco is compiled (full chain or CIC only) is chosen in the
// Makefile, as the variant .qsf files do.
//
// Python sets frequencies, rate and receiver count over the command bus, then
// raises `capture`. The ADC replays stim.mem in a loop. Every upstream word
// (rx_tvalid) is written to rx_stream.bin as two 32-bit words: the 24-bit
// data, and {clk_count[29:0], rx_tlast, 1'b1}.

`timescale 1ps/1ps

module tb_many_rx #(
  parameter NR = 12
) (
  input  logic        rst,
  input  logic        load_stim,
  input  logic        capture,
  input  logic [ 5:0] cmd_addr,
  input  logic [31:0] cmd_data,
  input  logic        cmd_rqst,
  output logic        clk,
  output logic        clk_2x,
  output logic [31:0] clk_count,
  output logic [31:0] words
);

  localparam STIM_LEN = 65536;

  initial begin
    clk    = 1'b0;
    clk_2x = 1'b0;
  end

  always begin
    #3250;
    clk_2x = ~clk_2x;
    if (clk_2x) clk = ~clk;
  end

  logic signed [11:0] stim [0:STIM_LEN-1];
  logic        [15:0] stim_index = 16'd0;
  logic signed [11:0] adc = 12'sd0;
  logic               rst_r = 1'b1;

  always @(posedge load_stim) $readmemh("stim.mem", stim);

  always @(posedge clk) begin
    rst_r <= rst;
    if (rst_r) begin
      stim_index <= 16'd0;
      adc        <= 12'sd0;
      clk_count  <= 32'd0;
    end else begin
      stim_index <= stim_index + 16'd1;
      adc        <= stim[stim_index];
      clk_count  <= clk_count + 32'd1;
    end
  end

  logic [23:0] rx_tdata;
  logic        rx_tlast, rx_tvalid;
  logic [ 1:0] rx_tuser;

  radio #(
    .NR      (NR),
    .NT      (0),
    .LRDATA  (0),
    .CLK_FREQ(76800000),
    .HL2LINK (0)
  ) radio_i (
    .clk                    (clk),
    .clk_2x                 (clk_2x),
    .rst_all                (rst_r),
    .rst_nco                (rst_r),
    .link_running           (1'b0),
    .link_master            (1'b0),
    .lm_data                (24'h0),
    .lm_valid               (1'b0),
    .ls_valid               (),
    .ls_done                (1'b0),
    .ds_cmd_ptt             (1'b0),
    .run                    (1'b1),
    .qmsec_pulse            (1'b0),
    .ext_keydown            (1'b0),
    .ext_ptt                (1'b0),
    .tx_on                  (),
    .cw_on                  (),
    .cw_profile             (),
    .tx_tdata               (32'h0),
    .tx_tlast               (1'b1),
    .tx_tready              (),
    .tx_tvalid              (1'b0),
    .tx_tuser               (4'h0),
    .tx_twait               (),
    .tx_data_dac            (),
    .clk_envelope           (1'b0),
    .tx_envelope_pwm_out    (),
    .tx_envelope_pwm_out_inv(),
    .lr_tdata               (32'h0),
    .lr_tid                 (3'h0),
    .lr_tlast               (1'b1),
    .lr_tready              (),
    .lr_tvalid              (1'b0),
    .rx_data_adc            (adc),
    .rx_tdata               (rx_tdata),
    .rx_tlast               (rx_tlast),
    .rx_tready              (1'b1),
    .rx_tvalid              (rx_tvalid),
    .rx_tuser               (rx_tuser),
    .cmd_addr               (cmd_addr),
    .cmd_data               (cmd_data),
    .cmd_rqst               (cmd_rqst),
    .cmd_ack                (),
    .debug_out              ()
  );

  // Upstream capture, written from the simulator so Python need not wake on
  // every clock.
  integer fd = 0;
  initial words = 32'd0;
  always @(posedge capture) begin
    fd = $fopen("rx_stream.bin", "wb");
    words = 32'd0;
  end
  always @(negedge capture) begin
    if (fd != 0) $fclose(fd);
    fd = 0;
  end

  always @(posedge clk) begin
    if (capture && fd != 0 && rx_tvalid) begin
      $fwrite(fd, "%u", {8'h00, rx_tdata});
      $fwrite(fd, "%u", {clk_count[29:0], rx_tlast, 1'b1});
      words <= words + 32'd1;
    end
  end

endmodule
