"""cocotb tests for the production radio.v with many receivers.

tb_many_rx.sv instantiates radio.v with NR receivers, so the mixer-pair
mapping, the frequency-register decode, the per-channel arrays and the
upstream multiplexer are the production code. CHAIN picks the receiver:
"full" (cic, varcic_mem, firX8R8), "cic" (receiver_ciconly.v, the
hl2b5up_cicrx chain, fixed 192 ksps), "cicshared" (the same with one shared
second CIC) or "cicfir" (cic_fir_shared: second CIC to 960 kHz and a /5 FIR).

The tests rely on retuning instead of a bit-exact model. The chain arithmetic
is already checked bit-exactly by rx_chain (CALCTYPE 3) and the sincos bench
(CALCTYPE 0 and 3); what is new here is the many-channel wiring.
"""

import os

import numpy as np

import cocotb
from cocotb.clock import Clock  # noqa: F401  (clocks come from the tb)
from cocotb.triggers import ClockCycles, Timer

NR = int(os.environ.get("NR", "12"))
CHAIN = os.environ.get("CHAIN", "full")
TX = bool(os.environ.get("TX"))

FS = 76_800_000
OUT_RATE = 192_000                 # rx_rate 2 for "full"; fixed for "cic"
OUT_PERIOD = FS // OUT_RATE        # 400 clocks
STIM_LEN = 65536
STIM_BIN = FS / STIM_LEN           # tones on this grid loop seamlessly

