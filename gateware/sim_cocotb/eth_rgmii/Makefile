SIM ?= verilator
ALTERA_SIM_LIB ?= $(HOME)/altera_lite/25.1std/quartus/eda/sim_lib
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl

#DUT (both rgmii modules are exercised, each in its own test module)
VERILOG_SOURCES += $(TOPDIR)/ethernet/rgmii_recv.v
VERILOG_SOURCES += $(TOPDIR)/ethernet/rgmii_send.v
VERILOG_SOURCES += $(TOPDIR)/ethernet/ddio_in.v
VERILOG_SOURCES += $(TOPDIR)/ethernet/ddio_out.v
# Altera megafunction simulation library (models altddio_in/out)
VERILOG_SOURCES += $(ALTERA_SIM_LIB)/altera_mf.v
# thin wrapper exposing both DUTs with plain (non-DDR) test ports
VERILOG_SOURCES += $(PWD)/tb_rgmii.v

TOPLEVEL = tb_rgmii

# --timing is needed by the vendor megafunction models
COMPILE_ARGS += --timing -Wno-fatal

# Verilator 5.046 generates uncompilable C++ for the unused std::process class
COMPILE_ARGS += --no-std-package

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_rgmii

include $(shell cocotb-config --makefiles)/Makefile.sim
