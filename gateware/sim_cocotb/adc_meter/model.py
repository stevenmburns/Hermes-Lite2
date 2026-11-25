"""Stimulus and bit-exact model for rtl/adc_meter.v.

Run as a script, it writes stim.mem for WINDOW_LOG2 and WINDOWS (environment).
"""

import os

import numpy as np

WINDOW_LOG2 = int(os.environ.get("WINDOW_LOG2", "12"))
WINDOWS = int(os.environ.get("WINDOWS", "8"))
L = 1 << WINDOW_LOG2
FULL_POS, FULL_NEG = 0x7FF, -0x800


def stimulus():
    """Signed ADC samples, WINDOWS * L of them. Window k of the stimulus:

    0  random +-500: no clips
    1  zeros (peak 0)
    2  random +-1500 with clips at both polarities, including runs (peak 2048
       from 0x800)
    3  every sample at full scale, alternating: L clips (saturates at 65535
       when L > 65535)
    4  random +-1800 with 0x7ff clips only (peak 2047)
    5  zeros and a single 0x800 in mid-window
    6+ random amplitude, random sparse clips (0x7ff); window 6 ends in a run
       of them

    The bench's windows start a few samples after these (the input delay), so
    the last GUARD samples of each window are zero: they fall into the next
    bench window and would otherwise change its peak.
    """
    GUARD = 8
    rng = np.random.default_rng(20261125)
    x = np.zeros(WINDOWS * L, dtype=np.int64)
    for k in range(WINDOWS):
        w = slice(k * L, (k + 1) * L)
        if k == 0:
            v = rng.integers(-500, 501, L)
        elif k in (1, 5):
            v = np.zeros(L, dtype=np.int64)
            if k == 5:
                v[L // 3] = FULL_NEG
        elif k == 2:
            v = rng.integers(-1500, 1501, L)
            pos = rng.integers(GUARD, L - GUARD, 40)
            v[pos] = np.where(rng.integers(0, 2, len(pos)) == 1, FULL_POS, FULL_NEG)
            v[L // 2:L // 2 + 17] = FULL_NEG
        elif k == 3:
            v = np.where(np.arange(L) % 2 == 0, FULL_POS, FULL_NEG)
        elif k == 4:
            v = rng.integers(-1800, 1801, L)
            v[rng.integers(0, L - GUARD, 25)] = FULL_POS
        else:
            a = int(rng.integers(10, 2047))
            v = rng.integers(-a, a + 1, L)
            v[rng.integers(0, L - GUARD, int(rng.integers(0, 200)))] = FULL_POS
        v[L - GUARD:] = 0
        if k == 6:
            # 0x7ff in the last GUARD samples: how many fall in the next bench
            # window is the input delay, so the alignment search is unique.
            # (Window 7 already peaks at 2047.)
            v[L - GUARD:] = FULL_POS
        x[w] = v
    return x


def write_stim(path="stim.mem"):
    with open(path, "w") as fd:
        for v in stimulus():
            fd.write(f"{int(v) & 0xFFF:03x}\n")


def windows(x_at_clock, nwin):
    """x_at_clock[c]: the sample adc_meter's input register holds at clock c
    (clock 0 = its first clock). Returns the meter word latched at the end of
    each of the first nwin windows."""
    out = []
    for k in range(nwin):
        v = x_at_clock[k * L:(k + 1) * L]
        clips = int(np.count_nonzero((v == FULL_POS) | (v == FULL_NEG)))
        peak = int(np.max(np.abs(v)))
        out.append((min(clips, 0xFFFF) << 16) | ((k & 0xF) << 12) | peak)
    return out


if __name__ == "__main__":
    write_stim()
