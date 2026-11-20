"""cic_s2_shared against NS separate cic_s2 instances, every output."""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ReadOnly

NS = int(os.environ.get("NS", "24"))
OUTPUTS = int(os.environ.get("OUTPUTS", "1500"))


async def collect(dut, strobe, data, n, out, when):
    while len(out) < n:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(strobe.value):
            v = int(data.value)
            out.append([(v >> (24 * s)) & 0xFFFFFF for s in range(NS)])
            when.append(cocotb.utils.get_sim_time("ns"))


async def run(dut, quiet):
    dut.quiet.value = int(quiet)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    ref, dut_out, t_ref, t_dut = [], [], [], []
    a = cocotb.start_soon(collect(dut, dut.ref_strobe, dut.ref_data, OUTPUTS,
                                  ref, t_ref))
    b = cocotb.start_soon(collect(dut, dut.dut_strobe, dut.dut_data, OUTPUTS,
                                  dut_out, t_dut))
    await a
    await b
    bad = [(k, s) for k in range(OUTPUTS) for s in range(NS)
           if ref[k][s] != dut_out[k][s]]
    nonzero = sum(1 for k in range(OUTPUTS) for s in range(NS) if ref[k][s])
    lag = sorted({round((d - r) / 10) for r, d in zip(t_ref, t_dut)})
    dut._log.info("NS=%d quiet=%s: %d outputs x %d streams, %d mismatches, "
                  "%d nonzero reference values, strobe lag %s clocks",
                  NS, quiet, OUTPUTS, NS, len(bad), nonzero, lag)
    assert nonzero > OUTPUTS * NS // 2, "reference mostly zero: not exercised"
    assert not bad, f"first mismatch output {bad[0][0]} stream {bad[0][1]}: " \
        f"ref {ref[bad[0][0]][bad[0][1]]:06x} got {dut_out[bad[0][0]][bad[0][1]]:06x}"


@cocotb.test()
async def test_full_scale_random(dut):
    await run(dut, quiet=False)


@cocotb.test()
async def test_quiet_random(dut):
    """Inputs within +/-2^9, so the high bits are sign copies."""
    await run(dut, quiet=True)