M2 = (2 ** 57 + FS // 2) // FS
M3 = 2 ** 24
RXFREQ_ADDR = [0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
               0x12, 0x13, 0x14, 0x15, 0x16]
CMDA_GENERAL = 0x00
RX_RATE_192K = 2

SETTLE_OUTPUTS = 64
CAPTURES = 0       # captures run so far in this simulation


def phase_increment(freq_hz):
    """radio.v: freqcomp = freq * M2 + M3, phase = freqcomp[56:25]."""
    return ((freq_hz * M2 + M3) >> 25) & 0xFFFFFFFF


def nco_freq(freq_hz):
    return phase_increment(freq_hz) * FS / 2 ** 32


def tone_freq(target_hz):
    return round(target_hz / STIM_BIN) * STIM_BIN


def slot_of(channel):
    """Which mix2 time slot (0 or 1) radio.v gives a channel."""
    if channel < 4:
        return 0 if channel < 2 else 1
    return channel & 1


def write_stim(tones):
    """tones: list of (freq_hz, amplitude). Writes stim.mem, 12-bit."""
    n = np.arange(STIM_LEN)
    x = np.zeros(STIM_LEN)
    for f, a in tones:
        x += a * np.cos(2 * np.pi * (f / FS) * n + 0.37 * f / 1e6)
    x = np.clip(np.round(x), -2048, 2047).astype(np.int64)
    with open("stim.mem", "w") as fd:
        for v in x:
            fd.write(f"{v & 0xFFF:03x}\n")


async def command(dut, addr, data):
    dut.cmd_addr.value = addr
    dut.cmd_data.value = data
    dut.cmd_rqst.value = 1
    await ClockCycles(dut.clk, 1)
    dut.cmd_rqst.value = 0
    await ClockCycles(dut.clk, 6)


COMMAND_CLOCKS = 7  # clocks per command() call


async def run_capture(dut, tunings, outputs, compare=True, pad_to=None):
    """Reset, tune channel c to tunings[c] Hz, capture `outputs` frames.

    Returns (frames, meta): frames[k] is an (NR, 2) array of signed (I, Q) for
    output frame k, after SETTLE_OUTPUTS frames are dropped; meta holds the
    raw per-word timing for the stream-format checks. compare=False skips
    the CHAIN=cic / cicshared capture comparison. pad_to=n waits as long as
    n frequency commands would take, so reset is released on the same clock
    whatever NR is (the ADC replay runs throughout).
    """
    dut.rst.value = 1
    dut.capture.value = 0
    dut.tx_run.value = 0
    dut.tx_capture.value = 0
    dut.cmd_rqst.value = 0
    dut.cmd_addr.value = 0
    dut.cmd_data.value = 0
    dut.load_stim.value = 0
    await Timer(1, unit="ns")
    dut.load_stim.value = 1
    await ClockCycles(dut.clk, 20)
    # Tune while reset is held: the command decoder is not reset, and every
    # NCO phase accumulator then starts from zero on the same clock.
    general = (RX_RATE_192K << 24) | ((NR - 1) << 3)
    await command(dut, CMDA_GENERAL, general)
    for c, f in enumerate(tunings):
        await command(dut, RXFREQ_ADDR[c], int(f))
    if pad_to is not None and pad_to > len(tunings):
        await ClockCycles(dut.clk, COMMAND_CLOCKS * (pad_to - len(tunings)))
    dut.rst.value = 0
    # Let every stage fill before recording.
    await ClockCycles(dut.clk, OUT_PERIOD * 32)
    dut.capture.value = 1
    await ClockCycles(dut.clk, 2)    # let the tb reset its word count
    want_words = 2 * NR * (outputs + SETTLE_OUTPUTS)
    while int(dut.words.value) < want_words:
        await ClockCycles(dut.clk, OUT_PERIOD * 64)
    dut.capture.value = 0
    await ClockCycles(dut.clk, 2)

    global CAPTURES
    CAPTURES += 1
    raw = np.fromfile("rx_stream.bin", dtype="<u4").reshape(-1, 2)
    data = raw[:, 0].astype(np.int64)
    data = ((data & 0xFFFFFF) ^ 0x800000) - 0x800000
    last = (raw[:, 1] >> 1) & 1
    clock = raw[:, 1] >> 2
    # Start at the first word after a tlast, so frames are aligned.
    first = int(np.argmax(last)) + 1
    data, last, clock = data[first:], last[first:], clock[first:]
    nframes = len(data) // (2 * NR)
    data, last, clock = (a[:nframes * 2 * NR] for a in (data, last, clock))
    frames = data.reshape(nframes, NR, 2)
    meta = {"last": last.reshape(nframes, 2 * NR),
            "clock": clock.reshape(nframes, 2 * NR)}
    frames = frames[SETTLE_OUTPUTS:]
    if compare:
        compare_with_cic(dut, frames)
    return frames, meta


COMPARED = []      # (capture, frame shift) for each CHAIN=cicshared comparison


def compare_with_cic(dut, frames):
    """Save this capture; for cicshared, require it to equal the cic run's.

    The shared CIC's output strobe comes later in the output period, so the
    first whole frame captured may be one output apart; the comparison tries
    shifts of up to two frames and needs an exact match at one of them.
    """
    name = f"frames_nr{NR}_capture{CAPTURES}"
    if CHAIN == "cic":
        np.save(f"{name}_cic.npy", frames)
        return
    if CHAIN != "cicshared":
        return
    ref_path = f"{name}_cic.npy"
    if not os.path.exists(ref_path):
        dut._log.warning("no %s: run CHAIN=cic first", ref_path)
        return
    ref = np.load(ref_path)
    n = min(len(ref), len(frames)) - 4
    for shift in (0, 1, -1, 2, -2):
        a = ref[2 + shift:2 + shift + n]
        b = frames[2:2 + n]
        if np.array_equal(a, b):
            COMPARED.append((CAPTURES, shift))
            dut._log.info("capture %d: %d frames x %d channels bit-identical "
                          "to CHAIN=cic (frame shift %+d)", CAPTURES, n, NR,
                          shift)
            return
    raise AssertionError(f"capture {CAPTURES} differs from CHAIN=cic")


# --------------------------------------------------------------- analysis

WINDOW_HALF = 24   # bins either side of a peak, for the Kaiser main lobe


def spectrum(iq):
    x = iq[:, 0] + 1j * iq[:, 1]
    w = np.kaiser(len(x), 20.0)
    s = np.fft.fftshift(np.fft.fft(x * w))
    p = np.abs(s) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / OUT_RATE))
    return f, p


def tone_power(f, p, freq):
    k = int(np.argmin(np.abs(f - freq)))
    lo, hi = max(0, k - WINDOW_HALF), min(len(p), k + WINDOW_HALF + 1)
    return float(np.sum(p[lo:hi])), k


