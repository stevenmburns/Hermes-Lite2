# debounce: CW key and PTT input debouncer, with candidate replacements

## Overview

`rtl/debounce.v` cleans up the key, PTT and TX-inhibit inputs. `control.v`
uses four instances: `de_phone_tip` (key tip, `ext_cwkey`), `de_phone_ring`
(key ring), `de_txinhibit` and `de_ptt`. On each `msec_pulse` it shifts `pb`
into a six-sample history. When the history before that shift is "stable",
`clean_pb` takes the new sample; otherwise it holds.

The header comment, "Debounce with immediate response if last signal
stabilized", says "stable" should mean all six samples equal. The committed
expression is

```verilog
assign stable = (&pb_history) | (|pb_history);
```

which reduces to `|pb_history`. While any of the last six samples is 1,
`clean_pb` copies `pb` on every pulse, so bounce passes through.

The bench simulates the committed module and five alternatives. All have the
same ports and use the same 1 ms `msec_pulse` tick:

| `DUT=` | Design | Source |
| --- | --- | --- |
| `committed` | as committed | `rtl/debounce.v` |
| `fixed` | the comment's intent: `(&pb_history) \| ~(\|pb_history)`. Passes the first edge, then ignores 6 samples | `sed` copy in `sim_build_fixed/` |
| `cl` | confirm then lock out: switch after 2 agreeing samples, then ignore 6 | `candidates/debounce_cl.v` |
| `run` | switch after 4 agreeing samples in a row (sampled restart-on-change timer) | `candidates/debounce_run.v` |
| `integ` | saturating up/down counter 0..4, switch at the ends | `candidates/debounce_integ.v` |
| `hold` | equal delay on both edges: on when the oldest of D+1 samples is 1 (with `CONFIRM`, and a newer one is too), off when all are 0 | `candidates/debounce_hold.v` |

