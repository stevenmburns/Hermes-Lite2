"""cocotb tests for rtl/debounce.v, the CW key, PTT and TX-inhibit debouncer.

debounce samples pb on each msec_pulse into a six-sample history. On a pulse
where the history (before that pulse's sample is added) is "stable", clean_pb
takes the new sample; otherwise clean_pb holds. The header comment describes
the intent: "immediate response if last signal stabilized", i.e. stable means
all six samples equal, so the first edge after a quiet period goes straight
through and bounce is ignored until the input has been steady for six samples.

The committed RTL computes stable = (&pb_history) | (|pb_history), which is
just |pb_history. Run with FIXED=1 to simulate the corrected expression,
(&pb_history) | ~(|pb_history). The model tests pass either way; the
specification tests are expected to fail on the committed RTL.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

FIXED = bool(os.environ.get("FIXED"))
MS_CLOCKS = 8          # clocks per msec_pulse; the RTL only acts on pulses
HISTORY = 6


class Debounce:
    """Pulse-level model of debounce.v, committed or corrected."""

    def __init__(self, fixed):
        self.fixed = fixed
        self.history = 0
        self.clean = 0

    def stable(self):
        if self.fixed:
            return self.history in (0, (1 << HISTORY) - 1)
        return self.history != 0          # (&h) | (|h) == |h

    def pulse(self, pb):
        if self.stable():
            self.clean = pb
        self.history = ((self.history << 1) | pb) & ((1 << HISTORY) - 1)
        return self.clean


def run_model(samples, fixed):
    model = Debounce(fixed)
    return [model.pulse(s) for s in samples]


async def setup(dut):
    """Start the clock and settle to an all-zero history with pb released."""
    dut.pb.value = 0
    dut.msec_pulse.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await FallingEdge(dut.clk)
    await drive(dut, [0] * (HISTORY + 2))


async def drive(dut, samples):
    """Present one pb value per millisecond; return clean_pb after each pulse.

    Inputs change on falling edges. Also checks that clean_pb never changes
    except on the clock edge that samples a msec_pulse.
    """
    out = []
    for s in samples:
        dut.pb.value = s
        for k in range(MS_CLOCKS):
            pulse = k == MS_CLOCKS - 1
            dut.msec_pulse.value = int(pulse)
            before = int(dut.clean_pb.value)
            await RisingEdge(dut.clk)
            await FallingEdge(dut.clk)
            if not pulse:
                assert int(dut.clean_pb.value) == before, \
                    "clean_pb changed without a msec_pulse"
        dut.msec_pulse.value = 0
        out.append(int(dut.clean_pb.value))
    return out


def history_before(samples, i):
    """The six samples in pb_history when sample i is taken (setup was 0s)."""
    padded = [0] * HISTORY + list(samples)
    return padded[i:i + HISTORY]


def edges(trace):
    return sum(1 for a, b in zip(trace, trace[1:]) if a != b)


def first_change(trace, start, value):
    for i in range(start, len(trace)):
        if trace[i] == value:
            return i - start
    return None


# Keying with contact bounce on both edges, one sample per millisecond. Real
# bounce is faster than 1 ms; what the RTL sees is the level at each pulse.
PRESS_BOUNCE = [1, 0, 1, 1, 0, 1]
RELEASE_BOUNCE = [0, 1, 0, 0, 1, 0]


def bouncy_key(down_ms=20, up_ms=20):
    return (PRESS_BOUNCE + [1] * (down_ms - len(PRESS_BOUNCE)) +
            RELEASE_BOUNCE + [0] * (up_ms - len(RELEASE_BOUNCE)))


# --------------------------------------------------------------- model tests

@cocotb.test()
async def test_matches_model_random(dut):
    """The RTL matches the pulse model on random bouncy keying, every pulse."""
    await setup(dut)
    rng = random.Random(182)
    samples = []
    level = 0
    while len(samples) < 2000:
        level ^= 1
        samples += [rng.randint(0, 1) for _ in range(rng.randint(0, 5))]
        samples += [level] * rng.randint(1, 15)
    got = await drive(dut, samples)
    model = Debounce(FIXED)
    for _ in range(HISTORY + 2):
        model.pulse(0)
    want = [model.pulse(s) for s in samples]
    mismatches = sum(g != w for g, w in zip(got, want))
    dut._log.info("%s RTL: %d pulses, %d mismatches, %d output edges "
                  "for %d input edges", "fixed" if FIXED else "committed",
                  len(samples), mismatches, edges(got), edges(samples))
    assert mismatches == 0


@cocotb.test()
async def test_model_distinguishes_versions(dut):
    """The two expressions differ on bouncy keying (guards the model test)."""
    samples = bouncy_key()
    assert run_model(samples, fixed=True) != run_model(samples, fixed=False)


# ------------------------------------------------------- specification tests

@cocotb.test(expect_fail=not FIXED)
async def test_bounce_gives_one_press_and_one_release(dut):
    """A bouncy key press and release give exactly two clean_pb edges."""
    await setup(dut)
    got = await drive(dut, bouncy_key() * 3)
    dut._log.info("clean_pb edges: %d (want 6) %s", edges([0] + got),
                  "".join(map(str, got)))
    assert edges([0] + got) == 6


@cocotb.test(expect_fail=not FIXED)
async def test_press_is_immediate(dut):
    """After a quiet period the first sample of a press reaches clean_pb."""
    await setup(dut)
    got = await drive(dut, bouncy_key())
    press = first_change(got, 0, 1)
    release = first_change(got, 20, 0)
    dut._log.info("latency after the sampling pulse: press %s ms, "
                  "release %s ms", press, release)
    assert press == 0 and release == 0


@cocotb.test()
async def test_release_is_immediate(dut):
    """Both versions release on the first low sample after a steady press."""
    await setup(dut)
    got = await drive(dut, [1] * 20 + [0] * 10)
    assert first_change(got, 20, 0) == 0


@cocotb.test(expect_fail=not FIXED)
async def test_steady_input_after_bounce_is_followed(dut):
    """Once the input has been steady for six samples, clean_pb equals it."""
    await setup(dut)
    samples = bouncy_key(down_ms=12, up_ms=12) * 4
    got = await drive(dut, samples)
    bad = [i for i in range(len(samples))
           if len(set(history_before(samples, i) + [samples[i]])) == 1
           and got[i] != samples[i]]
    prev = [0] + got
    worse = [i for i in range(len(samples))
             if got[i] != prev[i] and len(set(history_before(samples, i))) > 1]
    dut._log.info("steady samples not followed: %d; output changes while the "
                  "history was bouncing: %d", len(bad), len(worse))
    assert not bad and not worse


@cocotb.test()
async def test_single_sample_glitch(dut):
    """A 1 ms spike from idle: the trade-off between the two versions.

    The committed RTL ignores it (the empty history is not "stable"). The
    corrected one passes the first edge through immediately and then holds it
    until the history is steady again, so the spike becomes a 7 ms pulse.
    """
    await setup(dut)
    got = await drive(dut, [1] + [0] * 12)
    width = sum(got)
    dut._log.info("1 ms spike gives a %d ms clean_pb pulse", width)
    assert width == (7 if FIXED else 0)