def alias(freq):
    return (freq + OUT_RATE / 2) % OUT_RATE - OUT_RATE / 2


def out_freq(tone, tuning):
    """Output frequency of a tone: the mixer maps tone > NCO to negative."""
    return alias(nco_freq(tuning) - tone)


def db(x):
    return 10 * np.log10(x)


def _fir_coefs():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cic_fir", "coefs.txt")
    with open(path) as fp:
        fp.readline()
        return np.array([int(l) for l in fp if l.strip()], dtype=float)


FIR_H = _fir_coefs() if CHAIN == "cicfir" else None


def cic_response_db(offset):
    """Analytic gain of receiver_ciconly.v: CIC N=4 R=16, then N=4 R=25.
    For CHAIN=cicfir: CIC N=4 R=16, CIC N=4 R=5, then the /5 FIR at 960 kHz."""
    def stage(f, rate_in, r, n):
        x = np.pi * f / rate_in
        if abs(np.sin(x)) < 1e-15:
            return 1.0
        return abs(np.sin(r * x) / (r * np.sin(x))) ** n
    if CHAIN == "cicfir":
        k = np.arange(len(FIR_H))
        fir = abs(np.exp(-2j * np.pi * offset / 960e3 * k) @ FIR_H) / FIR_H.sum()
        h = stage(offset, FS, 16, 4) * stage(offset, FS / 16, 5, 4) * fir
    else:
        h = stage(offset, FS, 16, 4) * stage(offset, FS / 16, 25, 4)
    return 20 * np.log10(h)


# ------------------------------------------------------------------ tests

TUNE_BASE = 1_000_000
TUNE_STEP = 2_300_000      # channel c listens near 1 + 2.3 c MHz


@cocotb.test()
async def test_same_tuning_slot_classes_identical(dut):
    """All channels on one frequency: channels in the same mix2 slot match.

    radio.v puts each channel in time slot 0 or 1 of a shared mix2. Channels
    in the same slot see identical samples and phases, so their outputs must
    be bit-identical; the two slots differ by one ADC clock of delay, so
    across slots only the level must agree.

    It must be the first capture after power-up. radio.v never resets the
    receivers' filter state, and the pruned CICs do not cancel arbitrary
    leftover state exactly, so channels with different histories need not
    match bit for bit afterwards. It is therefore defined first, and checks.
    """
    assert CAPTURES == 0, "run this test first, from power-up state"
    tune = 7_100_000
    tone = tone_freq(tune + 6_000)
    write_stim([(tone, 1500.0)])
    frames, _ = await run_capture(dut, [tune] * NR, outputs=1024)
    classes = {}
    for c in range(NR):
        classes.setdefault(slot_of(c), []).append(c)
    for slot, chans in classes.items():
        ref = frames[:, chans[0], :]
        for c in chans[1:]:
            diff = int(np.sum(frames[:, c, :] != ref))
            assert diff == 0, f"channel {c} differs from channel {chans[0]}"
        dut._log.info("slot %d channels %s: bit-identical", slot, chans)
    powers = [float(np.sum(frames[:, c, :].astype(float) ** 2))
              for c in range(NR)]
    spread = db(max(powers) / min(powers))
    dut._log.info("power spread across slots: %.4f dB", spread)
    assert spread < 0.01


