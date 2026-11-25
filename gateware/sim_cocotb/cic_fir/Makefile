SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl

NS ?= 24
export NS
SIM_BUILD ?= sim_build_ns$(NS)

VERILOG_SOURCES += $(PWD)/tb_cic_fir.sv
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_fir_shared.v

TOPLEVEL = tb_cic_fir
COMPILE_ARGS += -GNS=$(NS) --timing -Wno-fatal -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC \
                -Wno-SELRANGE -Wno-UNOPTFLAT -Wno-CASEINCOMPLETE \
                +incdir+$(TOPDIR)/radio_openhpsdr1

GPI_IMPL := vpi
export TOPLEVEL_LANG
MODULE=test_cic_fir

include $(shell cocotb-config --makefiles)/Makefile.sim
