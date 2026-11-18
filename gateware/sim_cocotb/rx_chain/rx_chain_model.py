"""Bit-exact numpy model of the hl2b5up_main receive chain.

The model follows the arithmetic of the production RTL at 76.8 MHz:

    mix2/nco2/sincos -> cic (R=5) -> varcic (R=5/10/20/40) -> firX8R8 (R=8)

It is written from the datapath, stage by stage, rather than by replaying
registers, so that it runs fast enough for millions of ADC clocks.
"""

import functools
import os
import sys

import numpy as np

HERE = os.path.abspath(os.path.dirname(__file__))
RTL = os.path.abspath(os.path.join(HERE, os.pardir, os.pardir, "rtl"))
sys.path.insert(0, HERE)

from mif2mem import parse_mif  # noqa: E402

ADC_CLOCK_HZ = 76_800_000
CIC_DECIMATION = 5
FIR_DECIMATION = 8
FIR_TAPS_PER_BANK = 122
RATE_FOR_SPS = {48_000: 40, 96_000: 20, 192_000: 10, 384_000: 5}

CIC_STAGES = 3
CIC_ACC_WIDTH = 25
CIC_OUT_WIDTH = 16
VARCIC_STAGES = 5
VARCIC_IN_WIDTH = 16
VARCIC_OUT_WIDTH = 16
VARCIC_GROWTH = {5: 12, 10: 17, 20: 22, 40: 27}

# Register delays, in ADC clocks, from clk_count to the (ADC sample, NCO phase)
# that reach each mixer output in tb_rx_chain.sv.
MIXER_DELAYS = {0: (2, 3), 1: (3, 4), 2: (2, 3), 3: (3, 4)}


def signed(values, width):
    """Interpret the low `width` bits of each value as two's complement."""
    mask = (np.int64(1) << width) - 1
    sign = np.int64(1) << (width - 1)
    return ((np.asarray(values, dtype=np.int64) & mask) ^ sign) - sign


@functools.lru_cache(maxsize=1)
def load_coarse_rom():
    _, words = parse_mif(os.path.join(RTL, "nco", "sincos_coarse.mif"))
    return np.array(words, dtype=np.int64)


@functools.lru_cache(maxsize=1)
def load_fir_banks():
    """Return the eight coefficient banks in firX8R8 write order A..H.

    Each fir256 ROM holds two banks selected by the top address bit: banksel=1
    (the first four writes of a group) and banksel=0 (the last four).
    """
    roms = []
    for name in ("AE", "BF", "CG", "DH"):
        _, words = parse_mif(os.path.join(
            RTL, "radio_openhpsdr1", "firrom", f"coefL4{name}.mif"))
        roms.append(signed(np.array(words, dtype=np.int64), 18))
    first = [rom[128:128 + FIR_TAPS_PER_BANK] for rom in roms]
    second = [rom[:FIR_TAPS_PER_BANK] for rom in roms]
    return np.array(first + second, dtype=np.int64)


def sincos(angle, coarse_rom):
    """rtl/nco/sincos.v with CALCTYPE=3: 19-bit sign-magnitude (sin, cos)."""
    angle = np.asarray(angle, dtype=np.int64)
    quadrant = (angle >> 18) & 3
    coarse = (angle >> 10) & 0xFF
    fine = angle & 0x3FF

    addr = np.where(quadrant & 1, ~coarse & 0xFF, coarse)
    sin_sign = (quadrant >> 1) & 1
    cos_sign = sin_sign ^ (quadrant & 1)

    fine_high = (fine >> 9) & 1
    fine_addr = np.where(fine_high, fine & 0x1FF, ~fine & 0x1FF)
    fine_sign = 1 - fine_high

    word = coarse_rom[addr]
    coarse_sin = (word >> 18) & 0x3FFFF
    coarse_cos = word & 0x3FFFF

    fine_sin = (0x65 * (((fine_addr >> 3) << 1) | 1)) & 0x3FFF
    opb = fine_sin >> 7
    scsf = ((coarse_sin * opb) >> 15) & 0x3FF
    ccsf = ((coarse_cos * opb) >> 15) & 0x3FF

    # sop and cop are the XOR of the three sign inputs (cop inverted)
    sop = sin_sign ^ cos_sign ^ fine_sign
    cop = 1 - sop
    sin_mag = (coarse_sin + np.where(sop, -ccsf, ccsf)) & 0x3FFFF
    cos_mag = (coarse_cos + np.where(cop, -scsf, scsf)) & 0x3FFFF
    return (sin_sign << 18) | sin_mag, (cos_sign << 18) | cos_mag


def _signed_multiplier_input(value):
    """mix2.v conversion of 19-bit sign magnitude to an 18-bit signed operand."""
    negative = (value >> 18) & 1
    magnitude = value & 0x3FFFF
    negated = (((1 << 19) - magnitude) & 0x7FFFF) >> 1
    return signed(np.where(negative, negated, magnitude >> 1), 18)


def mix(adc, angle, coarse_rom):
    """rtl/nco/mix2.v for one channel: return 18-bit signed (I, Q)."""
    sin, cos = sincos(angle, coarse_rom)
    adc = np.asarray(adc, dtype=np.int64)

    def product(operand):
        full = adc * _signed_multiplier_input(operand)
        return signed(((full >> 11) & 0x3FFFF) + ((full >> 10) & 1), 18)

    return product(cos), product(sin)


