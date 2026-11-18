# rx_chain: production receive chain test

## Overview

This bench tests the receive path that `hl2b5up_main` builds at 76.8 MHz:

```
ADC -> mix2/nco2/sincos -> cic (R=5) -> varcic (R=5/10/20/40) -> firX8R8 (R=8)
```

One `mix2` serves two `receiver_nco` channels, wired as in `radio.v`. Unlike the
`rx1`, `rx2` and `rx2iq` benches, it compiles the `USE_ALTSYNCRAM` code paths used
by the production build and reads the production `.mif` ROM files.

## Coarse ROM latency regression

This bench found a regression from commit `7d3b4a2`, which set
`outdata_reg_a = "CLOCK0"` in `rtl/nco/coarserom.v`. That gave the coarse sine ROM
two clocks of read latency, while `sincos.v` is pipelined for one, as the inferred
ROM had before that commit. The coarse magnitude arrived one `clk_2x` cycle late,
and because `mix2` interleaves two channels on that clock, it belonged to the other
receiver channel. `sincos.v` now drives the ROM with the unregistered address, so
the M9K address register replaces the `coarse_addr` flop and the output stays
registered.

| Measurement | Regression | Corrected latency (current) |
| --- | --- | --- |
| Tests passing | 4 of 8 | 8 of 8 |
| Mixer samples matching the model | 16 of 3800 | 3800 of 3800 |
| Tone gain relative to correct chain | -1.8 dB | 0 dB |
| Response at 3x the tuned frequency | -9.2 dB | no output |
| Response at 5x the tuned frequency | -14.0 dB | no output |
| Retuning channel 1 changes channel 0 | yes | no |

The gain and harmonic levels are those of a square-wave local oscillator. Both the
regression and the fix have been shown in simulation only, using
`altsyncram_model.v` rather than Intel's `altera_mf.v`, and have not been measured
on hardware.

## Tests

| Test | What it checks |
| --- | --- |
| `test_rom_images_match_text_sources` | Each `.mif` matches its independent `.txt` copy |
| `test_sincos_model_agrees_with_register_model` | The fast NCO model matches `hlmodel.Sincos` |
| `test_mixer_outputs_bit_exact` | Both mixer channels match the model on every clock |
| `test_receiver_bit_exact_at_every_rate` | Noise input, both channels, I and Q, at 48/96/192/384 ksps |
| `test_channels_are_independent` | Retuning channel 1 leaves channel 0 bit-identical |
| `test_tone_frequency_image_and_spurs` | Tone position, image below -100 dBc, spurs below -90 dBc |
| `test_lo_harmonic_rejection` | Signals at 3x and 5x the tuned frequency are below -80 dB |
| `test_passband_flatness_and_alias_rejection` | Ripple under 0.5 dB to +/-20 kHz, aliases below -80 dB |

## Files

| File | Purpose |
| --- | --- |
| `tb_rx_chain.sv` | Clocks, ADC stimulus replay and the production wiring |
| `altsyncram_model.v` | Behavioural altsyncram with production read latency |
| `mif2mem.py` | Converts production `.mif` files for `$readmemh` |
| `rx_chain_model.py` | Bit-exact numpy model of the chain |
| `test_rx_chain.py` | The cocotb tests |

## Running

Activate an environment with cocotb, numpy and scipy, then:

```sh
cd gateware/sim_cocotb/rx_chain
make
```

Quartus is not required. Python writes `stim.mem`, a 65536-sample ADC sequence that
the testbench replays. Each comparison skips the first 140 outputs, which still
depend on the previous test's FIR history.
