# tx_chain: production transmit interpolation test

## Overview

This bench tests the TX interpolation path that `hl2b5up_main` builds at 76.8 MHz:

```
48 ksps I/Q -> FirInterp8_1024 (x8) -> CicInterpM5 (x200) -> 76.8 MHz I/Q
```

It is wired as in `radio.v` and compiles the `USE_ALTSYNCRAM` code paths, so the
FIR's coefficient ROM and sample RAM have their production read latency (two
clocks each). The ROM contents come from the production `.mif`.
`altsyncram_model.v` and `mif2mem.py` are shared with `../rx_chain`.

The CORDIC upconverter after the CIC is not included; `../cpl_cordic` covers it.

## How it works

The clock stays stopped until cocotb starts the run, so the simulation begins from
the power-up state. A single run of 2,564 input samples (4.1 million clocks) feeds
four segments: 600 samples of full-scale noise, two isolated full-scale impulses,
four tones, then zeros. `tb_tx_chain.sv` writes every CIC output and every FIR
output the CIC samples to raw files, and all four tests check that one capture.

`tx_chain_model.py` models both blocks bit for bit from power-up, so no output is
skipped.

## Tests

| Test | What it checks | Measured |
| --- | --- | --- |
| `test_fir_outputs_bit_exact` | Every FIR output, I and Q, matches the model | 20,512 of 20,512 |
| `test_cic_outputs_bit_exact` | Every CIC output on every clock matches the model | 4,102,399 of 4,102,399 |
| `test_tone_gain_and_flatness` | Tones at +1.7, -7.0, +14.1 and -15.0 kHz are within 0.2 dB of the gain computed from the coefficients and CIC growth, and within 0.1 dB of each other | +0.001 to +0.003 dB |
| `test_images_and_spurs` | Worst spur below 192 kHz under -72 dBc, from 192 kHz to 1.536 MHz under -100 dBc | -78.3 dBc at -33.9 kHz, -110.3 dBc at +193.7 kHz |

The spur limits sit 6 and 10 dB above the measured values, so they guard against
regressions rather than prove a specification.

Twelve hand-made mutations were each caught. Six in `CicInterpM5.v` failed only
the CIC check. Six in the FIR, its ROM latency and its RAM latency failed both.

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
make
```

A run takes about 25 seconds from clean. Quartus is not required.

## Files

| File | Purpose |
| --- | --- |
| `tb_tx_chain.sv` | Clock, stimulus handshake, DUT wiring and raw capture |
| `tx_chain_model.py` | Bit-exact numpy model of the FIR and CIC |
| `test_tx_chain.py` | Stimulus and the cocotb tests |