@cocotb.test()
async def test_stream_format_and_mapping(dut):
    """One tone per channel: each appears only in its own channel.

    Channel c is tuned near 1 + 2.3c MHz and its tone sits at a different
    in-band offset. Wrong frequency-register decode or pair wiring puts a
    tone in the wrong channel or loses it. The upstream stream must carry
    2 * NR words per output, tlast on the last, one output per 400 clocks.
    """
    offsets = [-15_000 + 2_700 * c for c in range(NR)]
    tunings = [TUNE_BASE + TUNE_STEP * c for c in range(NR)]
    tones = [tone_freq(t + o) for t, o in zip(tunings, offsets)]
    write_stim([(f, 0.9 * 2047 / NR) for f in tones])
    frames, meta = await run_capture(dut, tunings, outputs=2048)

    last = meta["last"]
    assert np.all(last[:, -1] == 1), "tlast missing on the last word"
    assert not np.any(last[:, :-1]), "tlast before the last word"
    starts = meta["clock"][:, 0]
    periods = np.unique(np.diff(starts))
    dut._log.info("NR=%d %s: %d frames, frame periods %s clocks, words per "
                  "frame %d", NR, CHAIN, len(frames), periods.tolist(),
                  last.shape[1])
    assert periods.tolist() == [OUT_PERIOD]
    burst = meta["clock"][:, -1] - meta["clock"][:, 0]
    assert np.all(burst < OUT_PERIOD), "frame longer than the output period"

    levels, leaks = [], []
    for c in range(NR):
        f, p = spectrum(frames[:, c, :])
        expected = out_freq(tones[c], tunings[c])
        power, k = tone_power(f, p, expected)
        peak = int(np.argmax(p))
        # Remove the CIC-only chain's known droop (the full chain is flat here).
        droop = cic_response_db(expected) if CHAIN.startswith("cic") else 0.0
        levels.append(db(power) - droop)
        dut._log.info("ch%-2d tuned %.3f MHz: tone at %+.0f Hz, peak at %+.0f Hz",
                      c, tunings[c] / 1e6, expected, f[peak])
        assert abs(peak - k) <= 2, f"channel {c}: tone not where it should be"
        # The strongest thing outside this channel's own tone, relative to it.
        q = p.copy()
        q[max(0, k - WINDOW_HALF):k + WINDOW_HALF + 1] = 0
        rest = int(np.argmax(q))
        leak = db(tone_power(f, q, f[rest])[0]) - levels[-1]
        leaks.append(leak)
        dut._log.info("ch%-2d strongest other component %.1f dB at %+.0f Hz",
                      c, leak, f[rest])
    spread = max(levels) - min(levels)
    dut._log.info("tone level spread across channels (droop removed): %.3f dB; worst other "
                  "component %.1f dB", spread, max(leaks))
    assert spread < 0.3
    assert max(leaks) < -80, "another channel's tone (or a spur) leaks in"


RESPONSE_OFFSETS = [5_000, 20_000, 40_000, 60_000, 75_000, 85_000, 95_000,
                    110_000, 125_000, 150_000, 175_000, 250_000]


@cocotb.test()
async def test_frequency_response(dut):
    """One ADC tone; channel c tuned so the tone sits at offset c.

    Measures the receiver's response at NR offsets in one run, including
    offsets past the output Nyquist frequency, which alias. Levels are
    relative to the 5 kHz channel. For the CIC-only chains they must match
    the analytic response (for cicfir, CICs and FIR, and offsets from 125 kHz,
    which alias onto the band, must also be 80 dB down); for CHAIN=full, the
    passband must be flat and the aliases far down.
    """
    offsets = RESPONSE_OFFSETS[:NR]
    tone = tone_freq(14_070_000)
    write_stim([(tone, 1800.0)])
    tunings = [round(tone - o) for o in offsets]
    frames, _ = await run_capture(dut, tunings, outputs=4096)
    measured = []
    for c, o in enumerate(offsets):
        f, p = spectrum(frames[:, c, :])
        power, _ = tone_power(f, p, out_freq(tone, tunings[c]))
        measured.append(db(power))
    ref = measured[0]
    rows = []
    for c, o in enumerate(offsets):
        rel = measured[c] - ref
        line = f"offset {o/1e3:6.1f} kHz (output {alias(o)/1e3:+6.1f} kHz): " \
               f"{rel:8.2f} dB"
        if CHAIN.startswith("cic"):
            want = cic_response_db(o) - cic_response_db(offsets[0])
            line += f"   analytic {want:8.2f} dB"
            rows.append((o, rel, want))
        dut._log.info("RESPONSE %s", line)
    if CHAIN.startswith("cic"):
        for o, rel, want in rows:
            if want > -90:
                assert abs(rel - want) < 0.2, f"{o} Hz: {rel:.2f} vs {want:.2f}"
            if CHAIN == "cicfir" and o >= 125_000:
                assert rel < -80, f"alias from {o} Hz only {rel:.1f} dB down"
    else:
        for o, rel in zip(offsets, [m - ref for m in measured]):
            if o <= 20_000:
                assert abs(rel) < 0.5, f"passband ripple at {o} Hz"
            if o >= 125_000:
                assert rel < -80, f"alias from {o} Hz only {rel:.1f} dB down"


