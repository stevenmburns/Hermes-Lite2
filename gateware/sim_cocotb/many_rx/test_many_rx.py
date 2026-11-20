"""cocotb tests for the production radio.v with many receivers.

tb_many_rx.sv instantiates radio.v with NR receivers, so the mixer-pair
mapping, the frequency-register decode, the per-channel arrays and the
upstream multiplexer are the production code. CHAIN picks the receiver:
"full" (cic, varcic_mem, firX8R8) or "cic" (receiver_ciconly.v, the
hl2b5up_cicrx chain, fixed 192 ksps).

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


async def run_capture(dut, tunings, outputs):
    """Reset, tune channel c to tunings[c] Hz, capture `outputs` frames.

    Returns (frames, meta): frames[k] is an (NR, 2) array of signed (I, Q) for
    output frame k, after SETTLE_OUTPUTS frames are dropped; meta holds the
    raw per-word timing for the stream-format checks.
    """
    dut.rst.value = 1
    dut.capture.value = 0
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
    return frames[SETTLE_OUTPUTS:], meta


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


def cic_response_db(offset):
    """Analytic gain of receiver_ciconly.v: CIC N=4 R=16, then N=4 R=25."""
    def stage(f, rate_in, r, n):
        x = np.pi * f / rate_in
        if abs(np.sin(x)) < 1e-15:
            return 1.0
        return abs(np.sin(r * x) / (r * np.sin(x))) ** n
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
        droop = cic_response_db(expected) if CHAIN == "cic" else 0.0
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
    relative to the 5 kHz channel. For CHAIN=cic they must match the
    analytic CIC response; for CHAIN=full, the passband must be flat and the
    aliases far down.
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
        if CHAIN == "cic":
            want = cic_response_db(o) - cic_response_db(offsets[0])
            line += f"   analytic {want:8.2f} dB"
            rows.append((o, rel, want))
        dut._log.info("RESPONSE %s", line)
    if CHAIN == "cic":
        for o, rel, want in rows:
            if want > -90:
                assert abs(rel - want) < 0.2, f"{o} Hz: {rel:.2f} vs {want:.2f}"
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

