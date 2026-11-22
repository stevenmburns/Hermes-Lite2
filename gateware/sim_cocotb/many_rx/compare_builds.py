"""Compare channels 0-9 of two test_cross_build_capture runs, bit for bit.

usage: python compare_builds.py REF_TAG TAG
  e.g. python compare_builds.py cic_nr10 cicshared_nr12

Each tag names files xbuild_<tag>_capture<k>.npy. The builds' output strobes
can sit at different points in the 400-clock output period, so the first
whole frame captured may differ by an output or two; each capture must match
exactly at one frame shift of at most two.
"""

import sys

import numpy as np

CAPTURES = 2
SHIFTS = (0, 1, -1, 2, -2)


def main(ref_tag, tag):
    failed = False
    for k in range(CAPTURES):
        ref = np.load(f"xbuild_{ref_tag}_capture{k}.npy")
        new = np.load(f"xbuild_{tag}_capture{k}.npy")
        n = min(len(ref), len(new)) - 4
        for shift in SHIFTS:
            a = ref[2 + shift:2 + shift + n]
            b = new[2:2 + n]
            if np.array_equal(a, b):
                print(f"capture {k}: {n} frames x {a.shape[1]} channels "
                      f"bit-identical (frame shift {shift:+d})")
                break
        else:
            failed = True
            a, b = ref[2:2 + n], new[2:2 + n]
            per_channel = np.sum(np.any(a != b, axis=2), axis=0)
            print(f"capture {k}: DIFFERS at every shift; frames differing "
                  f"per channel at shift 0: {per_channel.tolist()}")
    return 1 if failed else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
