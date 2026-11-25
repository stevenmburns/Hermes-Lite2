# adc_meter: ADC clip count and peak level

`rtl/adc_meter.v` measures the raw ADC samples at the ADC clock. Every
2^19 samples (6.8 ms at 76.8 MHz) it latches, for the window just ended:

| Bits | Field |
| --- | --- |
| 31:16 | Samples at full scale (0x7ff or 0x800, the stock overload test), saturating at 65535 |
| 15:12 | Window number, wrapping; a new value means a new window |
| 11:0 | Peak \|ADC\|, 0 to 2048 (dBFS = 20 log10(peak / 2048)) |

`hermeslite_core` carries the word into the control clock with
`sync_qualifier` and, with `ADC_METER = 1` (`hl2b5up_cicfir_tx`), sends it as
the data of response slot 3 (C0 address 3, unused in stock HL2): C1 C2 are
the clip count, C3 C4 the window number and peak. Builds with `ADC_METER = 0`
send what they always did.

The stock overload bit only says that at least one sample clipped since the
last status frame. The clip count says how often, and the peak says how much
headroom is left when nothing clips.

## Bench

`tb_adc_meter.sv` runs the meter at 76.8 MHz and `sync_qualifier` at
2.5 MHz, as wired in `hermeslite_core`. The stimulus (`model.py`) has
windows with no clips, all zeros, clips of both polarities, every sample
clipped, 0x7ff clips only, a single 0x800, and random levels. The test:

- compares every latched word with the bit-exact model in `model.py`,
  searching the input delay, which must be unique (window 6 ends in a run of
  clips that splits between windows by the delay);
- checks that the stimulus reached clip count 0 and above 40, peaks 0, 2047
  and 2048, and, for the production window, saturation at 65535;
- checks that the control-clock side receives every word exactly once, in
  order, unchanged.

```sh
make                    # WINDOW_LOG2=12: 9 windows of 4096 samples, under a second
make WINDOW_LOG2=19     # the production window, about 15 s
```

Results: both pass, 9 of 9 windows bit-exact. With `WINDOW_LOG2=19` the
all-clip window reads 65535. Two hand-made mutations are caught: counting
only 0x7ff as a clip, and leaving the window's last sample out of the count.
