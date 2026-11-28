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
#   hold       candidates/debounce_hold.v   both edges delayed D+1 samples;
#              HOLD_D (default 4) and HOLD_CONFIRM (default 1) set its parameters
# `make all-duts` runs all six, each in its own sim_build_<dut>;
# `make hold-sweep` runs hold for D = 2..6, with and without CONFIRM.
DUT ?= committed
HOLD_D ?= 4
HOLD_CONFIRM ?= 1
export DUT HOLD_D HOLD_CONFIRM

ifeq ($(DUT),hold)
SIM_BUILD ?= sim_build_hold_d$(HOLD_D)_c$(HOLD_CONFIRM)
else
SIM_BUILD ?= sim_build_$(DUT)
endif

ifeq ($(DUT),committed)
VERILOG_SOURCES += $(TOPDIR)/debounce.v
TOPLEVEL = debounce
else ifeq ($(DUT),fixed)
FIXED_SRC := $(PWD)/$(SIM_BUILD)/debounce_fixed.v
VERILOG_SOURCES += $(FIXED_SRC)
TOPLEVEL = debounce
else ifneq ($(filter $(DUT),cl run integ hold),)
VERILOG_SOURCES += $(PWD)/candidates/debounce_$(DUT).v
TOPLEVEL = debounce_$(DUT)
else
$(error DUT must be committed, fixed, cl, run, integ or hold)
endif

GPI_IMPL := vpi

export TOPLEVEL_LANG
MODULE=test_debounce

EXTRA_ARGS += --trace --trace-depth 2
ifeq ($(DUT),hold)
EXTRA_ARGS += -GD=$(HOLD_D) -GCONFIRM=$(HOLD_CONFIRM)
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

# After the include, so cocotb's target stays the default goal.
ifeq ($(DUT),fixed)
$(FIXED_SRC): $(TOPDIR)/debounce.v Makefile
	mkdir -p $(dir $@)
	sed 's/(&pb_history) | (|pb_history)/(\&pb_history) | ~(|pb_history)/' $< > $@
	grep -q '~(|pb_history)' $@
$(SIM_BUILD)/Vtop.mk: $(FIXED_SRC)
endif

.PHONY: all-duts hold-sweep traces

# Scenario traces for plot_traces.py: one traces_<dut>.json per design.
traces:
	@for d in committed fixed cl integ; do \
	  COCOTB_TEST_FILTER=test_dump_scenarios $(MAKE) --no-print-directory DUT=$$d \
	    SIM_BUILD=sim_build_$$d > traces_$$d.log 2>&1 || { echo "FAIL $$d"; exit 1; }; \
	done
	@for d in 2 4; do \
	  COCOTB_TEST_FILTER=test_dump_scenarios $(MAKE) --no-print-directory DUT=hold HOLD_D=$$d \
	    HOLD_CONFIRM=1 SIM_BUILD=sim_build_hold_d$${d}_c1 > traces_hold_d$$d.log 2>&1 \
	    || { echo "FAIL hold D=$$d"; exit 1; }; \
	done
	@grep -h "FAIL=" traces_*.log
all-duts:
	@status=0; for d in committed fixed cl run integ hold; do \
	  $(MAKE) --no-print-directory DUT=$$d SIM_BUILD=sim_build_$$d > results_$$d.log 2>&1; rc=$$?; \
	  if [ $$rc -eq 0 ] && grep -q 'FAIL=0' results_$$d.log; then \
	    echo "PASS $$d"; else echo "FAIL $$d (results_$$d.log)"; status=1; fi; \
	done; exit $$status

hold-sweep:
	@status=0; for c in 0 1; do for d in 2 3 4 5 6; do \
	  log=results_hold_d$${d}_c$${c}.log; \
	  $(MAKE) --no-print-directory DUT=hold HOLD_D=$$d HOLD_CONFIRM=$$c \
	    SIM_BUILD=sim_build_hold_d$${d}_c$${c} > $$log 2>&1; rc=$$?; \
	  if [ $$rc -eq 0 ] && grep -q 'FAIL=0' $$log; then \
	    echo "PASS hold D=$$d CONFIRM=$$c"; else echo "FAIL hold D=$$d CONFIRM=$$c ($$log)"; status=1; fi; \
	done; done; exit $$status
