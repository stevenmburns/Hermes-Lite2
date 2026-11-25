"""cic_fir_shared against the bit-exact model (model.py), plus a tone test that
measures the response from the RTL output alone.

Every test checks, for all NS streams and every output:
  * the RTL output equals the model's, once the two decimation phases and the
    output offset are found (the search must find exactly one alignment),
  * out_strobe comes every 400 clocks,
  * out_data does not change in the 2*12+6 clocks after out_strobe, while
    radio.v reads it, and reports how long it actually stays put.
"""

import os

import cocotb
import numpy as np
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge

import model

NS = int(os.environ.get("NS", "24"))
HOLD = 2 * 12 + 6
FS1 = 4.8e6
OLD_GAIN = 64 * 25**4 / 2**19


def pack(col):
    v = 0
    for s, a in enumerate(col):
        v |= (int(a) & 0x3FFFF) << (18 * s)
    return v


async def drive(dut, X):
    """Present frame n's inputs during frame n-1, so the strobe1 edge latches them."""
    dut.x_next.value = pack(X[:, 0])
    n = 1
    while n < X.shape[1]:
        await RisingEdge(dut.clk)
        await ReadOnly()
        if int(dut.strobe1.value):
            await RisingEdge(dut.clk)          # this edge latches frame n-1's value
            dut.x_next.value = pack(X[:, n])
            n += 1


async def collect(dut, n_out, out, gaps, holds):
    clk = 0
    last = None
    pending = []          # (clock of strobe, value at strobe)
    while len(out) < n_out or pending:
        await RisingEdge(dut.clk)
        await ReadOnly()
        clk += 1
        v = int(dut.dut_data.value)
        still = []
        for (t0, v0) in pending:
            if v != v0:
                holds.append(clk - t0)
            elif clk - t0 < 400:
                still.append((t0, v0))
            else:
                holds.append(400)
        pending = still
        if int(dut.dut_strobe.value) and len(out) < n_out:
            out.append([(v >> (24 * s)) & 0xFFFFFF for s in range(NS)])
            if last is not None:
                gaps.append(clk - last)
            last = clk
            pending.append((clk, v))


def signed24(a):
    a = np.asarray(a, dtype=np.int64)
    return np.where(a >= 1 << 23, a - (1 << 24), a)


def align(X, got, skip):
    """Find (cic_phase, fir_phase, offset) with got[k] == model[k + offset] for stream 0,
    ignoring the first `skip` outputs."""
    g0 = got[:, 0]
    hits = []
    for p in range(5):
        for q in range(5):
            m = model.chain(X[0], p, q)
            for off in range(-3, 4):
                a, b = skip + max(0, -off), skip + max(0, off)
                n = min(len(g0) - a, len(m) - b)
                if n > len(g0) - skip - 10 and np.array_equal(g0[a:a + n], m[b:b + n]):
                    hits.append((p, q, off, a, b, n))
    return hits


