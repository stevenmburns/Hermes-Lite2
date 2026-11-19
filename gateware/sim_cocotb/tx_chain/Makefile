SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl
RXCHAIN=$(PWD)/../rx_chain
PYTHON ?= python3

# USE_ALTSYNCRAM selects the same ROM and RAM code paths as the production build.
COMPILE_ARGS += +define+USE_ALTSYNCRAM=1

VERILOG_SOURCES += $(PWD)/tb_tx_chain.sv
VERILOG_SOURCES += $(RXCHAIN)/altsyncram_model.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/FirInterp8_1024.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firram36I_1024.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firrom/firromI_1024.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/CicInterpM5.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cpl_cordic.v

# hl2b5up_main builds the upconverter as tx_nco_upconv.  Run with TX_NCO=
# (empty) to test the CORDIC, cpl_cordic, instead.
TX_NCO ?= 1
ifneq ($(TX_NCO),)
COMPILE_ARGS += +define+TX_NCO=1
SIM_BUILD = sim_build_nco
VERILOG_SOURCES += $(TOPDIR)/nco/tx_nco_upconv.v
VERILOG_SOURCES += $(TOPDIR)/nco/sincos.v
VERILOG_SOURCES += $(TOPDIR)/nco/coarserom.v
VERILOG_SOURCES += $(TOPDIR)/primitives/sim/multipliers.v
endif

TOPLEVEL = tb_tx_chain

COMPILE_ARGS += --timing -Wno-fatal -Wno-PROCASSWIRE -Wno-WIDTHEXPAND \
                -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE -Wno-IMPLICIT

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_tx_chain

MIF_FILES = $(TOPDIR)/radio_openhpsdr1/firrom/coefI8_1024.mif \
            $(TOPDIR)/nco/sincos_coarse.mif

CUSTOM_SIM_DEPS += rom_images.stamp

include $(shell cocotb-config --makefiles)/Makefile.sim

# Depends on the Makefile too, so adding a file to MIF_FILES regenerates them.
rom_images.stamp: $(RXCHAIN)/mif2mem.py $(MIF_FILES) Makefile
	$(PYTHON) $(RXCHAIN)/mif2mem.py . $(MIF_FILES)
	touch $@

clean::
	rm -f rom_images.stamp stim.mem *.mif cic_out.bin fir_out.bin up_out.bin
