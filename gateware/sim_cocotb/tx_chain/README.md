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
| `test_images_and_spurs` | Worst spur below 192 kHz under -72 dBc, from 192 kHz to 1.536 MHz under -100 dBc | -82.2 dBc at -33.9 kHz, -115.2 dBc at +193.7 kHz |

The spur limits sit 10 and 15 dB above the measured values, so they guard against
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

## Block-RAM comb

`hl2b5up_cicfir_tx` builds with `TX_CIC_MEM`, which replaces
`CicInterpM5` with `rtl/radio_openhpsdr1/CicInterpM5Mem.v`. The integrators stay in
registers. The comb state moves into one M9K, and a single subtractor computes the
ten comb values serially, in 23 of the 200 clocks between input samples. Each comb
value is stored at IBITS + 5 = 25 bits, which is exact because each stage grows the
input by at most one bit.

Both versions pass every test here with the same model. Of 12 mutations in the new
module, 9 were caught. Two survivors are equivalent: one writes to the wrong bank,
which negates comb stages 1 to 4, and the negations cancel; the other reloads an
operand register that is not read on that step. The third reads Q directly instead
of the captured copy, which only differs if the input changes on the clock after a
sample; radio.v holds it for about 135 clocks.

Quartus 25.1std, seed 1, after place and route:

| Measurement | CicInterpM5 | 51-bit RAM | 25-bit RAM |
| --- | --- | --- | --- |
| TX CIC logic elements | 1,032 | 874 | 750 |
| Total logic elements | 19,280 | 19,121 | 19,075 |
| M9K blocks | 57 | 58 | 58 |
| Worst setup slack | +0.043 ns | +0.043 ns | +0.043 ns |

Quartus already trims the original combs to their real width, so they were only
about 470 registers. Saving 205 LEs (under 1% of the device) costs one of the 9
remaining M9Ks and does not change the worst path, so `hl2b5up_main` does not use
it. `hl2b5up_cicfir_tx` does: there logic is the scarce resource and M9Ks are not.

## Notes on the FIR

* The passband is about +/-15 kHz. A tone at -18.9 kHz comes out 1.6 dB low.
* `FirInterp8_1024` used to do NTAPS / 8 + 1 = 129 multiply-adds over its
  128-sample ring. With NTAPS = 1024 the last one wrapped to the newest sample
  again, with coefficient p (|p| <= 11, against a peak of 88,334). It now does
  exactly NTAPS / 8. The fix improved the worst image below 192 kHz from -78.3
  to -82.2 dBc, and from 192 kHz to 1.536 MHz from -110.3 to -115.2 dBc. For
  NTAPS <= 1016 with zeros in the unused ROM entries, the extra product had a
  zero coefficient, so those filters are unchanged.

## Running

Activate an environment with cocotb and numpy, then:

```sh
cd gateware/sim_cocotb/tx_chain
make                          # block-RAM comb and NCO upconverter (hl2b5up_cicfir_tx)
make TX_CIC_MEM=              # register comb and NCO upconverter, as built for hl2b5up_main
make TX_CIC_MEM= TX_NCO=      # register comb and CORDIC upconverter (stock)
```

A run takes about 40 seconds from clean. Quartus is not required.

## Files

| File | Purpose |
| --- | --- |
| `tb_tx_chain.sv` | Clock, stimulus handshake, DUT wiring and raw capture |
| `tx_chain_model.py` | Bit-exact numpy model of the FIR and CIC |
| `test_tx_chain.py` | Stimulus and the cocotb tests |
