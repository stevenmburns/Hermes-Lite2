"""cocotb tests for the hl2b5up_main TX interpolation chain.

One simulation from power-up feeds the chain a stimulus made of four segments
(full-scale noise, isolated impulses, a four-tone signal, then zeros), records
every FIR and CIC output, and every test checks that one capture.
"""

import os
import sys

import cocotb
import numpy as np
from cocotb.triggers import RisingEdge

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "rx_chain"))

import mif2mem  # noqa: E402
import tx_chain_model as model  # noqa: E402

RRRR = 200
GBITS = 31
CLOCKS_PER_INPUT = 8 * RRRR
COEF_MIF = os.path.join(HERE, "..", "..", "rtl", "radio_openhpsdr1", "firrom", "coefI8_1024.mif")

NOISE_LEN = 600
IMPULSE_GAP = 200
TONE_BINS = (37, -150, 301, -320)   # bins of 48 kHz / 1024: +1.7, -7.0, +14.1, -15.0 kHz
TONE_AMPLITUDE = 6000
TONE_SETTLE = 200                   # input samples before the analysis window
TONE_WINDOW = 1024                  # input samples in the analysis window
TONE_LEN = TONE_SETTLE + TONE_WINDOW + 200
TAIL_LEN = 140


def load_coef():
    _, words = mif2mem.parse_mif(COEF_MIF)
    return model.to_signed(words, 18)


def make_stimulus():
    rng = np.random.default_rng(20261119)
    noise_i = rng.integers(-32768, 32768, NOISE_LEN)
    noise_q = rng.integers(-32768, 32768, NOISE_LEN)

    imp_i = np.zeros(2 * IMPULSE_GAP, dtype=np.int64)
    imp_q = np.zeros(2 * IMPULSE_GAP, dtype=np.int64)
    imp_i[0], imp_q[0] = 32767, -32768
    imp_i[IMPULSE_GAP], imp_q[IMPULSE_GAP] = -32768, 32767

    n = np.arange(TONE_LEN)
    tone = sum(np.exp(2j * np.pi * b * n / TONE_WINDOW) for b in TONE_BINS) * TONE_AMPLITUDE
    tone_i = np.round(tone.real).astype(np.int64)
    tone_q = np.round(tone.imag).astype(np.int64)

    tail = np.zeros(TAIL_LEN, dtype=np.int64)
    stim_i = np.concatenate((noise_i, imp_i, tone_i, tail))
    stim_q = np.concatenate((noise_q, imp_q, tone_q, tail))
    tone_start = NOISE_LEN + 2 * IMPULSE_GAP
    return stim_i, stim_q, tone_start


class Capture:
    """Lazily runs the simulation once and holds the RTL and model outputs."""

    result = None

    @classmethod
    async def get(cls, dut):
        if cls.result is None:
            cls.result = await cls._run(dut)
        return cls.result

    @staticmethod
    async def _run(dut):
        stim_i, stim_q, tone_start = make_stimulus()
        nclk = len(stim_i) * CLOCKS_PER_INPUT
        with open("stim.mem", "w") as f:
            for i, q in zip(stim_i, stim_q):
                f.write(f"{(int(i) & 0xFFFF) << 16 | (int(q) & 0xFFFF):08x}\n")

        dut.nstim.value = len(stim_i)
        dut.nclk.value = nclk
        dut.run.value = 1
        await RisingEdge(dut.done)

        cic = np.fromfile("cic_out.bin", dtype="<u4")
        fir = np.fromfile("fir_out.bin", dtype="<i4")
        assert len(cic) == nclk, f"{len(cic)} CIC words recorded, expected {nclk}"
        rtl = {
            # Each record is the value before an edge, i.e. after the previous one.
            "cic_r": model.to_signed(cic[1:] >> 16, 16),
            "cic_i": model.to_signed(cic[1:] & 0xFFFF, 16),
            "fir_i": fir[0::2].astype(np.int64),
            "fir_q": fir[1::2].astype(np.int64),
        }
        u_i, u_q, cic_r, cic_i = model.chain(stim_i, stim_q, load_coef(), nclk, RRRR, GBITS)
        ref = {"cic_r": cic_r[:-1], "cic_i": cic_i[:-1], "fir_i": u_i, "fir_q": u_q}
        return rtl, ref, tone_start


def first_mismatch(name, got, want):
    assert len(got) == len(want), f"{name}: {len(got)} samples, model has {len(want)}"
    bad = np.flatnonzero(got != want)
    if len(bad):
        k = bad[0]
        lo = max(0, k - 2)
        return (f"{name}: {len(bad)} of {len(want)} samples differ, first at {k}: "
                f"rtl {got[lo:k + 3].tolist()} model {want[lo:k + 3].tolist()}")
    return None


def tone_spectrum(rtl, tone_start):
    """FFT of the CIC output over the steady-state tone window."""
    # Input sample s reaches the CIC output about 8 * (s + 3) CIC events later;
    # TONE_SETTLE covers that and the 129-tap FIR history with a wide margin.
    first = (tone_start + TONE_SETTLE) * CLOCKS_PER_INPUT
    length = TONE_WINDOW * CLOCKS_PER_INPUT
    z = rtl["cic_r"][first:first + length] + 1j * rtl["cic_i"][first:first + length]
    return np.abs(np.fft.fft(z)) / length, length


