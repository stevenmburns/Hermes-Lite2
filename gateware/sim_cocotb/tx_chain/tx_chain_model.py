"""Bit-exact model of the hl2b5up_main TX interpolation chain.

    FirInterp8_1024 (x8, 48 -> 384 ksps) -> CicInterpM5 (x200, -> 76.8 MHz)

Both models start from the power-up state (all registers and RAM zero) and are
indexed by clock edge, so the testbench must record from the first clock edge.

FIR timing, as wired in radio.v:

* The FIR computes one output each time the CIC strobes ``calc`` (once every
  RRRR clocks) and writes a new input sample after every eighth output.
* Write n stores the value the testbench was presenting at that moment.  The
  testbench presents 0 before the first request and ``stim[n - 1]`` after the
  n-th request, so the written sequence is ``w = [0, stim[0], stim[1], ...]``.
* Output m uses phase p = m % 8 and the newest written sample n = m // 8 - 1,
  and sums NTAPS / 8 = 128 products: sample n - j with coefficient p + 8 j.
"""

import numpy as np

FIR_MACS = 128
FIR_PHASES = 8


def to_signed(value, bits):
    value = np.asarray(value, dtype=np.int64) & ((1 << bits) - 1)
    return np.where(value >> (bits - 1), value - (1 << bits), value)


def fir_outputs(stim_i, stim_q, coef, count):
    """Return the first ``count`` FIR outputs (y_real, y_imag) as int64 arrays."""
    coef = np.asarray(coef, dtype=np.int64)
    out = []
    for stim in (stim_i, stim_q):
        w = np.concatenate(([0], np.asarray(stim, dtype=np.int64)))
        newest = np.arange(count) // FIR_PHASES - 1
        phase = np.arange(count) % FIR_PHASES
        acc = np.zeros(count, dtype=np.int64)
        for j in range(FIR_MACS):
            k = newest - j
            valid = (k >= 0) & (k < len(w))
            sample = np.where(valid, w[np.clip(k, 0, len(w) - 1)], 0)
            # Samples are 16 bits sign-extended to 18; the product is 36 bits.
            product = sample * coef[phase + 8 * j]
            acc += (product >> 12) + ((product >> 11) & 1)
        acc &= (1 << 24) - 1
        half = acc >> 1
        out.append(to_signed((half & 0xFFFFF) + (half & 1), 20))
    return out[0], out[1]


def cic_outputs(u, rrrr, ibits, gbits, obits, nclk):
    """Return the CIC output after each of the first ``nclk`` clock edges.

    ``u[k]`` is the input sampled at comb event k (clock edge k * rrrr + rrrr - 1).
    """
    cbits = ibits + gbits
    mask = (1 << cbits) - 1
    nevents = nclk // rrrr
    u = [int(v) for v in u[:nevents]]

    # Pipelined comb, one update per event, all stages using old values.
    x = [0] * 6
    dx = [0] * 5
    comb = np.zeros(nevents, dtype=np.uint64)
    for k in range(nevents):
        new_x = [u[k] & mask] + [(x[s] - dx[s]) & mask for s in range(5)]
        dx = x[:5]
        x = new_x
        comb[k] = x[5]

    # x5 holds the comb result for the one clock after each event, else 0.
    x5 = np.zeros(nclk, dtype=np.uint64)
    x5[rrrr - 1 :: rrrr][:nevents] = comb

    # Each integrator adds the previous stage's value from before the edge.
    stage = x5
    for _ in range(5):
        stage = np.concatenate(([np.uint64(0)], np.cumsum(stage, dtype=np.uint64)[:-1]))
    y5 = stage & np.uint64(mask)

    top = (y5 >> np.uint64(cbits - obits)) & np.uint64((1 << obits) - 1)
    rnd = (y5 >> np.uint64(cbits - obits - 1)) & np.uint64(1)
    return to_signed((top + rnd).astype(np.int64), obits)


def chain(stim_i, stim_q, coef, nclk, rrrr=200, gbits=31):
    """Model the whole chain for ``nclk`` clocks.

    Returns (fir_i, fir_q, cic_r, cic_i).  fir_* are the CIC inputs at each comb
    event, cic_* the CIC outputs after each clock edge.
    """
    nevents = nclk // rrrr
    fi, fq = fir_outputs(stim_i, stim_q, coef, nevents - 1)
    u_i = np.concatenate(([0], fi))
    u_q = np.concatenate(([0], fq))
    cic_r = cic_outputs(u_i, rrrr, 20, gbits, 16, nclk)
    cic_i = cic_outputs(u_q, rrrr, 20, gbits, 16, nclk)
    return u_i, u_q, cic_r, cic_i
