"""Production receive chain: mix2 -> cic -> varcic -> firX8R8 at 76.8 MHz."""

import os
import sys

import cocotb
import numpy as np
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from scipy.signal.windows import blackmanharris

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

import hlmodel  # noqa: E402
import rx_chain_model as model  # noqa: E402

FS = model.ADC_CLOCK_HZ
STIM_LEN = 65536
TONE_STEP_HZ = FS / STIM_LEN
# The FIR holds 122 outputs of history; earlier outputs depend on the previous test.
SETTLE_OUTPUTS = 140
SAMPLE_RATES = (48_000, 96_000, 192_000, 384_000)

# Default tuning for the second mixer (channels 2 and 3)
PHI2 = int(round(10_136_000 * 2**32 / FS))
PHI3 = int(round(18_100_000 * 2**32 / FS))

# Limits sit a few dB outside the values measured on a correctly aligned chain.
IMAGE_LIMIT_DBC = -100.0
SPUR_LIMIT_DBC = -90.0
PASSBAND_RIPPLE_DB = 0.5
ALIAS_LIMIT_DB = -80.0
LO_HARMONIC_LIMIT_DB = -80.0


def phase_word(freq_hz):
    return int(round(freq_hz * 2**32 / FS)) & 0xFFFFFFFF


def tone_bin(freq_hz):
    return int(round(freq_hz / TONE_STEP_HZ))


def tones(bins_and_amplitudes):
    """Coherent ADC stimulus, rounded to 12 bits."""
    n = np.arange(STIM_LEN)
    total = np.zeros(STIM_LEN)
    for tone, amplitude in bins_and_amplitudes:
        total += amplitude * np.cos(2 * np.pi * tone * n / STIM_LEN)
    return np.clip(np.round(total), -2048, 2047).astype(np.int64)


def noise(seed):
    return np.random.default_rng(seed).integers(-2048, 2048, STIM_LEN)


async def start(dut, stimulus, phi0, phi1, sample_rate, phi2=PHI2, phi3=PHI3):
    with open("stim.mem", "w") as f:
        f.writelines(f"{int(v) & 0xFFF:03x}\n" for v in stimulus)
    dut.rst.value = 1
    dut.load_stim.value = 0
    dut.phi0.value = phi0
    dut.phi1.value = phi1
    dut.phi2.value = phi2
    dut.phi3.value = phi3
    dut.rate.value = model.RATE_FOR_SPS[sample_rate]
    await Timer(1, "ns")
    dut.load_stim.value = 1
    for _ in range(40):
        await RisingEdge(dut.clk)
    dut.rst.value = 0


async def capture(dut, stimulus, phi0, phi1, sample_rate, outputs, phi2=PHI2, phi3=PHI3):
    """Return I and Q of all four channels for each output after reset."""
    await start(dut, stimulus, phi0, phi1, sample_rate, phi2, phi3)
    rows = np.zeros((outputs, 8), dtype=np.int64)
    clocks = np.zeros(outputs, dtype=np.int64)
    for k in range(outputs):
        await RisingEdge(dut.out_strobe)
        await FallingEdge(dut.clk)
        clocks[k] = int(dut.clk_count.value)
        rows[k] = (dut.ch0_i.value.to_signed(), dut.ch0_q.value.to_signed(),
                   dut.ch1_i.value.to_signed(), dut.ch1_q.value.to_signed(),
                   dut.ch2_i.value.to_signed(), dut.ch2_q.value.to_signed(),
                   dut.ch3_i.value.to_signed(), dut.ch3_q.value.to_signed())
    expected_period = FS // sample_rate
    periods = set(np.diff(clocks).tolist())
    assert periods == {expected_period}, (
        f"{sample_rate} sps: output spacing {periods}, expected {expected_period}")
    return rows