def db(x):
    return 20 * np.log10(np.maximum(x, 1e-300))


@cocotb.test()
async def test_fir_outputs_bit_exact(dut):
    """Every FIR output the CIC samples matches the model."""
    rtl, ref, _ = await Capture.get(dut)
    errors = [first_mismatch(k, rtl[k], ref[k]) for k in ("fir_i", "fir_q")]
    errors = [e for e in errors if e]
    assert not errors, "\n".join(errors)
    nonzero = np.count_nonzero(rtl["fir_i"])
    assert nonzero > 0.9 * len(rtl["fir_i"]) * 0.5, f"only {nonzero} nonzero FIR outputs"
    dut._log.info("%d FIR outputs per component match", len(rtl["fir_i"]))


@cocotb.test()
async def test_cic_outputs_bit_exact(dut):
    """Every CIC output, on every 76.8 MHz clock, matches the model."""
    rtl, ref, _ = await Capture.get(dut)
    errors = [first_mismatch(k, rtl[k], ref[k]) for k in ("cic_r", "cic_i")]
    errors = [e for e in errors if e]
    assert not errors, "\n".join(errors)
    peak = int(np.max(np.abs(rtl["cic_r"])))
    assert peak > 8000, f"CIC output peak {peak} is too small to exercise the datapath"
    dut._log.info("%d CIC outputs per component match, peak %d", len(rtl["cic_r"]), peak)


@cocotb.test()
async def test_tone_gain_and_flatness(dut):
    """Tone levels match the gain computed from the coefficients and CIC growth."""
    rtl, _, tone_start = await Capture.get(dut)
    spectrum, n = tone_spectrum(rtl, tone_start)
    coef = load_coef()
    # FIR: phase sum / 2^12 / 2; CIC: RRRR^5 / RRRR / 2^(CBITS - OBITS).
    fir_gain = np.mean([coef[p::8].sum() for p in range(8)]) / 2 ** 13
    cic_gain = RRRR ** 4 / 2 ** (20 + GBITS - 16)
    expected = TONE_AMPLITUDE * fir_gain * cic_gain
    levels = np.array([spectrum[b % n] for b in TONE_BINS])
    err_db = db(levels / expected)
    dut._log.info("tone levels vs %.1f expected: %s dB", expected,
                  ", ".join(f"{b * 48000 / 1024:+.0f} Hz {e:+.3f}" for b, e in zip(TONE_BINS, err_db)))
    assert np.all(np.abs(err_db) < 0.2), f"tone level error {err_db} dB"
    assert np.ptp(err_db) < 0.1, f"passband ripple {np.ptp(err_db):.3f} dB"


@cocotb.test()
async def test_images_and_spurs(dut):
    """Interpolation images and other spurs stay far below the tones."""
    rtl, _, tone_start = await Capture.get(dut)
    spectrum, n = tone_spectrum(rtl, tone_start)
    tone_bins = [b % n for b in TONE_BINS]
    ref = min(spectrum[b] for b in tone_bins)
    rest = spectrum.copy()
    rest[tone_bins] = 0
    bins_per_384k = 8 * TONE_WINDOW

    freq_bin = (np.arange(n) + n // 2) % n - n // 2      # signed bin index

    def worst(selection):
        k = int(np.argmax(np.where(selection, rest, 0)))
        return db(rest[k] / ref), freq_bin[k] * 76.8e6 / n

    # Images of the 48 ksps input inside the FIR's 384 kHz output band, then
    # images of the 384 ksps FIR output that the CIC must suppress.
    fir_band = np.abs(freq_bin) < bins_per_384k // 2
    cic_band = ~fir_band & (np.abs(freq_bin) < 4 * bins_per_384k)
    fir_images, fir_f = worst(fir_band)
    cic_images, cic_f = worst(cic_band)
    anywhere, any_f = worst(np.ones(n, dtype=bool))
    dut._log.info("worst spur, |f| < 192 kHz: %.1f dBc at %+.0f Hz", fir_images, fir_f)
    dut._log.info("worst spur, 192 kHz to 1.536 MHz: %.1f dBc at %+.0f Hz", cic_images, cic_f)
    dut._log.info("worst spur anywhere: %.1f dBc at %+.0f Hz", anywhere, any_f)
    # Limits sit about 10 dB (FIR) and 15 dB (CIC) above the measured values:
    # -82.2 dBc at -33.9 kHz and -115.2 dBc at +193.7 kHz.
    assert fir_images < -72, f"FIR image {fir_images:.1f} dBc at {fir_f:+.0f} Hz"
    assert cic_images < -100, f"CIC image {cic_images:.1f} dBc at {cic_f:+.0f} Hz"
    assert anywhere < -72, f"spur {anywhere:.1f} dBc at {any_f:+.0f} Hz"