def nco_angles(phi, count, start=0):
    """20-bit sincos angle for `count` ADC clocks of a 32-bit phase increment."""
    index = np.arange(start, start + count, dtype=np.int64).astype(np.uint64)
    phase = (index * np.uint64(phi)) & np.uint64(0xFFFFFFFF)
    return (phase >> np.uint64(12)).astype(np.int64)


def _wrap(values, width):
    return values & ((np.int64(1) << width) - 1)


def _delayed_difference(values, stages, width):
    """Comb chain in which every stage adds one output-sample register delay."""
    out = np.asarray(values, dtype=np.int64)
    for stage in range(stages):
        previous = np.concatenate(([0], out[:-1]))
        diff = _wrap(out - previous, width)
        if stage < stages - 1:
            diff = np.concatenate(([0], diff[:-1]))
        out = diff
    return out


def _integrate(values, stages, width):
    """Integrator chain in which each stage registers its input by one sample."""
    out = np.asarray(values, dtype=np.int64)
    for _ in range(stages):
        out = _wrap(np.concatenate(([0], np.cumsum(out)[:-1])), width)
    return out


def cic(samples):
    """rtl/radio_openhpsdr1/cic.v with DECIMATION=5."""
    integrated = _integrate(samples, CIC_STAGES, CIC_ACC_WIDTH)
    picked = integrated[CIC_DECIMATION:: CIC_DECIMATION]
    combed = signed(_delayed_difference(picked, CIC_STAGES, CIC_ACC_WIDTH),
                    CIC_ACC_WIDTH)
    shift = CIC_ACC_WIDTH - CIC_OUT_WIDTH
    return signed((combed >> shift) + ((combed >> (shift - 1)) & 1),
                  CIC_OUT_WIDTH)


def varcic(samples, decimation):
    """rtl/radio_openhpsdr1/varcic.v, including its output register."""
    acc_width = VARCIC_IN_WIDTH + VARCIC_GROWTH[40]
    delayed = np.concatenate(([0], samples[:-1]))
    integrated = _integrate(delayed, VARCIC_STAGES, acc_width)
    picked = integrated[decimation:: decimation]
    combed = signed(_delayed_difference(picked, VARCIC_STAGES, acc_width),
                    acc_width)
    lsb = VARCIC_IN_WIDTH + VARCIC_GROWTH[decimation] - VARCIC_OUT_WIDTH
    rounded = signed((combed >> lsb) + ((combed >> (lsb - 1)) & 1),
                     VARCIC_OUT_WIDTH)
    return np.concatenate(([0], rounded[:-1]))


def fir(samples, banks):
    """rtl/radio_openhpsdr1/firfilt.v firX8R8: decimate by 8 over eight banks."""
    groups = len(samples) // FIR_DECIMATION
    data = np.asarray(samples[:groups * FIR_DECIMATION], dtype=np.int64)
    data = data.reshape(groups, FIR_DECIMATION)

    accumulators = np.zeros((groups, FIR_DECIMATION), dtype=np.int64)
    for bank in range(FIR_DECIMATION):
        history = np.concatenate((np.zeros(FIR_TAPS_PER_BANK - 1, dtype=np.int64),
                                  data[:, bank]))
        windows = np.lib.stride_tricks.sliding_window_view(
            history, FIR_TAPS_PER_BANK)[:, ::-1]
        products = windows * banks[bank]
        terms = (products >> 12) + ((products >> 11) & 1)
        accumulators[:, bank] = signed(terms.sum(axis=1), 24)

    # Each output adds banks E..H of the previous group to banks A..D of this one
    previous = np.vstack((np.zeros((1, 4), dtype=np.int64),
                          accumulators[:-1, 4:]))
    return signed(previous.sum(axis=1) + accumulators[:, :4].sum(axis=1), 24)


def receive(stimulus, phi, sample_rate, outputs, channel):
    """Return `outputs` 24-bit signed (I, Q) samples for one receiver channel.

    `stimulus` is the 65536-sample ADC sequence that tb_rx_chain.sv replays.
    Sample 0 of the result is the first output strobe after reset.
    """
    decimation = RATE_FOR_SPS[sample_rate]
    period = CIC_DECIMATION * decimation * FIR_DECIMATION
    clocks = period * (outputs + 2)
    mix_i, mix_q = mixer_output(stimulus, phi, clocks, channel)

    def filtered(values):
        return fir(varcic(cic(values), decimation), load_fir_banks())[:outputs]

    return filtered(mix_i), filtered(mix_q)


def mixer_output(stimulus, phi, clocks, channel):
    """Mixer samples seen by receiver `channel` at clk_count 0..clocks-1."""
    adc_delay, nco_delay = MIXER_DELAYS[channel]
    index = np.arange(clocks, dtype=np.int64)
    adc = np.asarray(stimulus, dtype=np.int64)[(index - adc_delay) % len(stimulus)]
    return mix(adc, nco_angles(phi, clocks, -nco_delay), load_coarse_rom())
