"""Bit-exact model of cic_fir_shared: second CIC (N=4, R=5, 28 bits) and the /5 FIR.

x is the cic_s1 output sequence of one stream (one value per 4.8 MHz frame).
`cic_phase` is the frame index (mod 5) of the first decimation, `fir_phase` the
CIC-output index (mod 5) of the first FIR output; the bench finds both.
"""
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
M28 = (1 << 28) - 1


def load_coefs():
    with open(os.path.join(HERE, 'coefs.txt')) as fp:
        shift = int(fp.readline().split()[2])
        h = np.array([int(l) for l in fp if l.strip()], dtype=np.int64)
    return h, shift


def wrap(v, bits):
    v = np.asarray(v, dtype=np.int64) & ((1 << bits) - 1)
    return np.where(v >= 1 << (bits - 1), v - (1 << bits), v)


def cic2(x, cic_phase):
    """18-bit second-CIC outputs for frames cic_phase, cic_phase+5, ..."""
    x = np.asarray(x, dtype=np.int64)
    n = len(x)
    i1 = i2 = i3 = i4 = 0
    c = []
    for t in range(n):
        # every integrator adds the old value of the one before it
        i1, i2, i3, i4 = (i1 + x[t]) & M28, (i2 + i1) & M28, (i3 + i2) & M28, (i4 + i3) & M28
        if t % 5 == cic_phase:
            c.append(i4)
    v = np.array(c, dtype=np.int64)
    for _ in range(4):
        v = (v - np.concatenate(([0], v[:-1]))) & M28
    d = wrap(v, 28)
    return (d + 512) >> 10


def fir(z, fir_phase, h=None, shift=None):
    if h is None:
        h, shift = load_coefs()
    z = np.asarray(z, dtype=np.int64)
    full = np.convolve(z, h)[:len(z)]           # full[p] = sum_k h[k] z[p-k]
    acc = full[fir_phase::5]
    y = (acc + (1 << (shift - 1))) >> shift
    return np.clip(y, -(1 << 23), (1 << 23) - 1)


def chain(x, cic_phase, fir_phase):
    return fir(cic2(x, cic_phase), fir_phase)