`run` and `integ` are the two common textbook designs (for example MIT 6.111's
restart-on-change timer, and the integrator in Ganssle's guide). The files in
`candidates/` are for the bench and are not compiled into any build.

## Running

```sh
make all-duts      # all six designs, results_<dut>.log each, PASS/FAIL per line
make DUT=cl        # one design
make DUT=hold HOLD_D=2 HOLD_CONFIRM=0   # hold with other parameters
make hold-sweep    # hold for D = 2..6, with and without CONFIRM
```

`msec_pulse` is driven every 8 clocks instead of every 1 ms, because the
modules only act on pulses. Each pulse takes one `pb` sample. Bounce faster
than 1 ms reaches a module only as the level present at each pulse.

## Tests

Each design has a pulse-level Python model.

| Test | Checks |
| --- | --- |
| `test_matches_model_random` | 2,004 random bouncy samples, RTL against model on every pulse |
| `test_matches_model_keying` | 40 keyed elements with bounce and spikes, RTL against model |
| `test_models_differ` | the six models give six different outputs (guards the model tests) |
| `test_bounce_gives_one_press_and_one_release` | a fixed bounce pattern, three keyings, six edges |
| `test_press_is_immediate` | the first sample of a press reaches `clean_pb` |
| `test_realistic_keying_no_extra_edges` | 150 random elements, two edges each |
| `test_spikes_rejected` | the same keying plus isolated 1 ms spikes, two edges each |
| `test_width_not_shortened` | the 150 elements without spikes: every press has the same delay, and no element comes out shorter than keyed |
| `test_keying_metrics`, `test_single_sample_glitch` | log the numbers below |

The property tests are marked `expect_fail` for a design that lacks the
property, so every design reports all 10 tests passing. A design that gains or
loses a property shows up as a failure.

The keying stimulus uses key-down and key-up times of 12 to 60 ms; a dit at
100 WPM is 12 ms. Each edge bounces for 0 to 6 ms, as random samples that
start with the new level. Ganssle measured bounce at about 1.6 ms on average
and 6.2 ms for his worst switch. Spikes are single-sample inversions, at least
8 ms from an edge and 3 samples from each other.

## Results

Seed 1, 150 elements. Delays run from the first contact of an edge, in whole
samples. Width error is output pulse width minus keyed width.

| Design | Extra edges, bounce only | Extra edges, with 1 ms spikes | Press delay, mean (range) | Release delay, mean (range) | Width error | 1 ms spike from idle |
| --- | --- | --- | --- | --- | --- | --- |
| committed | 344 | 554 | n/a | n/a | n/a | ignored |
| fixed | 0 | 392 | 0 ms | 0 ms | 0 ms | 7 ms pulse |
| cl | 0 | 0 | 2.2 ms (1–7) | 2.2 ms (1–7) | −6 to +6 ms | ignored |
| run | 0 | 0 | 4.9 ms (3–9) | 5.2 ms (3–9) | −6 to +6 ms | ignored |
| integ | 0 | 0 | 4.7 ms (3–9) | 5.0 ms (3–9) | −6 to +6 ms | ignored |
| hold, D=4 | 0 | 208 | 5 ms (5–5) | 7.3 ms (5–11) | 0 to +6 ms | 1 ms pulse |
| hold, D=5, CONFIRM | 0 | 18 | 6 ms (6–6) | 8.3 ms (6–12) | 0 to +6 ms | ignored |

- **committed:** bounce and spikes pass through. Delay figures can't be paired
  because of the extra edges.
- **fixed:** adds no delay and removes bounce, but every spike gets through,
  stretched to the 7-sample lockout. A spike during key-down also gets through,
  as a dropout.
- **cl, run, integ:** all reject bounce and isolated spikes. `cl` has less than
  half the delay of the other two. Bounce at either edge moves that edge by up
  to its length, which gives the ±6 ms width error for all three.
- **cl and spikes:** two spikes next to each other make a 2 ms spike, which
  `cl` passes by design (`CONFIRM=2`). `run` and `integ` reject spikes up to 3
  samples long.
- **hold:** delays both edges by the same D+1 samples, so the element keeps its
  keyed width. On comes D+1 samples after the first contact, with no
  confirmation; off comes D+1 samples after the last contact, once the window
  is all open. Release delay above is measured from the first open sample, so
  it includes the release bounce. The only width error is that release bounce,
  0 to +6 ms here; press bounce no longer shortens an element. D only has to
  span the longest open gap inside a bounce burst, not the whole burst.
- **hold and spikes:** without `CONFIRM` every 1 ms spike in key-up comes out
  as a 1 ms pulse, delayed but not stretched; dropouts during key-down are
  filled. With `CONFIRM`, a lone spike is ignored; the remaining extra edges are
  two spikes 3 samples apart that land in the same window.

`hold` sweep (`make hold-sweep`), same stimulus:

| D | CONFIRM | Extra edges, bounce only | Extra edges, with spikes | Press delay, mean (range) | Width error |
| --- | --- | --- | --- | --- | --- |
| 2 | 0 | 50 | 266 | | |
| 3 | 0 | 14 | 226 | | |
| 4 | 0 | 0 | 208 | 5 ms (5–5) | 0 to +6 ms |
| 5 | 0 | 0 | 202 | 6 ms (6–6) | 0 to +6 ms |
| 6 | 0 | 0 | 200 | 7 ms (7–7) | 0 to +6 ms |
| 2 | 1 | 16 | 14 | | |
| 3 | 1 | 0 | 12 | 4.3 ms (4–9) | −4 to +6 ms |
| 4 | 1 | 0 | 14 | 5.1 ms (5–10) | −2 to +6 ms |
| 5 | 1 | 0 | 18 | 6 ms (6–6) | 0 to +6 ms |
| 6 | 1 | 0 | 24 | 7 ms (7–7) | 0 to +6 ms |

The stimulus is harsh for this design: its bounce is random 1 ms samples, so an
edge can show up to 5 open samples in a row while still bouncing, and D has to
be 4 or more to bridge that. Real contact bounce is mostly gaps well under a
millisecond, which a 1 ms sample rarely sees twice in a row, so D = 2 (3 ms
latency) may be enough on a real key. With `CONFIRM`, D below 5 lets a press
whose first contact is followed by D open samples start at its next contact,
which is where the negative width error comes from.

`msec_pulse` comes from `control.v`, where the quarter-millisecond counter
reloads to 625 and so has a period of 626 cycles of the 2.5 MHz control clock.
Each "millisecond" is therefore 1.0016 ms. That is not modelled here.

These are simulation results. Nothing here has been measured on a radio.

## Files

| File | Purpose |
| --- | --- |
| `Makefile` | Verilator build; `DUT=` selects the design, `all-duts` runs all six, `hold-sweep` runs `hold` over D |
| `test_debounce.py` | Models, stimulus and the cocotb tests |
| `candidates/debounce_cl.v` | Confirm-then-lockout candidate, `CONFIRM` and `LOCKOUT` parameters |
| `candidates/debounce_run.v` | Run-length comparison design |
| `candidates/debounce_integ.v` | Integrator comparison design |
| `candidates/debounce_hold.v` | Equal-delay candidate, `D` and `CONFIRM` parameters |