@cocotb.test()
async def test_spurs(dut):
    """One -1.6 dBFS tone in every channel: worst spur below -95 dBc."""
    tone = tone_freq(10_120_000)
    write_stim([(tone, 1700.0)])
    tunings = [round(tone - 7_000 - 1_100 * c) for c in range(NR)]
    frames, _ = await run_capture(dut, tunings, outputs=4096)
    worst = []
    for c in range(NR):
        f, p = spectrum(frames[:, c, :])
        offset = out_freq(tone, tunings[c])
        carrier, k = tone_power(f, p, offset)
        q = p.copy()
        q[max(0, k - WINDOW_HALF):k + WINDOW_HALF + 1] = 0
        # Keep the comparison to the band a host would display.
        band = np.abs(f) < OUT_RATE * 0.4
        spur_bin = int(np.argmax(q * band))
        spur, _ = tone_power(f, q, f[spur_bin])
        worst.append(db(spur / carrier))
        dut._log.info("SPUR ch%-2d worst %.1f dBc at %+.0f Hz", c, worst[-1],
                      f[spur_bin])
    dut._log.info("SPUR NR=%d %s worst over channels: %.1f dBc", NR, CHAIN,
                  max(worst))
    assert max(worst) < -95


# Cross-build comparison (`make compare-builds`). Channels 0-9 get the same
# tuning whatever NR is, so a 10-receiver and a 12-receiver radio.v can be
# compared channel by channel. Channels 10 and 11 copy channels 8 and 9, which
# are in the same mix2 slots, so they must match them bit for bit.
XBUILD_TUNINGS = [
    [1_030_000 + 2_310_000 * c for c in range(10)],
    [3_570_000 + 1_870_000 * c for c in range(10)],
]


def xbuild_tunings(base):
    t = list(base)
    t += [t[8], t[9]]          # channels 10 and 11, when NR is 12
    return t[:NR]


def write_xbuild_stim():
    """A tone near every channel of both tuning sets, plus seeded noise.

    It does not depend on NR, so every build sees the same ADC samples. The
    noise keeps all the low-order bits of every stage busy.
    """
    n = np.arange(STIM_LEN)
    x = np.zeros(STIM_LEN)
    for k, base in enumerate(XBUILD_TUNINGS):
        for c, t in enumerate(base):
            f = tone_freq(t + 4_000 + 3_100 * c + 1_700 * k)
            x += 90.0 * np.cos(2 * np.pi * (f / FS) * n + 0.37 * c + k)
    x += np.random.default_rng(20261122).normal(0.0, 250.0, STIM_LEN)
    x = np.clip(np.round(x), -2048, 2047).astype(np.int64)
    with open("stim.mem", "w") as fd:
        for v in x:
            fd.write(f"{v & 0xFFF:03x}\n")


XBUILD = os.environ.get("XBUILD") == "1"


@cocotb.test(skip=not XBUILD)
async def test_cross_build_capture(dut):
    """XBUILD=1: save channels 0-9 of two captures for compare_builds.py.

    It must be the only test in the run (the Makefile target filters for it):
    radio.v never resets the receivers' filter state, so captures can only be
    compared across builds when both start from power-up and see the same
    commands in the same order.
    """
    assert CAPTURES == 0, "run this test alone, from power-up state"
    assert NR >= 10, "the comparison covers channels 0-9"
    write_xbuild_stim()
    for k, base in enumerate(XBUILD_TUNINGS):
        frames, _ = await run_capture(dut, xbuild_tunings(base), outputs=2048,
                                      compare=False, pad_to=len(RXFREQ_ADDR))
        nonzero = float(np.mean(frames != 0))
        assert nonzero > 0.9, f"capture {k}: output mostly zero"
        if NR == 12:
            for c, ref in ((10, 8), (11, 9)):
                diff = int(np.sum(frames[:, c, :] != frames[:, ref, :]))
                assert diff == 0, f"capture {k}: channel {c} differs from {ref}"
            dut._log.info("capture %d: channels 10, 11 bit-identical to 8, 9",
                          k)
        path = f"xbuild_{CHAIN}_nr{NR}_capture{k}.npy"
        np.save(path, frames[:, :10, :])
        dut._log.info("capture %d: saved %s, %d frames, %.3f nonzero", k,
                      path, len(frames), nonzero)


