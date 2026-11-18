// Minimal behavioural altsyncram for simulating the production receiver.
//
// The production build defines USE_ALTSYNCRAM, which selects explicit altsyncram
// instances in coarserom.v, firromH.v and firram36.v.  Intel's altera_mf.v needs
// a Quartus install, so this models only the modes those three files use:
//
//   ROM        address_a registered by clock0; q_a optionally registered again
//   DUAL_PORT  write on port A; address_b registered by clock0; q_b optionally
//              registered again
//
// Read latency is the point of this file.  An altsyncram address input is always
// registered, so outdata_reg = "CLOCK0" gives two clocks of read latency and
// "UNREGISTERED" gives one.  The plain behavioural ROM/RAM models in the RTL have
// one clock, so they do not reproduce production timing.
//
// init_file is read with $readmemh: mif2mem.py converts each production .mif into
// a file of the same name in the simulation run directory.

`timescale 1ps/1ps

module altsyncram (
  input  wire                     clock0,
  input  wire                     clock1,
  input  wire                     aclr0,
  input  wire                     aclr1,
  input  wire                     addressstall_a,
  input  wire                     addressstall_b,
  input  wire [width_byteena_a-1:0] byteena_a,
  input  wire                     byteena_b,
  input  wire                     clocken0,
  input  wire                     clocken1,
  input  wire                     clocken2,
  input  wire                     clocken3,
  input  wire                     rden_a,
  input  wire                     rden_b,
  input  wire                     wren_a,
  input  wire                     wren_b,
  input  wire [widthad_a-1:0]     address_a,
  input  wire [widthad_b-1:0]     address_b,
  input  wire [width_a-1:0]       data_a,
  input  wire [width_b-1:0]       data_b,
  output wire [width_a-1:0]       q_a,
  output wire [width_b-1:0]       q_b,
  output wire [2:0]               eccstatus
);

  parameter operation_mode                     = "ROM";
  parameter width_a                            = 1;
  parameter widthad_a                          = 1;
  parameter numwords_a                         = 2;
  parameter width_b                            = 1;
  parameter widthad_b                          = 1;
  parameter numwords_b                         = 2;
  parameter width_byteena_a                    = 1;
  parameter outdata_reg_a                      = "UNREGISTERED";
  parameter outdata_reg_b                      = "UNREGISTERED";
  parameter address_reg_b                      = "CLOCK0";
  parameter init_file                          = "UNUSED";
  parameter address_aclr_a                     = "NONE";
  parameter address_aclr_b                     = "NONE";
  parameter outdata_aclr_a                     = "NONE";
  parameter outdata_aclr_b                     = "NONE";
  parameter clock_enable_input_a               = "BYPASS";
  parameter clock_enable_input_b               = "BYPASS";
  parameter clock_enable_output_a              = "BYPASS";
  parameter clock_enable_output_b              = "BYPASS";
  parameter intended_device_family             = "Cyclone IV E";
  parameter lpm_hint                           = "UNUSED";
  parameter lpm_type                           = "altsyncram";
  parameter power_up_uninitialized             = "FALSE";
  parameter read_during_write_mode_mixed_ports = "DONT_CARE";

  localparam IS_ROM = (operation_mode == "ROM");
  localparam REG_A  = (outdata_reg_a == "CLOCK0");
  localparam REG_B  = (outdata_reg_b == "CLOCK0");

  reg [width_a-1:0]   mem [0:numwords_a-1];
  reg [widthad_a-1:0] addr_a_r = 0;
  reg [widthad_b-1:0] addr_b_r = 0;
  reg [width_a-1:0]   q_a_r = 0;
  reg [width_b-1:0]   q_b_r = 0;

  integer i;
  initial begin
    for (i = 0; i < numwords_a; i = i + 1) mem[i] = 0;
    if (IS_ROM) $readmemh(init_file, mem);
  end

  always @(posedge clock0) begin
    addr_a_r <= address_a;
    addr_b_r <= address_b;
    q_a_r    <= mem[addr_a_r];
    q_b_r    <= mem[addr_b_r];
    if (!IS_ROM && wren_a) mem[address_a] <= data_a;
  end

  assign q_a = REG_A ? q_a_r : mem[addr_a_r];
  assign q_b = REG_B ? q_b_r : mem[addr_b_r];
  assign eccstatus = 3'b000;

endmodule
