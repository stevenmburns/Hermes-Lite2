"""cocotb bench for rtl/adc_meter.v and its crossing into the control clock.

Every meter word latched at the ADC clock must match the model, and the
control-clock side (sync_qualifier, as in hermeslite_core) must see each one
exactly once, in order, unchanged.
"""

import numpy as np

import cocotb
from cocotb.triggers import ClockCycles, Edge, ReadOnly, RisingEdge, Timer

import model

L = model.L
CLK_PS = 13020


@cocotb.test()
async def test_meter_windows(dut):
    stim = model.stimulus()
    nwin = model.WINDOWS + 1          # the stimulus straddles one extra window
    src, ctrl = [], []

    async def watch_src():
        while True:
            await Edge(dut.meter_toggle)
            await Timer(1, unit="ps")
            src.append(int(dut.meter.value))

    async def watch_ctrl():
        # data_out loads on the clock edge that ends the valid pulse, so read
        # it after the next edge.
        while True:
            await RisingEdge(dut.clk_ctrl)
            await ReadOnly()
            if int(dut.meter_ctrl_valid.value):
                await RisingEdge(dut.clk_ctrl)
                await ReadOnly()
                ctrl.append(int(dut.meter_ctrl.value))

    dut.go.value = 0
    cocotb.start_soon(watch_src())
    cocotb.start_soon(watch_ctrl())
    await ClockCycles(dut.clk_ad, 3)
    dut.go.value = 1
    await Timer((nwin * L + 64) * CLK_PS, unit="ps")
    await Timer(4_000_000, unit="ps")   # let the last word cross (10 control clocks)

    g = int(dut.go_count.value)
    assert len(src) >= nwin, f"only {len(src)} meter updates for {nwin} windows"
    got = src[:nwin]

    matches = []
    for d in range(g, g + 6):
        x = np.zeros(nwin * L, dtype=np.int64)
        n = min(len(stim), nwin * L - d)
        x[d:d + n] = stim[:n]
        if model.windows(x, nwin) == got:
            matches.append(d)
    if len(matches) != 1:
        x = np.zeros(nwin * L, dtype=np.int64)
        x[g + 2:g + 2 + len(stim)] = stim[:nwin * L - g - 2]
        want = model.windows(x, nwin)
        for k, (a, b) in enumerate(zip(got, want)):
            dut._log.info("window %d: rtl %08x model(d=%d) %08x", k, a, g + 2, b)
    assert len(matches) == 1, f"input delays matching every window: {matches} (go at clock {g})"

    for k, w in enumerate(got):
        dut._log.info("window %d: clips %5d  number %2d  peak %4d", k, w >> 16, (w >> 12) & 0xF, w & 0xFFF)
    clips = [w >> 16 for w in got]
    peaks = [w & 0xFFF for w in got]
    # The stimulus must actually reach the interesting cases.
    assert 0 in clips and max(clips) > 40, "stimulus did not exercise clip counting"
    assert 2048 in peaks and 2047 in peaks and 0 in peaks, "stimulus missed a peak case"
    if L > 0xFFFF:
        assert 0xFFFF in clips, "the all-clip window did not saturate the count"

    assert ctrl == src, (f"control side saw {len(ctrl)} words, source latched {len(src)};"
                         f" first difference at {next((i for i, (a, b) in enumerate(zip(ctrl, src)) if a != b), min(len(ctrl), len(src)))}")
    dut._log.info("input delay %d clocks after go; %d windows match the model; control side saw all %d, in order",
                  matches[0] - g, nwin, len(ctrl))