def assert_matches_model(rows, stimulus, phi, sample_rate, channel, label):
    expected_i, expected_q = model.receive(stimulus, phi, sample_rate, len(rows), channel)
    for name, column, expected in (("I", 2 * channel, expected_i),
                                   ("Q", 2 * channel + 1, expected_q)):
        got = rows[SETTLE_OUTPUTS:, column]
        want = expected[SETTLE_OUTPUTS:]
        bad = np.flatnonzero(got != want)
        assert bad.size == 0, (
            f"{label} ch{channel} {name}: {bad.size}/{got.size} outputs differ; first at "
            f"output {bad[0] + SETTLE_OUTPUTS}: got {got[bad[0]]}, expected {want[bad[0]]}")


def complex_channel(rows, channel):
    settled = rows[SETTLE_OUTPUTS:]
    return settled[:, 2 * channel] + 1j * settled[:, 2 * channel + 1]


def tone_level(samples, freq_hz, sample_rate):
    """Amplitude of a complex tone at a known frequency, using a low-leakage window."""
    window = blackmanharris(len(samples))
    n = np.arange(len(samples))
    rotated = samples * np.exp(-2j * np.pi * freq_hz * n / sample_rate)
    return abs(np.sum(window * rotated)) / np.sum(window)


def db(ratio):
    return 20 * np.log10(max(ratio, 1e-12))


def worst_spur_dbc(samples, freq_hz, sample_rate, guard_bins=8):
    window = blackmanharris(len(samples))
    spectrum = np.abs(np.fft.fft(window * samples))
    tone = int(round(freq_hz / sample_rate * len(samples))) % len(samples)
    distance = np.minimum((np.arange(len(samples)) - tone) % len(samples),
                          (tone - np.arange(len(samples))) % len(samples))
    return db(spectrum[distance > guard_bins].max() / spectrum[distance <= guard_bins].max())


@cocotb.test()
async def test_rom_images_match_text_sources(dut):
    """The model reads the .mif files, so pin them to their independent .txt copies."""
    pairs = [(os.path.join("nco", "sincos_coarse"), 36)]
    pairs += [(os.path.join("radio_openhpsdr1", "firrom", f"coefL4{name}"), 18)
              for name in ("AE", "BF", "CG", "DH")]
    for stem, width in pairs:
        _, words = model.parse_mif(os.path.join(model.RTL, stem + ".mif"))
        with open(os.path.join(model.RTL, stem + ".txt")) as f:
            text = [int(line.split("//")[0].strip(), 2) for line in f if line.split("//")[0].strip()]
        assert words == text, f"{stem}: .mif and .txt contents differ"
        assert len(words) == 256 and max(words) < (1 << width), f"{stem}: unexpected shape"


@cocotb.test()
async def test_sincos_model_agrees_with_register_model(dut):
    """The fast NCO model must agree with the existing register-level sincos model."""
    angles = np.random.default_rng(11).integers(0, 1 << 20, 3000)
    reference = hlmodel.Sincos(calctype=3)
    outputs = [reference.step(int(angle)) for angle in angles]
    latency = 5
    got_sin, got_cos = model.sincos(angles[:-latency + 1], model.load_coarse_rom())
    want = np.array(outputs[latency - 1:], dtype=np.int64)
    assert np.array_equal(got_sin, want[:, 0]), "sin differs from hlmodel.Sincos"
    assert np.array_equal(got_cos, want[:, 1]), "cos differs from hlmodel.Sincos"


