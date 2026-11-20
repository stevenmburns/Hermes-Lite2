# many_rx: production radio.v with up to 12 receivers

## Overview

`rx_chain` tests one mixer and four receivers that its testbench wires up
itself. This bench instantiates `rtl/radio_openhpsdr1/radio.v`, so the code
that only matters with many receivers is the production code:

- the frequency-register decode (`CMDA_RXFREQ0..11`, `nco_index`);
- the mixer-pair mapping (pair 0 serves channels 0 and 2, pair 1 serves 1 and
  3, pair p >= 2 serves 2p and 2p+1);
- the per-channel arrays and the ADC fanout `adcpipe`;
- the upstream multiplexer, which sends every channel's I and Q each time
  channel 0's strobe fires.

The command bus is driven directly, as `usopenhpsdr1.v` would drive it. The
ADC replays `stim.mem` in a loop, and the testbench writes every upstream word
to `rx_stream.bin`.

```sh
make                     # CHAIN=full NR=12: cic, varcic_mem, firX8R8 at 192 ksps
make CHAIN=cic NR=12     # receiver_ciconly.v, the hl2b5up_cicrx chain
make compare-shared NR=12   # CHAIN=cic, then CHAIN=cicshared (CIC_SHARED),
                         # which must match it bit for bit, capture by capture
make NR=4                # 4 receivers: radio.v uses CALCTYPE 3 at NR <= 5, 0 above
make RADIO_V=/path/to/radio.v   # test another copy of radio.v
```

A run of the four tests takes about 1 to 2.5 minutes.

## Tests

| Test | Checks |
| --- | --- |
| `test_same_tuning_slot_classes_identical` | All channels tuned to one frequency. Channels in the same mix2 time slot give bit-identical output, and the two slots agree in power within 0.01 dB |
| `test_stream_format_and_mapping` | One tone per channel. Each tone appears in its own channel only, at the right frequency. The stream carries 2 x NR words per output with `tlast` on the last, one output every 400 clocks |
| `test_frequency_response` | One ADC tone, with channel c tuned so the tone sits at offset c. This measures NR points of the response in one run, including offsets that alias. `CHAIN=cic` must match the analytic CIC response within 0.2 dB. `CHAIN=full` must be flat within 0.5 dB to 20 kHz, with aliases at least 80 dB down from 125 kHz |
| `test_spurs` | One tone in every channel. The worst spur within ±0.4 x the sample rate must be below -95 dBc |

The slot test must be the first capture after power-up. `radio.v` never
resets the receivers' filter state, and the pruned CICs do not cancel
arbitrary leftover state exactly, so channels with different histories need
not match bit for bit afterwards. The test checks that it ran first.

The bench relies on retuning instead of a bit-exact model. `rx_chain`
(CALCTYPE 3) and `sincos` (CALCTYPE 0 and 3) already check the arithmetic bit
for bit.

## Results

All four tests pass for `CHAIN=full NR=12`, `CHAIN=cic NR=12` and
`CHAIN=full NR=4`.

**A bug found above 10 receivers.** `adcpipe`, the per-pair ADC fanout, had
five entries. With 11 or 12 receivers the sixth mixer pair read past its end,
so channels 10 and 11 got no signal. Quartus stops on it with error 10251, so
no bitstream was ever built that way. Running the bench against the earlier
`radio.v` (via `RADIO_V`) fails `test_stream_format_and_mapping` with
"channel 10: tone not where it should be".

Frequency response at 192 ksps, relative to a 5 kHz offset. An "output" in
brackets is where an offset past ±96 kHz aliases to:

| Offset | Full chain | CIC only (measured) | CIC only (analytic) |
| --- | --- | --- | --- |
| 20 kHz | -0.07 dB | -0.58 dB | -0.58 dB |
| 40 kHz | -0.07 dB | -2.48 dB | -2.48 dB |
| 60 kHz | -0.11 dB | -5.73 dB | -5.73 dB |
| 85 kHz | -0.29 dB | -11.99 dB | -11.99 dB |
| 95 kHz | -5.95 dB | -15.29 dB | -15.29 dB |
| 110 kHz (-82 kHz) | -90.6 dB | -21.30 dB | -21.30 dB |
| 125 kHz (-67 kHz) | -97.0 dB | -28.89 dB | -28.89 dB |
| 150 kHz (-42 kHz) | -99.8 dB | -46.97 dB | -46.97 dB |
| 175 kHz (-17 kHz) | -94.1 dB | -81.44 dB | -81.42 dB |
| 250 kHz (+58 kHz) | -94.9 dB | -56.10 dB | -56.10 dB |

The CIC-only chain droops 12 dB by 85 kHz, and signals from 96 to 150 kHz
away alias into the band only 15 to 47 dB down.

Worst spur over all channels: -103.3 dBc for full, NR=4 (CALCTYPE 3);
-103.0 dBc for full, NR=12 (CALCTYPE 0); -104.6 dBc for CIC only, NR=12. In
this test the cheaper CALCTYPE 0 sine and cosine cost under 0.5 dB.

**Shared second CIC stage.** `CHAIN=cicshared` builds the CIC-only chain
with `CIC_SHARED`, so one `cic_s2_shared` does every receiver's second stage
(see `../cic_s2_shared/README.md`). Each capture is saved by the `CHAIN=cic`
run and compared with it; `test_every_capture_matched_cic` fails if any
reference is missing. With 12 receivers all four captures match, up to 4,091
frames x 12 channels. The first whole frame may be one output apart, because
the shared stage's strobe comes 59 clocks later in the output period.

These are simulation results. Nothing here has been measured on a radio.

## Files

| File | Purpose |
| --- | --- |
| `tb_many_rx.sv` | Clocks, ADC replay, `radio.v`, upstream capture to `rx_stream.bin` |
| `test_many_rx.py` | Command-bus driver, spectrum analysis, the tests |
| `Makefile` | `NR`, `CHAIN` and `RADIO_V`. Reuses `../rx_chain/altsyncram_model.v` and `mif2mem.py` |
