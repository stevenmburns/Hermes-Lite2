# cic_s2_shared: shared second CIC stage against the original

## Overview

`rtl/radio_openhpsdr1/cic_s2_shared.v` does the second CIC stage of
`receiver_ciconly.v` (`cic_s2`: N=4, R=25, 18 bits in, 24 bits out) for up to
28 I/Q streams, with the integrator and comb state in block RAM. `radio.v`
uses it when `CIC_SHARED` is defined, as `hl2b5up_cicrx` now does.

This bench drives NS separate `cic_s2` instances and one `cic_s2_shared` from
the same strobes and inputs, and compares every output. The strobes come
from counters like `receiver_ciconly.v`'s (strobe1 every 16 clocks, strobe2
every 25th strobe1). Each stream's input is an LFSR that changes on each
strobe1 edge, as `cic_s1`'s output register does. The reference outputs pass
through a copy of `receiver_nco`'s output register.

```sh
make            # NS=24, as for 12 receivers
make NS=7       # any stream count from 1 to 28
make SHARED_V=/path/to/variant.v   # test another copy of the module
```

## Tests

| Test | Inputs |
| --- | --- |
| `test_full_scale_random` | all 18 bits random, so every integrator wraps |
| `test_quiet_random` | within ±2^9, so the high bits are sign copies |

Each compares 1,500 outputs of every stream and checks that over half of the
reference values are nonzero.

## Results

| NS | Lanes | Mismatches (both tests) | Output strobe vs. original |
| --- | --- | --- | --- |
| 1 | 1 | 0 | 7 clocks earlier |
| 7 | 1 | 0 | 29 clocks later |
| 20 | 2 x 10 | 0 | 47 clocks later |
| 24 | 2 x 12 | 0 | 59 clocks later |
| 28 | 2 x 14 | 0 | 71 clocks later |

The output period is 400 clocks, so the strobe moves but never by more than
71 clocks.

Planted bugs (`SHARED_V`, full-scale test, NS=24):

| Change | Result |
| --- | --- |
| third integrator takes `i2[35:2]` instead of `i2[36:3]` | caught, 35,903 mismatches |
| first comb takes `carry[28:0]` instead of `carry[29:1]` | caught, 35,903 mismatches |
| output takes `old_out[24:1]` instead of `[25:2]` | caught, 35,903 mismatches |
| comb run carries each stage's new output instead of its old one | caught, 35,975 mismatches |
| comb run starts at phase L-1 instead of L+1 | not caught: equivalent |

The last change is equivalent, not a gap. Starting two phases earlier still
puts the comb engine's first write after the last integrator write, because
a comb write comes three clocks after its start.

At the system level, `many_rx` with `CHAIN=cicshared` (`make compare-shared`)
runs the production `radio.v` with 12 receivers. Every capture is
bit-identical to the `CHAIN=cic` run.

## Files

| File | Purpose |
| --- | --- |
| `tb_cic_s2_shared.sv` | Strobes, LFSR inputs, NS `cic_s2` references, the shared module |
| `test_cic_s2_shared.py` | Collects both output streams and compares them |
| `Makefile` | `NS` and `SHARED_V` |