async def run(dut, X, label, skip=40):
    """skip: outputs to ignore while state left by an earlier test in the same
    simulation flushes out (the CIC forgets its start state after 4 outputs, the
    FIR after 22). The first test runs from power-up and uses skip=0."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    n_out = X.shape[1] // 25 - 3
    out, gaps, holds = [], [], []
    cocotb.start_soon(drive(dut, X))
    await collect(dut, n_out, out, gaps, holds)
    got = signed24(np.array(out))
    if os.environ.get("DUMP"):
        np.save(f"dump_{label.replace(' ', '_')}_X.npy", X)
        np.save(f"dump_{label.replace(' ', '_')}_got.npy", got)
    hits = align(X, got, skip)
    assert len(hits) == 1, f"{label}: expected one alignment, found {hits}"
    p, q, off, a, b, n = hits[0]
    bad = 0
    for s in range(NS):
        m = model.chain(X[s], p, q)
        bad += int(np.count_nonzero(got[a:a + n, s] != m[b:b + n]))
    nonzero = int(np.count_nonzero(got[a:a + n]))
    dut._log.info("%s: %d outputs x %d streams compared, %d mismatches, %d nonzero; "
                  "phases cic %d fir %d offset %d; strobe gaps %s; "
                  "out_data held %d..%d clocks after out_strobe",
                  label, n, NS, bad, nonzero, p, q, off, sorted(set(gaps)),
                  min(holds), max(holds))
    assert nonzero > n * NS // 2, "output mostly zero: not exercised"
    assert bad == 0
    assert set(gaps) == {400}, f"strobe spacing {sorted(set(gaps))}"
    assert min(holds) >= HOLD, f"out_data changed {min(holds)} clocks after out_strobe"
    return got[a:a + n]


@cocotb.test()
async def test_full_scale_random(dut):
    rng = np.random.default_rng(1)
    X = rng.integers(-(1 << 17), 1 << 17, size=(NS, 25 * 400))
    await run(dut, X, "full-scale random", skip=0)


@cocotb.test()
async def test_quiet_random(dut):
    rng = np.random.default_rng(2)
    X = rng.integers(-(1 << 9), 1 << 9, size=(NS, 25 * 400))
    await run(dut, X, "quiet random")


def worst_case_pattern():
    """A full-scale +-1 input matched to the chain's impulse response (CIC R=5 at
    4.8 MHz, then the FIR): sum|g| is 1.7 x the DC gain, so it drives the output
    past +2^23 - 1 (its inverse past -2^23), unlike any sine or square wave."""
    h, _ = model.load_coefs()
    c = np.ones(5)
    for _ in range(3):
        c = np.convolve(c, np.ones(5))
    up = np.zeros(len(h) * 5 - 4)
    up[::5] = h
    g = np.convolve(c, up)
    return np.where(g[::-1] >= 0, (1 << 17) - 1, -(1 << 17))


@cocotb.test()
async def test_saturation(dut):
    """Worst-case inputs: the output must clip at both limits exactly as the model does.
    The 557-frame pattern is not a multiple of 5 long, so it meets every decimation phase."""
    nfr = 25 * 400
    pat = worst_case_pattern()
    X = np.zeros((NS, nfr), dtype=np.int64)
    for s in range(NS):
        x = np.roll(np.tile(pat, nfr // len(pat) + 2), 37 * s)[:nfr]
        X[s] = x if s % 2 == 0 else -x - 1
    got = await run(dut, X, "saturation")
    hi = int(np.count_nonzero(got == (1 << 23) - 1))
    lo = int(np.count_nonzero(got == -(1 << 23)))
    dut._log.info("saturation: %d outputs at +2^23-1, %d at -2^23", hi, lo)
    assert hi > 0 and lo > 0, "the output never reached both limits: saturation not exercised"


# Tones on 187.5 Hz bins (192 kHz / 1024), so a 1024-point FFT needs no window.
PASS_KHZ = [9.375, 30.0, 49.875, 60.0, 69.9375, 75.0]
# The first four are FIR images; the last two are the second CIC's images next to
# its first null (960 kHz -60 and +75 kHz), about -89 dBc. Those sit near one LSB
# of the CIC's 18-bit output, so they get full-scale inputs and only have to read
# below -80 dBc and above zero. The bit-exact comparison is the real check of the
# arithmetic; design.py covers the response of the whole chain.
ALIAS_KHZ = [117.0, 151.875, 222.0, 324.0, 900.0, 1035.0]   # fold to -75, -40.1, +30, -60, -60, +75


@cocotb.test()
async def test_tones(dut):
    """Stream pair c carries a complex tone; check passband gain and image rejection."""
    import design
    hq, sh = model.load_coefs()
    freqs = (PASS_KHZ + ALIAS_KHZ)[:NS // 2]
    nfr = 25 * (1024 + 80)
    t = np.arange(nfr) / FS1
    X = np.zeros((NS, nfr), dtype=np.int64)
    amp = []
    for c, fk in enumerate(freqs):
        A = (1 << 16) if fk in PASS_KHZ else (1 << 17) - 1
        amp.append(A)
        ph = 2 * np.pi * fk * 1e3 * t
        X[2 * c] = np.round(A * np.cos(ph))
        X[2 * c + 1] = np.round(A * np.sin(ph))
    got = await run(dut, X, "tones")
    y = got[-1024:]
    assert len(y) == 1024, f"only {len(y)} outputs for the 1024-point FFT"
    failures = []
    for c, fk in enumerate(freqs):
        z = (y[:, 2 * c] + 1j * y[:, 2 * c + 1]) / (amp[c] * OLD_GAIN)
        Z = np.fft.fft(z) / 1024
        fo = ((fk * 1e3 + 96e3) % 192e3) - 96e3
        k = int(round(fo / 187.5)) % 1024
        lvl = 20 * np.log10(abs(Z[k]) + 1e-20)
        spur = np.abs(Z.copy()); spur[k] = 0
        worst = 20 * np.log10(spur.max() + 1e-20)
        if fk in PASS_KHZ:
            f = fk * 1e3
            n = np.arange(len(hq))
            pred = design.cic(f, 5, 4, FS1) * abs(np.exp(-2j * np.pi * f / 960e3 * n) @ hq) / 2**sh / design.FIR_GAIN
            pred_db = 20 * np.log10(pred)
            dut._log.info(f"pass  {fk:9.4f} kHz: {lvl:+8.3f} dB (design {pred_db:+.3f}), largest other bin {worst:7.1f} dB")
            if abs(lvl - pred_db) >= 0.02:
                failures.append(f"{fk} kHz gain {lvl:.3f} dB, design {pred_db:.3f}")
            if worst >= -80:
                failures.append(f"{fk} kHz: spur at {worst:.1f} dB")
        else:
            dut._log.info(f"image {fk:9.4f} kHz -> {fo/1e3:+8.3f} kHz: {lvl:7.1f} dBc")
            if lvl >= -80:
                failures.append(f"image of {fk} kHz at {lvl:.1f} dBc")
            if Z[k] == 0:
                failures.append(f"image of {fk} kHz is exactly zero: measured nothing")
    assert not failures, "; ".join(failures)
