SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl

# FIXED=1 simulates a copy of debounce.v with the stability test corrected to
# "all six samples equal", (&pb_history) | ~(|pb_history), instead of the RTL
# as committed. The tests read the same variable to pick their expectations.
FIXED ?=
export FIXED

ifeq ($(FIXED),)
SIM_BUILD ?= sim_build
VERILOG_SOURCES += $(TOPDIR)/debounce.v
else
SIM_BUILD ?= sim_build_fixed
FIXED_SRC := $(PWD)/$(SIM_BUILD)/debounce_fixed.v
VERILOG_SOURCES += $(FIXED_SRC)
endif

TOPLEVEL = debounce

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_debounce

EXTRA_ARGS += --trace --trace-depth 2

include $(shell cocotb-config --makefiles)/Makefile.sim

# After the include, so cocotb's target stays the default goal.
ifneq ($(FIXED),)
$(FIXED_SRC): $(TOPDIR)/debounce.v Makefile
	mkdir -p $(dir $@)
	sed 's/(&pb_history) | (|pb_history)/(\&pb_history) | ~(|pb_history)/' $< > $@
	grep -q '~(|pb_history)' $@
$(SIM_BUILD)/Vtop.mk: $(FIXED_SRC)
endif
