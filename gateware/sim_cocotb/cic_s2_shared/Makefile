SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl

NS ?= 24
export NS
SIM_BUILD ?= sim_build_ns$(NS)

VERILOG_SOURCES += $(PWD)/tb_cic_s2_shared.sv
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/receiver_ciconly.v
SHARED_V ?= $(TOPDIR)/radio_openhpsdr1/cic_s2_shared.v
VERILOG_SOURCES += $(SHARED_V)
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_integrator.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_comb.v

TOPLEVEL = tb_cic_s2_shared
COMPILE_ARGS += -GNS=$(NS) --timing -Wno-fatal -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
                -Wno-SELRANGE -Wno-UNOPTFLAT -Wno-CASEINCOMPLETE

GPI_IMPL := vpi
export TOPLEVEL_LANG
MODULE=test_cic_s2_shared

include $(shell cocotb-config --makefiles)/Makefile.sim
