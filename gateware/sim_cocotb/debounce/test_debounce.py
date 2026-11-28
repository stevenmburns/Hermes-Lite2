"""cocotb tests for rtl/debounce.v and candidate replacements.

All designs have debounce.v's ports and sample pb once per msec_pulse. DUT
selects which one is simulated (see the Makefile):

  committed   rtl/debounce.v as it is: stable = (&h) | (|h), which is |h
  fixed       the same file with stable = (&h) | ~(|h), what its comment
              describes: "immediate response if last signal stabilized"
  cl          candidates/debounce_cl.v: confirm 2 samples, then lock out 6
  run         candidates/debounce_run.v: switch after 4 agreeing samples
  integ       candidates/debounce_integ.v: saturating counter, 0..4
  hold        candidates/debounce_hold.v: both edges D+1 samples late, so the
              element keeps its width (HOLD_D, HOLD_CONFIRM)

Each design has a pulse-level Python model. test_matches_model_* check the RTL
against it on every pulse. The property tests then check behaviour; a design
that is not expected to have a property has that test marked expect_fail, so
every run reports all tests passing and any change in behaviour shows up as a
failure. test_keying_metrics logs the numbers compared in README.md.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

DUT = os.environ.get("DUT", "committed")
MS_CLOCKS = 8          # clocks per msec_pulse; the RTL only acts on pulses
HISTORY = 6


# ------------------------------------------------------------------- models

class ShiftHistory:
    """rtl/debounce.v, committed (fixed=False) or corrected (fixed=True)."""

    def __init__(self, fixed):
        self.fixed = fixed
        self.history = 0
        self.clean = 0

    def pulse(self, pb):
        if self.fixed:
            stable = self.history in (0, (1 << HISTORY) - 1)
        else:
            stable = self.history != 0
        if stable:
            self.clean = pb
        self.history = ((self.history << 1) | pb) & ((1 << HISTORY) - 1)
        return self.clean


class ConfirmLockout:
    IDLE, CHECK, LOCK = range(3)

    def __init__(self, confirm=2, lockout=6):
        self.confirm, self.lockout = confirm, lockout
        self.state, self.cnt, self.clean = self.IDLE, 0, 0

    def pulse(self, pb):
        if self.state == self.IDLE:
            if pb != self.clean:
                if self.confirm <= 1:
                    self.clean, self.state, self.cnt = pb, self.LOCK, 0
                else:
                    self.state, self.cnt = self.CHECK, 1
        elif self.state == self.CHECK:
            if pb == self.clean:
                self.state = self.IDLE
            elif self.cnt == self.confirm - 1:
                self.clean, self.state, self.cnt = pb, self.LOCK, 0
            else:
                self.cnt += 1
        else:
            if self.cnt == self.lockout - 1:
                self.state = self.IDLE
            else:
                self.cnt += 1
        return self.clean


class RunLength:
    def __init__(self, n=4):
        self.n, self.last, self.run, self.clean = n, 0, 0, 0

    def pulse(self, pb):
        run = 1 if pb != self.last else min(self.run + 1, self.n)
        self.last, self.run = pb, run
        if run == self.n:
            self.clean = pb
        return self.clean


class Integrator:
    def __init__(self, top=4):
        self.top, self.cnt, self.clean = top, 0, 0

    def pulse(self, pb):
        self.cnt = min(self.cnt + 1, self.top) if pb else max(self.cnt - 1, 0)
        if self.cnt == self.top:
            self.clean = 1
        if self.cnt == 0:
            self.clean = 0
        return self.clean


class EqualDelay:
    """candidates/debounce_hold.v: both edges D+1 samples late."""

    def __init__(self, d=4, confirm=1):
        self.d, self.confirm = d, confirm
        self.history, self.clean = 0, 0

    def pulse(self, pb):
        oldest = (self.history >> self.d) & 1
        newer = self.history & ((1 << self.d) - 1)
        if oldest and (not self.confirm or newer):
            self.clean = 1
        elif self.history == 0:
            self.clean = 0
        self.history = ((self.history << 1) | pb) & ((1 << (self.d + 1)) - 1)
        return self.clean


HOLD_D = int(os.environ.get("HOLD_D", "4"))
HOLD_CONFIRM = int(os.environ.get("HOLD_CONFIRM", "1"))

MODELS = {
    "committed": lambda: ShiftHistory(fixed=False),
    "fixed": lambda: ShiftHistory(fixed=True),
    "cl": ConfirmLockout,
    "run": RunLength,
    "integ": Integrator,
    "hold": lambda: EqualDelay(HOLD_D, HOLD_CONFIRM),
}


def run_model(samples, name=DUT, settle=HISTORY + 2):
    model = MODELS[name]()
    for _ in range(settle):
        model.pulse(0)
    return [model.pulse(s) for s in samples]


# ------------------------------------------------------------------- driver

async def setup(dut):
    """Start the clock and settle with pb released."""
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


def edges(trace, start=0):
    trace = [start] + list(trace)
    return sum(1 for a, b in zip(trace, trace[1:]) if a != b)


# ---------------------------------------------------------------- stimulus

PRESS_BOUNCE = [1, 0, 1, 1, 0, 1]
RELEASE_BOUNCE = [0, 1, 0, 0, 1, 0]


def bouncy_key(down_ms=20, up_ms=20):
    return (PRESS_BOUNCE + [1] * (down_ms - len(PRESS_BOUNCE)) +
            RELEASE_BOUNCE + [0] * (up_ms - len(RELEASE_BOUNCE)))


def keying(seed, elements=150, spikes=False):
    """Random keying with bounce, one sample per millisecond.

    Key-down and key-up times are 12 to 60 ms (a dit at 100 WPM is 12 ms).
    Each edge bounces for 0 to 6 ms (Ganssle's worst switch: 6.2 ms) as random
    samples, starting with the new level. With spikes, steady stretches also
    get isolated one-sample inversions at least 8 ms from any edge. Returns the
    samples and, per element, the true press and release sample indices.
    """
    rng = random.Random(seed)
    samples, marks = [0] * 30, []

    def stretch(level, length):
        body = [level] * length
        if spikes and length > 20:
            placed = []
            for _ in range(rng.randint(0, 2)):
                k = rng.randint(8, length - 9)
                if all(abs(k - j) >= 3 for j in placed):   # keep them isolated
                    body[k] = 1 - level
                    placed.append(k)
        return body

    for _ in range(elements):
        for level in (1, 0):
            if level:
                press = len(samples)
            else:
                release = len(samples)
            bounce = rng.randint(0, 6)
            edge = ([level] + [rng.randint(0, 1) for _ in range(bounce - 1)]
                    if bounce else [])
            length = rng.randint(12, 60)
            samples += edge + stretch(level, length - len(edge))
        marks.append((press, release))
    samples += [0] * 30
    return samples, marks


def keying_metrics(out, marks):
    """Delays and width errors, pairing output edges with keyed elements."""
    rises = [i for i in range(len(out)) if out[i] and (i == 0 or not out[i - 1])]
    falls = [i for i in range(1, len(out)) if not out[i] and out[i - 1]]
    extra = len(rises) + len(falls) - 2 * len(marks)
    if extra:
        return {"extra_edges": extra}
    press = [r - p for r, (p, _) in zip(rises, marks)]
    release = [f - q for f, (_, q) in zip(falls, marks)]
    width = [(f - r) - (q - p) for r, f, (p, q) in zip(rises, falls, marks)]
    return {"extra_edges": 0, "press": press, "release": release,
            "width": width}


# ------------------------------------------------------------ expectations

# Which properties each design has; property tests are expect_fail otherwise.
EXPECT = {
    #             bounce  immediate  realistic  spikes  width
    "committed": (False,  False,     False,     False,  False),
    "fixed":     (True,   True,      True,      False,  True),
    "cl":        (True,   False,     True,      True,   False),
    "run":       (True,   False,     True,      True,   False),
    "integ":     (True,   False,     True,      True,   False),
    # hold: the bench's bounce has gaps of up to 5 samples, so it needs D >= 4
    # (D >= 3 with CONFIRM) to give no extra edges, and D >= 5 with CONFIRM to
    # keep every press delay at D+1. Isolated spikes 3 samples apart can both
    # sit in the window, so CONFIRM does not reject all of them.
    "hold":      (HOLD_D >= 2, False,
                  HOLD_D >= (3 if HOLD_CONFIRM else 4), False,
                  HOLD_D >= (5 if HOLD_CONFIRM else 4)),
}


def expect_fail(index):
    return not EXPECT[DUT][index]


# -------------------------------------------------------------- model tests

@cocotb.test()
async def test_matches_model_random(dut):
    """The RTL matches its model on random bouncy input, every pulse."""
    await setup(dut)
    rng = random.Random(182)
    samples, level = [], 0
    while len(samples) < 2000:
        level ^= 1
        samples += [rng.randint(0, 1) for _ in range(rng.randint(0, 5))]
        samples += [level] * rng.randint(1, 15)
    got = await drive(dut, samples)
    want = run_model(samples)
    mismatches = sum(g != w for g, w in zip(got, want))
    dut._log.info("%s: %d pulses, %d mismatches, %d output edges for %d input "
                  "edges", DUT, len(samples), mismatches, edges(got),
                  edges(samples))
    assert mismatches == 0


@cocotb.test()
async def test_matches_model_keying(dut):
    """The RTL matches its model on realistic keying with spikes."""
    await setup(dut)
    samples, _ = keying(seed=7, elements=40, spikes=True)
    got = await drive(dut, samples)
    assert got == run_model(samples)


@cocotb.test()
async def test_models_differ(dut):
    """Every pair of models differs on this input (guards the model tests)."""
    samples, _ = keying(seed=7, elements=40, spikes=True)
    traces = {name: tuple(run_model(samples, name)) for name in MODELS}
    assert len(set(traces.values())) == len(MODELS)


# ----------------------------------------------------------- property tests

@cocotb.test(expect_fail=expect_fail(0))
async def test_bounce_gives_one_press_and_one_release(dut):
    """Three bouncy keyings give exactly six clean_pb edges."""
    await setup(dut)
    got = await drive(dut, bouncy_key() * 3)
    dut._log.info("clean_pb edges: %d (want 6) %s", edges(got),
                  "".join(map(str, got)))
    assert edges(got) == 6


@cocotb.test(expect_fail=expect_fail(1))
async def test_press_is_immediate(dut):
    """The first sample of a press after a quiet period reaches clean_pb."""
    await setup(dut)
    got = await drive(dut, bouncy_key())
    assert got[0] == 1


@cocotb.test(expect_fail=expect_fail(2))
async def test_realistic_keying_no_extra_edges(dut):
    """150 bouncy elements (0-6 ms bounce, no spikes): two edges each."""
    await setup(dut)
    samples, marks = keying(seed=1)
    m = keying_metrics(await drive(dut, samples), marks)
    dut._log.info("extra edges: %d", m["extra_edges"])
    assert m["extra_edges"] == 0


@cocotb.test(expect_fail=expect_fail(3))
async def test_spikes_rejected(dut):
    """The same keying plus isolated 1 ms spikes: still two edges each."""
    await setup(dut)
    samples, marks = keying(seed=1, spikes=True)
    m = keying_metrics(await drive(dut, samples), marks)
    dut._log.info("extra edges with spikes: %d", m["extra_edges"])
    assert m["extra_edges"] == 0


@cocotb.test(expect_fail=expect_fail(4))
async def test_width_not_shortened(dut):
    """150 bouncy elements: every press has the same delay and no element is
    shorter than keyed, so only the release bounce changes the width."""
    await setup(dut)
    samples, marks = keying(seed=1)
    m = keying_metrics(await drive(dut, samples), marks)
    assert m["extra_edges"] == 0
    dut._log.info("press delay %d..%d ms, width error %+d..%+d ms",
                  min(m["press"]), max(m["press"]), min(m["width"]),
                  max(m["width"]))
    assert min(m["press"]) == max(m["press"])
    assert min(m["width"]) >= 0


@cocotb.test()
async def test_keying_metrics(dut):
    """Log delay and width error on realistic keying (README table)."""
    await setup(dut)
    for spikes in (False, True):
        samples, marks = keying(seed=1, spikes=spikes)
        got = await drive(dut, samples)
        assert got == run_model(samples)
        m = keying_metrics(got, marks)
        if m["extra_edges"]:
            dut._log.info("METRICS %s spikes=%s extra_edges=%d", DUT, spikes,
                          m["extra_edges"])
            continue
        dut._log.info(
            "METRICS %s spikes=%s extra_edges=0 press=%d..%d ms (mean %.2f) "
            "release=%d..%d ms (mean %.2f) width_error=%+d..%+d ms",
            DUT, spikes, min(m["press"]), max(m["press"]),
            sum(m["press"]) / len(m["press"]), min(m["release"]),
            max(m["release"]), sum(m["release"]) / len(m["release"]),
            min(m["width"]), max(m["width"]))


# ---------------------------------------------------------------- scenarios

def _key(pre, body, post):
    return [0] * pre + body + [0] * post


def _dits(n=3, on=30, off=30, bounce=((1, 0, 1), (0, 1, 0, 0, 1))):
    out, keyed, t = [0] * 6, [], 6
    for _ in range(n):
        press, release = list(bounce[0]), list(bounce[1])
        out += press + [1] * (on - len(press)) + release + [0] * (off - len(release))
        keyed.append((t, t + on))
        t += on + off
    return out + [0] * 10, keyed


SCENARIOS = {
    # name: (pb samples, keyed intervals [start, end) in samples)
    "clean": (_key(5, [1] * 20, 17), [(5, 25)]),
    "press_bounce": (_key(5, [1, 0, 1, 1, 0, 0, 1] + [1] * 13, 17), [(5, 25)]),
    "release_bounce": (_key(5, [1] * 20 + [0, 1, 0, 0, 1], 12), [(5, 25)]),
    "spike": ([0] * 10 + [1] + [0] * 31, []),
    "dropout": (_key(5, [1] * 10 + [0] + [1] * 10, 16), [(5, 26)]),
    "dits_40wpm": _dits(),
}
TRACE_LABEL = (f"hold_d{HOLD_D}_c{HOLD_CONFIRM}" if DUT == "hold" else DUT)


@cocotb.test()
async def test_dump_scenarios(dut):
    """Drive each hand-made scenario through the RTL and write traces_<dut>.json
    (clean_pb after every pulse) for plot_traces.py. Checks the RTL against the
    model on each one; 14 idle samples between scenarios clear every design."""
    import json
    await setup(dut)
    out = {"dut": TRACE_LABEL, "scenarios": {}}
    for name, (samples, keyed) in SCENARIOS.items():
        await drive(dut, [0] * 14)
        got = await drive(dut, samples)
        assert got == run_model(samples), name
        out["scenarios"][name] = {"pb": samples, "clean": got, "keyed": keyed}
    with open(f"traces_{TRACE_LABEL}.json", "w") as f:
        json.dump(out, f)
    dut._log.info("wrote traces_%s.json", TRACE_LABEL)


@cocotb.test()
async def test_single_sample_glitch(dut):
    """A 1 ms spike from idle: log the clean_pb pulse it produces."""
    await setup(dut)
    samples = [1] + [0] * 12
    got = await drive(dut, samples)
    dut._log.info("METRICS %s 1 ms spike gives a %d ms pulse", DUT, sum(got))
    assert got == run_model(samples)