@cocotb.test(skip=CHAIN != "cicshared" or XBUILD)
async def test_every_capture_matched_cic(dut):
    """CHAIN=cicshared: every capture above equalled the CHAIN=cic run's."""
    dut._log.info("compared captures: %s", COMPARED)
    assert len(COMPARED) == CAPTURES and CAPTURES == 4, \
        "missing CHAIN=cic reference; run `make compare-shared`"


# ------------------------------------------------------------------ transmit

CMDA_TXFREQ = 0x01
CMDA_LATENCY = 0x17
TX_FREQ = 7_100_000
TX_STIM_LEN = 4096                 # tb loops this many 48 kHz samples
TX_AUDIO_BIN = 128                 # 128 * 48000 / 4096 = 1500 Hz, loops seamlessly
TX_AUDIO = TX_AUDIO_BIN * 48_000 / TX_STIM_LEN
TX_AMPLITUDE = 16000
TX_SETTLE = 400_000                # clocks after PTT: FIR, CIC and the FIFO-less start
TX_WINDOW = 2 ** 19                # DAC words analysed (146 Hz bins)
RRRR = 200                         # radio.v TX CIC rate at 76.8 MHz
GBITS = 31
UPCONV_GAIN = 0.41169              # CORDIC gain / 4, which tx_nco_upconv matches


def tx_expected_amplitude():
    """DAC amplitude for a complex tone of TX_AMPLITUDE, as tx_chain computes it:
    FIR phase sum / 2^13, CIC RRRR^4 / 2^(20 + GBITS - 16), upconverter, then >>> 2."""
    rtl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "rtl")
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rx_chain"))
    import mif2mem
    _, words = mif2mem.parse_mif(os.path.join(rtl, "radio_openhpsdr1", "firrom", "coefI8_1024.mif"))
    coef = np.array([w - (1 << 18) if w & (1 << 17) else w for w in words], dtype=float)
    fir_gain = np.mean([coef[p::8].sum() for p in range(8)]) / 2 ** 13
    cic_gain = RRRR ** 4 / 2 ** (20 + GBITS - 16)
    return TX_AMPLITUDE * fir_gain * cic_gain * UPCONV_GAIN / 4


def write_tx_stim():
    n = np.arange(TX_STIM_LEN)
    ph = 2 * np.pi * TX_AUDIO_BIN * n / TX_STIM_LEN
    i = np.round(TX_AMPLITUDE * np.cos(ph)).astype(np.int64)
    q = np.round(TX_AMPLITUDE * np.sin(ph)).astype(np.int64)
    with open("tx_stim.mem", "w") as fd:
        for a, b in zip(i, q):
            fd.write(f"{a & 0xFFFF:04x}{b & 0xFFFF:04x}\n")


async def capture_dac(dut, clocks):
    dut.tx_capture.value = 1
    await ClockCycles(dut.clk, 2)
    while int(dut.dac_words.value) < clocks:
        await ClockCycles(dut.clk, 4096)
    dut.tx_capture.value = 0
    await ClockCycles(dut.clk, 2)
    w = np.fromfile("tx_dac.bin", dtype="<u4").astype(np.int64) & 0xFFF
    w = np.where(w >= 2048, w - 4096, w)
    assert len(w) >= clocks, f"captured {len(w)} DAC words, wanted {clocks}"
    return w[:clocks].astype(float)


