# tx_chain: production transmit interpolation test

## Overview

This bench tests the TX interpolation path that `hl2b5up_main` builds at 76.8 MHz:

```
48 ksps I/Q -> FirInterp8_1024 (x8) -> CicInterpM5 (x200) -> upconverter -> 76.8 MHz I/Q
```

It is wired as in `radio.v` and compiles the `USE_ALTSYNCRAM` code paths, so the
FIR's coefficient ROM and sample RAM have their production read latency (two
clocks each). The ROM contents come from the production `.mif`.
`altsyncram_model.v` and `mif2mem.py` are shared with `../rx_chain`.


## How it works

The clock stays stopped until cocotb starts the run, so the simulation begins from
the power-up state. A single run of 3,988 input samples (6.4 million clocks) feeds
five segments: 600 samples of full-scale noise, two isolated full-scale impulses,
four tones, a carrier near full DAC drive, then zeros. `tb_tx_chain.sv` writes
every FIR output the CIC samples, every CIC output and every upconverter output to
raw files, and all six tests check that one capture.

`tx_chain_model.py` models both blocks bit for bit from power-up, so no output is
skipped.

## Tests

| Test | What it checks | Measured |
| --- | --- | --- |
| `test_fir_outputs_bit_exact` | Every FIR output, I and Q, matches the model | 31,904 of 31,904 |
| `test_cic_outputs_bit_exact` | Every CIC output on every clock matches the model | 6,380,799 of 6,380,799 |
| `test_tone_gain_and_flatness` | Tones at +1.7, -7.0, +14.1 and -15.0 kHz are within 0.2 dB of the gain computed from the coefficients and CIC growth, and within 0.1 dB of each other | +0.001 to +0.003 dB |
| `test_images_and_spurs` | Worst spur below 192 kHz under -72 dBc, from 192 kHz to 1.536 MHz under -100 dBc | -78.3 dBc at -33.9 kHz, -110.3 dBc at +193.7 kHz |

The spur limits sit 6 and 10 dB above the measured values, so they guard against
regressions rather than prove a specification.

Twelve hand-made mutations were each caught. Six in `CicInterpM5.v` failed only
the CIC check. Six in the FIR, its ROM latency and its RAM latency failed both.

## Upconverter

The CIC output drives the upconverter as in `radio.v` (`tx_i = y2_i`,
`tx_q = y2_r`), at a fixed phase increment for 7.1 MHz. `hl2b5up_main` builds
with `TX_NCO`, which replaces `cpl_cordic` with `rtl/nco/tx_nco_upconv.v`: the
receive side's `sincos` NCO, four multipliers and a gain trim. It keeps the
CORDIC's phase accumulator, gain, 20-clock delay and phase, but it is not
bit-exact, so these two tests fit the output to an ideal rotation of its input:

| Test | What it checks |
| --- | --- |
| `test_upconverter_fit` | Delay, gain and phase of the fit, and error under -70 dBc, for the tone and carrier segments |
| `test_upconverter_carrier_spurs` | A carrier near full DAC drive: output peak, spectrum, the 12-bit DAC word, and the spectrum of the fit error |

Measured with a carrier at 1.84, 7.1, 14.2, 28.4 and 37.0 MHz:

| Measurement | cpl_cordic | tx_nco_upconv |
| --- | --- | --- |
| Delay, gain, phase | 20 clocks, 0.41169, 0.000 deg | the same |
| Error against an ideal rotation | -85.8 dBc | -85.0 to -85.1 dBc |
| Worst spur in that error | -107.4 to -113.2 dBc | -100.4 to -101.8 dBc |
| Worst spur in the 12-bit DAC word | -89.6 to -90.5 dBc | within 0.1 dB of the CORDIC |

The NCO's spurs come from the 12 phase bits sincos drops, and the DAC word's
spurs come from upstream (an FIR image 48 kHz from the carrier), so the two
designs are equivalent at the DAC. `TX_FREQ_HZ=28.4e6 make` runs another band.

## Notes on the FIR

* The passband is about +/-15 kHz. A tone at -18.9 kHz comes out 1.6 dB low.
* `FirInterp8_1024` does NTAPS / 8 + 1 = 129 multiply-adds over a 128-sample ring.
  The last one wraps to the newest sample again and uses coefficient p
  (|p| <= 11, against a peak of 88,334), adding about -80 dB of error. The model
  reproduces this so that it can be bit-exact.

## Running

Activate an environment with cocotb and numpy, then:

```sh
cd gateware/sim_cocotb/tx_chain
make                # NCO upconverter, as built for hl2b5up_main
make TX_NCO=        # CORDIC upconverter, cpl_cordic
```

A run takes about 40 seconds from clean. Quartus is not required.

## Files

| File | Purpose |
| --- | --- |
| `tb_tx_chain.sv` | Clock, stimulus handshake, DUT wiring and raw capture |
| `tx_chain_model.py` | Bit-exact numpy model of the FIR and CIC |
| `test_tx_chain.py` | Stimulus and the cocotb tests |
