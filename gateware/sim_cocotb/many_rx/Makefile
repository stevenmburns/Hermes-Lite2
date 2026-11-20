SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl
RXCHAIN_DIR=$(PWD)/../rx_chain
PYTHON ?= python3

# NR receivers in radio.v (1..12). radio.v picks CALCTYPE 0 above 5.
NR ?= 12
# CHAIN picks the receiver_nco source, as the variant .qsf files do:
#   full  receiver_nco.v      cic -> varcic_mem -> firX8R8, rate selectable
#   cic   receiver_ciconly.v  fixed CIC /16 /25, 192 ksps (hl2b5up_cicrx)
#   cicshared  the same, with CIC_SHARED: one cic_s2_shared for all receivers.
#              Each capture is compared bit for bit with the CHAIN=cic run's,
#              which `make compare-shared` runs first.
CHAIN ?= full
export NR CHAIN

SIM_BUILD ?= sim_build_$(CHAIN)_nr$(NR)

COMPILE_ARGS += +define+USE_ALTSYNCRAM=1
COMPILE_ARGS += -GNR=$(NR)
COMPILE_ARGS += +incdir+$(TOPDIR)

VERILOG_SOURCES += $(PWD)/tb_many_rx.sv
VERILOG_SOURCES += $(RXCHAIN_DIR)/altsyncram_model.v
# RADIO_V lets a run use another copy of radio.v (e.g. an older revision).
RADIO_V ?= $(TOPDIR)/radio_openhpsdr1/radio.v
VERILOG_SOURCES += $(RADIO_V)
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/vna_scanner.v
VERILOG_SOURCES += $(TOPDIR)/nco/mix2.v
VERILOG_SOURCES += $(TOPDIR)/nco/nco2.v
VERILOG_SOURCES += $(TOPDIR)/nco/sincos.v
VERILOG_SOURCES += $(TOPDIR)/nco/coarserom.v
VERILOG_SOURCES += $(TOPDIR)/nco/finerom.v
VERILOG_SOURCES += $(TOPDIR)/primitives/sim/multipliers.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_comb.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_integrator.v
ifeq ($(CHAIN),full)
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/receiver_nco.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/varcic_mem.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firfilt.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firram36.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/firrom/firromH.v
else ifeq ($(CHAIN),cic)
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/receiver_ciconly.v
else ifeq ($(CHAIN),cicshared)
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/receiver_ciconly.v
VERILOG_SOURCES += $(TOPDIR)/radio_openhpsdr1/cic_s2_shared.v
COMPILE_ARGS += +define+CIC_SHARED=1
else
$(error CHAIN must be full, cic or cicshared)
endif

TOPLEVEL = tb_many_rx

COMPILE_ARGS += --timing -Wno-fatal -Wno-PROCASSWIRE -Wno-WIDTHEXPAND \
                -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE -Wno-IMPLICIT \
                -Wno-MULTIDRIVEN -Wno-UNOPTFLAT -Wno-PARAMNODEFAULT

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_many_rx

MIF_FILES = $(TOPDIR)/nco/sincos_coarse.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4AE.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4BF.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4CG.mif \
            $(TOPDIR)/radio_openhpsdr1/firrom/coefL4DH.mif

CUSTOM_SIM_DEPS += rom_images.stamp

include $(shell cocotb-config --makefiles)/Makefile.sim

rom_images.stamp: $(RXCHAIN_DIR)/mif2mem.py $(MIF_FILES) $(TOPDIR)/nco/sin_fine.txt Makefile
	$(PYTHON) $(RXCHAIN_DIR)/mif2mem.py . $(MIF_FILES)
	cp $(TOPDIR)/nco/sin_fine.txt .
	touch $@

.PHONY: compare-shared
compare-shared:
	$(MAKE) CHAIN=cic NR=$(NR) SIM_BUILD=sim_build_cic_nr$(NR)
	$(MAKE) CHAIN=cicshared NR=$(NR) SIM_BUILD=sim_build_cicshared_nr$(NR)

clean::
	rm -f rom_images.stamp stim.mem rx_stream.bin *.mif sin_fine.txt frames_*.npy