@cocotb.test(skip=not TX or XBUILD)
async def test_transmit_through_radio(dut):
    """PTT and a 1.5 kHz complex tone (I = cos, Q = sin) through radio.v's TX
    path: the DAC is silent before PTT, then carries one tone at the level the
    chain gain predicts, with the other sideband below -100 dBc and every spur
    below -85 dBc.

    radio.v puts this tone 1.5 kHz BELOW the carrier, with cpl_cordic (TX=cordic)
    as with tx_nco_upconv: that is the stock HL2 convention, which client
    software already matches, so the test expects it."""
    write_stim([])                 # ADC quiet; the receivers run regardless
    write_tx_stim()
    dut.rst.value = 1
    dut.capture.value = 0
    dut.tx_run.value = 0
    dut.tx_capture.value = 0
    dut.cmd_rqst.value = 0
    dut.load_stim.value = 0
    await Timer(1, unit="ns")
    dut.load_stim.value = 1
    await ClockCycles(dut.clk, 20)
    await command(dut, CMDA_GENERAL, (RX_RATE_192K << 24) | ((NR - 1) << 3))
    await command(dut, CMDA_TXFREQ, TX_FREQ)
    await command(dut, CMDA_LATENCY, 0)    # no TX buffer wait, no PTT hang
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2000)

    idle = await capture_dac(dut, 8192)
    dut._log.info("before PTT: DAC words %d..%d", int(idle.min()), int(idle.max()))
    assert np.all(idle == 0), "DAC is not silent before PTT"

    dut.tx_run.value = 1
    await ClockCycles(dut.clk, TX_SETTLE)
    s0 = int(dut.tx_samples.value)
    dac = await capture_dac(dut, TX_WINDOW)
    rate = (int(dut.tx_samples.value) - s0) / ((TX_WINDOW + 8) / FS)
    dut._log.info("TX samples taken at %.0f Hz", rate)
    assert abs(rate - 48_000) < 500, f"radio.v took TX samples at {rate:.0f} Hz, not 48 kHz"

    win = np.kaiser(TX_WINDOW, 20)        # sidelobes below -140 dB; main lobe about +-7 bins
    spec = np.abs(np.fft.rfft(dac * win)) / (win.sum() / 2)
    binhz = FS / TX_WINDOW
    f_up = nco_freq(TX_FREQ) - TX_AUDIO    # the wanted tone (see docstring)
    f_lo = nco_freq(TX_FREQ) + TX_AUDIO    # the other sideband

    def level(f):
        k = int(round(f / binhz))
        return spec[k - 3:k + 4].max(), k

    up, kup = level(f_up)
    lo, klo = level(f_lo)
    want = tx_expected_amplitude()
    mask = np.ones(len(spec), bool)
    mask[:8] = False                           # DC: the >>> 2 truncation offset
    mask[kup - 16:kup + 17] = False         # the tone's main lobe (+-2.3 kHz)
    kspur = int(np.argmax(np.where(mask, spec, 0)))
    dut._log.info("tone at %.0f Hz: %.1f DAC codes (predicted %.1f, %+.3f dB), peak word %d",
                  f_up, up, want, 20 * np.log10(up / want), int(np.abs(dac).max()))
    dut._log.info("other sideband %.0f Hz: %.1f dBc; worst spur %.1f dBc at %.0f Hz",
                  f_lo, 20 * np.log10(lo / up), 20 * np.log10(spec[kspur] / up), kspur * binhz)
    assert abs(20 * np.log10(up / want)) < 0.5, "tone level differs from the chain gain"
    assert np.abs(dac).max() < 2047, "DAC word at full scale"
    # Limits 20 and 10 dB above the values measured with either upconverter
    # (sideband -121 to -124 dBc, worst spur -95 dBc).
    assert 20 * np.log10(lo / up) < -100, "other sideband not suppressed"
    assert 20 * np.log10(spec[kspur] / up) < -85, "spur above -85 dBc"

    dut.tx_run.value = 0
    await ClockCycles(dut.clk, 400_000)
    after = await capture_dac(dut, 8192)
    dut._log.info("after PTT release: DAC words %d..%d", int(after.min()), int(after.max()))
    assert np.all(after == 0), "DAC is not silent after PTT release"