@cocotb.test()
async def test_mixer_outputs_bit_exact(dut):
    """Both interleaved mixer channels must match the model on every ADC clock."""
    stimulus = noise(21)
    phi0, phi1 = 0x1A2B3C4D, 0x2E6F1357
    await start(dut, stimulus, phi0, phi1, 384_000)
    clocks = 4000
    observed = np.zeros((clocks, 5), dtype=np.int64)
    filled = 0
    while filled < clocks:
        await FallingEdge(dut.clk_2x)
        if int(dut.clk.value) == 0:
            observed[filled] = (int(dut.clk_count.value), dut.mix0_i.value.to_signed(),
                                dut.mix0_q.value.to_signed(), dut.mix1_i.value.to_signed(),
                                dut.mix1_q.value.to_signed())
            filled += 1
    observed = observed[200:]
    count = int(observed[-1, 0]) + 1
    for channel, phi in ((0, phi0), (1, phi1)):
        want_i, want_q = model.mixer_output(stimulus, phi, count, channel)
        index = observed[:, 0]
        for name, column, want in (("I", 1 + 2 * channel, want_i),
                                   ("Q", 2 + 2 * channel, want_q)):
            bad = np.count_nonzero(observed[:, column] != want[index])
            assert bad == 0, f"mixer ch{channel} {name}: {bad}/{len(index)} samples differ"


@cocotb.test()
async def test_receiver_bit_exact_at_every_rate(dut):
    """Noise through all four channels must match the model at every sample rate."""
    stimulus = noise(22)
    phi0, phi1 = phase_word(7_074_000), phase_word(14_074_000)
    for sample_rate in SAMPLE_RATES:
        outputs = SETTLE_OUTPUTS + 500
        rows = await capture(dut, stimulus, phi0, phi1, sample_rate, outputs)
        assert_matches_model(rows, stimulus, phi0, sample_rate, 0, f"{sample_rate} sps")
        assert_matches_model(rows, stimulus, phi1, sample_rate, 1, f"{sample_rate} sps")
        assert_matches_model(rows, stimulus, PHI2, sample_rate, 2, f"{sample_rate} sps")
        assert_matches_model(rows, stimulus, PHI3, sample_rate, 3, f"{sample_rate} sps")
        assert np.any(rows[SETTLE_OUTPUTS:] != 0), "receiver produced only zeros"
        dut._log.info(f"{sample_rate} sps: 500 outputs bit-exact on all four channels")


@cocotb.test()
async def test_channels_are_independent(dut):
    """Retuning channels 1 and 3 must not change one output bit of channels 0 and 2."""
    stimulus = noise(23)
    phi0 = phase_word(7_074_000)
    outputs = SETTLE_OUTPUTS + 300
    first = await capture(dut, stimulus, phi0, phase_word(3_573_000), 192_000, outputs)
    second = await capture(dut, stimulus, phi0, phase_word(21_074_000), 192_000, outputs,
                           phi3=phase_word(1_840_000))
    settled_first, settled_second = first[SETTLE_OUTPUTS:], second[SETTLE_OUTPUTS:]
    for held, retuned in ((0, 1), (2, 3)):
        columns = [2 * held, 2 * held + 1]
        changed = np.count_nonzero(settled_first[:, columns] != settled_second[:, columns])
        assert changed == 0, f"retuning channel {retuned} changed {changed} channel {held} words"
        columns = [2 * retuned, 2 * retuned + 1]
        moved = np.count_nonzero(settled_first[:, columns] != settled_second[:, columns])
        assert moved > 0, f"channel {retuned} did not respond to retuning"


@cocotb.test()
async def test_tone_frequency_image_and_spurs(dut):
    """A tone must land at the right offset, with no image and low spurs."""
    sample_rate = 48_000
    nco_hz = 7_100_000
    tone_hz = tone_bin(nco_hz + 5_000) * TONE_STEP_HZ
    offset_hz = nco_hz - tone_hz  # the mixer maps a tone above the NCO to negative frequency
    stimulus = tones([(tone_bin(tone_hz), 1400)])
    outputs = SETTLE_OUTPUTS + 2048
    rows = await capture(dut, stimulus, phase_word(nco_hz), phase_word(3_500_000),
                         sample_rate, outputs)
    samples = complex_channel(rows, 0)
    wanted = tone_level(samples, offset_hz, sample_rate)
    image = tone_level(samples, -offset_hz, sample_rate)
    image_dbc = db(image / wanted)
    spur_dbc = worst_spur_dbc(samples, offset_hz, sample_rate)
    dut._log.info(f"wanted amplitude {wanted:.0f} LSB, image {image_dbc:.1f} dBc, "
                  f"worst spur {spur_dbc:.1f} dBc")
    assert wanted > 1e5, f"tone missing at {offset_hz:.0f} Hz: amplitude {wanted:.0f}"
    assert image_dbc < IMAGE_LIMIT_DBC, f"image {image_dbc:.1f} dBc"
    assert spur_dbc < SPUR_LIMIT_DBC, f"worst spur {spur_dbc:.1f} dBc"


