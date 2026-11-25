SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl
PYTHON ?= python3

# 19 is the production window (2^19 samples, 6.8 ms); 12 runs many windows fast.
WINDOW_LOG2 ?= 12
WINDOWS ?= 8
STIM_LEN = $(shell echo $$(( $(WINDOWS) << $(WINDOW_LOG2) )))
export WINDOW_LOG2 WINDOWS
SIM_BUILD ?= sim_build_w$(WINDOW_LOG2)

VERILOG_SOURCES += $(PWD)/tb_adc_meter.sv
ADC_METER_V ?= $(TOPDIR)/adc_meter.v
VERILOG_SOURCES += $(ADC_METER_V)
VERILOG_SOURCES += $(TOPDIR)/sync.v

TOPLEVEL = tb_adc_meter
COMPILE_ARGS += -GWINDOW_LOG2=$(WINDOW_LOG2) -GSTIM_LEN=$(STIM_LEN) \
                --timing -Wno-fatal -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC

GPI_IMPL := vpi
export TOPLEVEL_LANG
MODULE=test_adc_meter

# stim.mem is read at time 0, so it is written before every run (it depends
# on WINDOW_LOG2 and WINDOWS). The rule follows the include so that cocotb's
# target stays the default.
CUSTOM_SIM_DEPS += stim

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: stim
stim:
	WINDOW_LOG2=$(WINDOW_LOG2) WINDOWS=$(WINDOWS) $(PYTHON) model.py

clean::
	rm -f stim.mem
