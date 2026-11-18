SIM ?= verilator
ALTERA_SIM_LIB ?= $(HOME)/altera_lite/25.1std/quartus/eda/sim_lib
TOPLEVEL_LANG ?= verilog
# Verilator 5.046 generates uncompilable C++ for the unused std::process class
COMPILE_ARGS += --no-std-package

GPI_IMPL := vpi

VERILOG_SOURCES += $(PWD)/../../rtl/sync.v
VERILOG_SOURCES += $(PWD)/../../rtl/ethernet/icmp.v
VERILOG_SOURCES += $(PWD)/../../rtl/ethernet/icmp_fifo.v
VERILOG_SOURCES += $(PWD)/../../rtl/fifos.v
# Altera megafunction simulation library (models altddio_*, dcfifo, ...)
VERILOG_SOURCES += $(ALTERA_SIM_LIB)/altera_mf.v

# --timing is needed by the vendor megafunction models; PROCASSWIRE because
# icmp.v drives its output dst_unreachable procedurally without declaring
# it as reg (accepted by Quartus)
COMPILE_ARGS += --timing -Wno-fatal -Wno-PROCASSWIRE

TOPLEVEL = icmp
MODULE = test_icmp

include $(shell cocotb-config --makefiles)/Makefile.sim