@cocotb.test()
async def test_lo_harmonic_rejection(dut):
    """Signals at odd multiples of the tuned frequency must not reach the output."""
    sample_rate = 48_000
    nco_hz = 7_100_000
    outputs = SETTLE_OUTPUTS + 1024

    async def peak(tone_hz):
        stimulus = tones([(tone_bin(tone_hz), 1400)])
        rows = await capture(dut, stimulus, phase_word(nco_hz), phase_word(3_500_000),
                             sample_rate, outputs)
        samples = complex_channel(rows, 0)
        return np.abs(np.fft.fft(blackmanharris(len(samples)) * samples)).max()

    reference = await peak(nco_hz + 5_000)
    assert reference > 1e5, f"reference tone missing: peak {reference:.0f}"
    levels = {}
    for harmonic in (3, 5):
        levels[harmonic] = db(await peak(harmonic * nco_hz + 5_000) / reference)
    dut._log.info("LO harmonic response: " + ", ".join(
        f"{harmonic}x {level:.1f} dB" for harmonic, level in levels.items()))
    worst = max(levels.values())
    assert worst < LO_HARMONIC_LIMIT_DB, f"LO harmonic response {worst:.1f} dB"


@cocotb.test()
async def test_passband_flatness_and_alias_rejection(dut):
    """In-band tones stay flat; tones that would alias into the band are rejected."""
    sample_rate = 48_000
    nco_hz = 7_100_000
    outputs = SETTLE_OUTPUTS + 1024
    amplitude = 250

    async def measure(offsets):
        """Return dB relative to a 1 kHz reference tone in the same capture."""
        bins = [tone_bin(nco_hz + offset) for offset in (1_000, *offsets)]
        rows = await capture(dut, tones([(b, amplitude) for b in bins]), phase_word(nco_hz),
                             phase_word(3_500_000), sample_rate, outputs)
        samples = complex_channel(rows, 0)
        actual = [b * TONE_STEP_HZ - nco_hz for b in bins]
        aliased = [((-f + sample_rate / 2) % sample_rate) - sample_rate / 2 for f in actual]
        reference = tone_level(samples, aliased[0], sample_rate)
        assert reference > 1e4, f"reference tone missing: amplitude {reference:.0f}"
        return {offset: db(tone_level(samples, f, sample_rate) / reference)
                for offset, f in zip(offsets, aliased[1:])}

    levels = await measure((-20_000, -12_000, -4_000, 4_000, 12_000, 20_000))
    ripple = max(max(levels.values()), 0.0) - min(min(levels.values()), 0.0)
    dut._log.info("passband dB re 1 kHz: " + ", ".join(
        f"{offset:+d} Hz {level:+.3f}" for offset, level in levels.items()))
    assert ripple < PASSBAND_RIPPLE_DB, f"passband ripple {ripple:.3f} dB"

    aliases = await measure((-40_000, -32_000, 32_000, 40_000, 56_000))
    dut._log.info("alias dB re 1 kHz: " + ", ".join(
        f"{offset:+d} Hz {level:.1f}" for offset, level in aliases.items()))
    worst = max(aliases.values())
    assert worst < ALIAS_LIMIT_DB, f"worst alias {worst:.1f} dB"
