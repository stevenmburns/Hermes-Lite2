# debounce: CW key and PTT input debouncer

## Overview

`rtl/debounce.v` cleans up the key, PTT and TX-inhibit inputs. `control.v` uses
four instances: `de_phone_tip` (key tip, `ext_cwkey`), `de_phone_ring` (key
ring), `de_txinhibit` and `de_ptt`. On each `msec_pulse` it shifts `pb` into a
six-sample history. When the history before that shift is "stable", `clean_pb`
takes the new sample; otherwise it holds.

The module's header comment, "Debounce with immediate response if last signal
stabilized", describes the intent. "Stable" should mean all six samples are
equal. The first edge after a quiet period then passes straight through, and
bounce is ignored until the input has been steady for six milliseconds.

The committed expression is

```verilog
assign stable = (&pb_history) | (|pb_history);
```

which reduces to `|pb_history`. While any of the last six samples is 1,
`clean_pb` copies `pb` on every pulse, so bounce on the release passes through.
Only an all-zero history blocks an update. The corrected expression is

```verilog
assign stable = (&pb_history) | ~(|pb_history);
```

## Running

```sh
make            # the committed rtl/debounce.v
make FIXED=1    # a copy with the corrected expression, built in sim_build_fixed/
```

`FIXED=1` generates `sim_build_fixed/debounce_fixed.v` from `rtl/debounce.v`
with `sed` and checks that the substitution happened. The RTL file is never
edited. The same variable selects the tests' expectations. Three
specification tests are marked `expect_fail` for the committed RTL, so both
runs report `PASS=7`. A test that starts passing where it was expected to fail
is reported as a failure.

`msec_pulse` is driven every 8 clocks instead of every 1 ms, because the
module only acts on pulses. Each pulse takes one `pb` sample. Bounce faster
than 1 ms reaches the module only as the level present at each pulse.

## Results

| Test | Committed RTL | Corrected |
| --- | --- | --- |
| `test_matches_model_random`: 2,004 random bouncy samples against a pulse-level model | 0 mismatches, 311 output edges for 356 input edges | 0 mismatches, 170 output edges |
| `test_model_distinguishes_versions` | pass | pass |
| `test_bounce_gives_one_press_and_one_release`: three bouncy keyings | 24 edges, expected fail | 6 edges |
| `test_press_is_immediate` | press 2 ms late with this bounce, expected fail | 0 ms |
| `test_release_is_immediate`: clean release after a steady press | 0 ms | 0 ms |
| `test_steady_input_after_bounce_is_followed` | 28 output changes while the history was bouncing, expected fail | 0 |
| `test_single_sample_glitch`: one 1 ms spike from idle | ignored | becomes a 7 ms pulse |

Latencies count whole pulses after the sampling pulse. The last row is the
trade-off of the intended design. It responds at once to the first edge, so it
cannot also filter a lone spike. A spike from idle holds `clean_pb` high until
the history has cleared, which takes seven pulses. The committed code ignores
a 1 ms spike, but passes anything two samples long.

With both expressions, a steady input is always followed and a clean release
takes effect at once. The difference is what happens during bounce.

`msec_pulse` itself comes from `control.v`, where the quarter-millisecond
counter reloads to 625 and so has a period of 626 cycles of the 2.5 MHz
control clock. Each "millisecond" is therefore 1.0016 ms. That is not modelled
here.

These are simulation results. Nothing here has been measured on a radio.

## Files

| File | Purpose |
| --- | --- |
| `Makefile` | Verilator build; `FIXED=1` builds the corrected copy |
| `test_debounce.py` | Pulse-level model and the cocotb tests |
