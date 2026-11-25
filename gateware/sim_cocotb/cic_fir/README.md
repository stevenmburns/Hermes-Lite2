# cic_fir: second CIC plus a decimating FIR for the CIC-only receivers

`rtl/radio_openhpsdr1/cic_fir_shared.v` is a drop-in for `cic_s2_shared`. It
widens the alias-free band of the `hl2b5up_cicrx` receivers from about
+-35 kHz to +-75 kHz at 192 ksps.

## Why

The cicrx chain is two CICs, /16 then /25, straight to 192 ksps. Its droop is
small (-1.9 dB at 35 kHz); what limits it is aliasing. Signals outside the band
fold onto it with little attenuation:

| Offset | Droop | Worst folded image, cicrx | cicfir |
| --- | --- | --- | --- |
| 20 kHz | -0.6 dB | -75 dBc | -100 dBc |
| 35 kHz | -1.9 dB | -52 dBc | -100 dBc |
| 60 kHz | -5.8 dB | -27 dBc | -94 dBc |
| 75 kHz | -9.2 dB | -15 dBc | -86 dBc |

The cicfir gain is flat to -0.35 dB at 75 kHz, CIC droop included. A skimmer
on cicrx has to keep its decoders within about +-35 kHz of each receiver's
center (SparkSDR `ValidBandwidthRatio` 0.36); cicfir allows +-75 kHz (0.78).

## Chain

    cic_s1 (per receiver, N=4 R=16) -> 4.8 MHz
    second CIC (shared, N=4 R=5, 28 bits) -> 960 kHz
    FIR (shared, 109 taps, /5) -> 192 kHz

Decimating the CIC only to 960 kHz keeps its images far from the band
(-86 dBc or better within +-75 kHz). The FIR rejects everything that would fold
onto +-75 kHz in the last /5 (192k +- 75k and 384k +- 75k) by 90 dB. The output
level matches cicrx's.

Running the CIC to 384 kHz and adding a halfband was the first idea, but it only
doubles the clean band: the CIC's images at 384 kHz +- 80 kHz are still
-46 dBc.

## Hardware

* Second CIC: the `cic_s2_shared` scheme (integrators and combs in block RAM,
  lanes of up to 12 streams), with R=5 and no pruning, so it is exact.
* FIR: units of 3 streams, each with one M9K of delay lines and one 18x18
  multiplier, all stepping through the taps in lockstep on one coefficient
  table. A run takes 3 x 109 = 327 of the 400 clocks per output. NS=24 uses
  8 units.
* Output: one strobe per 192 kHz sample, every stream valid with it, held at
  least 181 clocks (radio.v reads 2 x NR clocks' worth).

## Files

| File | Purpose |
| --- | --- |
| `design.py` | Designs the FIR, prints the response, writes `cic_fir_coefs.vh` and `coefs.txt` |
| `model.py` | Bit-exact Python model of the module |
| `tb_cic_fir.sv`, `test_cic_fir.py` | cocotb bench |

## Bench

`make` (Verilator, NS=24) runs four tests. Each compares every output of all
24 streams with the model, after finding the two decimation phases (exactly one
alignment must match), and checks the strobe spacing and how long out_data
holds.

| Test | Input |
| --- | --- |
| `test_full_scale_random` | 18-bit random, from power-up: must match from the first output |
| `test_quiet_random` | +-2^9 random |
| `test_saturation` | A full-scale +-1 pattern matched to the chain's impulse response (its absolute gain is 1.7 x the DC gain), and its inverse: must clip at both limits. Random inputs reach only about 2.6M of the 8.4M limit, and neither does a full-scale 15 kHz square wave |
| `test_tones` | A complex tone per stream pair. Measured from the RTL output: passband gain at 9.4 to 75 kHz against `design.py` (within 0.02 dB), and the level of FIR and CIC images |

Results (Verilator 5, cocotb 2):

    full-scale random: 397 outputs x 24 streams, 0 mismatches, out_data held 181 clocks
    quiet random:      356 outputs x 24 streams, 0 mismatches
    saturation:        356 outputs x 24 streams, 0 mismatches; 130 at +2^23-1, 131 at -2^23
    tones:            1061 outputs x 24 streams, 0 mismatches
      pass   9.4 .. 75 kHz: +0.004 .. -0.336 dB, each within 0.001 dB of design
      FIR images (117, 152, 222, 324 kHz): -94.1 to -102.1 dBc
      CIC images (900, 1035 kHz):          -92.2, -88.5 dBc
