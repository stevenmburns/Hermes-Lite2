SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl
PYTHON ?= python3

# USE_ALTSYNCRAM selects the same ROM and RAM code paths as the production build.
COMPILE_ARGS += +define+USE_ALTSYNCRAM=1

VERILOG_SOURCES += $(PWD)/tb_rx_chain.sv
VERILOG_SOURCES += $(PWD)/altsyncram_model.v
VERILOG_SOURCES += $(TOPDIR)/nco/mix2.v
VERILOG_SOURCES += $(TOPDIR)/nco/nco2.v
VERILOG_SOURCES += $(TOPDIR)/nco/sincos.v
VERILOG_SOURCES += $(TOPDIR)/nco/coarserom.v
VERILOG_SOURCES += $(TOPDIR)/primitives/sim/multipliers.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/receiver_nco.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_comb.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_integrator.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/varcic_mem.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firfilt.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firram36.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firrom/firromH.v

TOPLEVEL = tb_rx_chain

COMPILE_ARGS += --timing -Wno-fatal -Wno-PROCASSWIRE -Wno-WIDTHEXPAND \
                -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE -Wno-IMPLICIT

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_rx_chain

MIF_FILES = $(TOPDIR)/nco/sincos_coarse.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4AE.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4BF.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4CG.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4DH.mif

CUSTOM_SIM_DEPS += rom_images.stamp

include $(shell cocotb-config --makefiles)/Makefile.sim

rom_images.stamp: mif2mem.py $(MIF_FILES)
	$(PYTHON) mif2mem.py . $(MIF_FILES)
	touch $@

clean::
	rm -f rom_images.stamp stim.mem *.mif
