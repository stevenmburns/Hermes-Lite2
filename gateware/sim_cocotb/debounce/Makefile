SIM ?= verilator
TOPLEVEL_LANG ?= verilog
PWD=$(shell pwd)
TOPDIR=$(PWD)/../../rtl

# DUT picks the design; test_debounce.py reads the same variable.
#   committed  rtl/debounce.v as committed (default)
#   fixed      a sed copy of it with stable = (&pb_history) | ~(|pb_history)
#   cl         candidates/debounce_cl.v     confirm 2, lock out 6
#   run        candidates/debounce_run.v    4 agreeing samples in a row
#   integ      candidates/debounce_integ.v  saturating counter 0..4
# `make all-duts` runs all five, each in its own sim_build_<dut>.
DUT ?= committed
export DUT

SIM_BUILD ?= sim_build_$(DUT)

ifeq ($(DUT),committed)
VERILOG_SOURCES += $(TOPDIR)/debounce.v
TOPLEVEL = debounce
else ifeq ($(DUT),fixed)
FIXED_SRC := $(PWD)/$(SIM_BUILD)/debounce_fixed.v
VERILOG_SOURCES += $(FIXED_SRC)
TOPLEVEL = debounce
else ifneq ($(filter $(DUT),cl run integ),)
VERILOG_SOURCES += $(PWD)/candidates/debounce_$(DUT).v
TOPLEVEL = debounce_$(DUT)
else
$(error DUT must be committed, fixed, cl, run or integ)
endif

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_debounce

EXTRA_ARGS += --trace --trace-depth 2

include $(shell cocotb-config --makefiles)/Makefile.sim

# After the include, so cocotb's target stays the default goal.
ifeq ($(DUT),fixed)
$(FIXED_SRC): $(TOPDIR)/debounce.v Makefile
	mkdir -p $(dir $@)
	sed 's/(&pb_history) | (|pb_history)/(\&pb_history) | ~(|pb_history)/' $< > $@
	grep -q '~(|pb_history)' $@
$(SIM_BUILD)/Vtop.mk: $(FIXED_SRC)
endif

.PHONY: all-duts
all-duts:
	@status=0; for d in committed fixed cl run integ; do \
	  $(MAKE) --no-print-directory DUT=$$d SIM_BUILD=sim_build_$$d > results_$$d.log 2>&1; rc=$$?; \
	  if [ $$rc -eq 0 ] && grep -q 'FAIL=0' results_$$d.log; then \
	    echo "PASS $$d"; else echo "FAIL $$d (results_$$d.log)"; status=1; fi; \
	done; exit $$status
