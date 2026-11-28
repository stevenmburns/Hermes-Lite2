"""Timing diagrams of the debouncers on hand-made key sequences.

  make traces                 # cocotb: writes traces_<dut>.json, one per design
  python plot_traces.py       # writes debounce_traces.png

Each panel is one scenario; every design's clean_pb is drawn under the same raw
pb, one sample per millisecond, as the RTL produced it. The grey band is the
keyed element. The note on each row gives press delay and width error (output
width minus keyed width), or what a key-up spike became.
"""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Fixed order and colour per design (categorical slots 1..6, never cycled).
DESIGNS = [
    ("committed", "committed debounce.v", "#2a78d6"),
    ("fixed", "comment's intent", "#eb6834"),
    ("cl", "confirm 2, lock out 6", "#1baf7a"),
    ("integ", "integrator 0..4", "#eda100"),
    ("hold_d2_c1", "equal delay, D=2", "#e87ba4"),
    ("hold_d4_c1", "equal delay, D=4", "#008300"),
]
PANELS = [
    ("clean", "Clean press and release"),
    ("press_bounce", "Press bounce"),
    ("release_bounce", "Release bounce"),
    ("spike", "1 ms spike, key up"),
    ("dropout", "1 ms dropout, key down"),
]
WIDE = ("dits_40wpm", "Three dits at 40 WPM (30 ms on, 30 ms off), 3 to 5 ms of bounce")
INK, MUTED, BAND, GRID = "#1f1f1e", "#6b6a64", "#e4e3de", "#efeee9"
HIGH = 0.62          # trace height in row units


def edges(trace):
    t = [0] + trace
    rises = [i - 1 for i in range(1, len(t)) if t[i] and not t[i - 1]]
    falls = [i - 1 for i in range(1, len(t)) if t[i - 1] and not t[i]]
    return rises, falls


def note(clean, keyed):
    rises, falls = edges(clean)
    if not keyed:
        if not rises:
            return "ignored"
        return " + ".join(f"{f - r} ms pulse" for r, f in zip(rises, falls))
    extra = len(rises) + len(falls) - 2 * len(keyed)
    if extra:
        return f"{extra} extra edges"
    d = [r - s for r, (s, _) in zip(rises, keyed)]
    w = [(f - r) - (e - s) for r, f, (s, e) in zip(rises, falls, keyed)]
    fmt = lambda v: (f"{min(v):+d}" if min(v) == max(v) else f"{min(v):+d}..{max(v):+d}")
    return f"{fmt(d).lstrip('+')} ms, {fmt(w)} ms"


NOTE_IN = 1.05       # width of the note column, inches


def panel(fig, ax, name, title, traces, labels):
    first = traces[DESIGNS[0][0]]["scenarios"][name]
    pb, keyed = first["pb"], first["keyed"]
    n = len(pb)
    ax_in = ax.get_position().width * fig.get_figwidth()
    extra = n * NOTE_IN / (ax_in - NOTE_IN)
    rows = [("pb (raw input)", pb, INK)] + [
        (lab, traces[key]["scenarios"][name]["clean"], col)
        for key, lab, col in DESIGNS]
    for s, e in keyed:
        ax.axvspan(s, e, color=BAND, lw=0, zorder=0)
    for k, (lab, tr, col) in enumerate(rows):
        y0 = len(rows) - 1 - k
        ax.hlines(y0, 0, n, color=GRID, lw=0.6, zorder=1)
        xs = list(range(n + 1))
        ys = [y0 + HIGH * v for v in tr] + [y0 + HIGH * tr[-1]]
        ax.step(xs, ys, where="post", color=col, lw=1.8 if k else 1.4,
                solid_joinstyle="miter", zorder=3)
        if k:
            text, colour = note(tr, keyed), INK
        else:
            text, colour = ("delay, width" if keyed else "comes out as"), MUTED
        ax.text(n + 0.12 * extra, y0 + HIGH / 2, text, ha="left", va="center",
                fontsize=7.5, color=colour, zorder=4,
                style="italic" if not k else "normal")
    ax.set_xlim(0, n + extra)
    ax.set_ylim(-0.25, len(rows) - 0.05)
    ax.set_yticks([len(rows) - 1 - k + HIGH / 2 for k in range(len(rows))])
    ax.set_yticklabels([r[0] for r in rows] if labels else [], fontsize=8.5,
                       color=INK)
    ax.tick_params(axis="y", length=0)
    step = 30 if n > 100 else 10
    ax.set_xticks(range(0, n + 1, step))
    ax.tick_params(axis="x", labelsize=7.5, colors=MUTED, length=2)
    ax.set_xlabel("ms", fontsize=7.5, color=MUTED, labelpad=1)
    ax.set_title(title, fontsize=9.5, color=INK, loc="left")
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#c9c8c1")
    ax.spines["bottom"].set_bounds(0, n)
    ax.xaxis.set_label_coords(n / (2 * (n + extra)), -0.07 if n < 100 else -0.06)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    traces = {}
    for key, _, _ in DESIGNS:
        path = os.path.join(here, f"traces_{key}.json")
        if not os.path.exists(path):
            sys.exit(f"missing {path}: run `make traces` first")
        traces[key] = json.load(open(path))
    fig = plt.figure(figsize=(17, 9.2))
    gs = fig.add_gridspec(2, len(PANELS), height_ratios=[1, 1], hspace=0.38,
                          wspace=0.06, left=0.105, right=0.995, top=0.9,
                          bottom=0.06)
    for i, (name, title) in enumerate(PANELS):
        panel(fig, fig.add_subplot(gs[0, i]), name, title, traces, labels=(i == 0))
    panel(fig, fig.add_subplot(gs[1, :]), WIDE[0], WIDE[1], traces, labels=True)
    fig.text(0.01, 0.965, "CW key debounce: RTL output on the same key sequences",
             fontsize=13, color=INK, weight="bold")
    fig.text(0.01, 0.935, "cocotb + Verilator, one sample per 1 ms msec_pulse. "
             "Grey band: the keyed element. Right of each trace: press delay and width error "
             "(output minus keyed). Equal delay uses CONFIRM=1.",
             fontsize=9, color=MUTED)
    out = os.path.join(here, "debounce_traces.png")
    fig.savefig(out, dpi=130, facecolor="white")
    print("wrote", out)


if __name__ == "__main__":
    main()
