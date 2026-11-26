"""Plot the 75.12 vs 75.13 receiver sweeps (poke_rx.py --sweep logs) against design.

  python plot_sweep.py sweep_75.12_m30.log sweep_75.13_m30.log

Writes sweep_rejection.png (0-310 kHz, alias rejection) and sweep_passband.png
(0-100 kHz, flatness).
"""
import os
import re
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import poke_rx  # noqa: E402

SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, FLOOR = "#2a78d6", "#eb6834", "#d9d8d3"


def parse(path):
    rows, refs = [], []
    for line in open(path):
        m = re.match(r"\s+([\d.]+)\s+([+-][\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*$", line)
        if m:
            rows.append(tuple(float(v) for v in m.groups()))
        m = re.search(r"reference (-?[\d.]+) dBFS", line)
        if m:
            refs.append(float(m.group(1)))
    a = np.array(rows)
    return {"off": a[:, 0], "meas": a[:, 2], "floor_bin": a[:, 4], "ref": refs}


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def main(old_log, new_log):
    old, new = parse(old_log), parse(new_log)
    f = np.linspace(1e3, 310e3, 3000)
    d_old = np.array([poke_rx.design_response_db(x, "cicrx") for x in f]) - poke_rx.design_response_db(10e3, "cicrx")
    d_new = np.array([poke_rx.design_response_db(x, "cicfir") for x in f]) - poke_rx.design_response_db(10e3, "cicfir")
    # A level read as the 7-bin sum of noise: what the measurement shows when the carrier is gone.
    limit = max(np.median(old["floor_bin"]), np.median(new["floor_bin"])) + 10 * np.log10(7)

    plt.rcParams["font.family"] = "DejaVu Sans"

    # ---- 1: rejection
    fig, ax = plt.subplots(figsize=(10, 5.6), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    ax.axhspan(-130, limit, color=FLOOR, alpha=0.5, linewidth=0)
    ax.text(305, -122, f"Shaded: below this setup's measurement limit (about {limit:.0f} dBc)",
            ha="right", va="bottom", color=INK2, fontsize=9,
            bbox=dict(facecolor=SURFACE, edgecolor="none", pad=2))
    ax.axvspan(0, 75, color=BLUE, alpha=0.06, linewidth=0)
    ax.text(37.5, 3, "75.13 clean band\n0-75 kHz", ha="center", va="bottom", color=INK2, fontsize=9)
    ax.axvline(96, color=INK2, linewidth=1, linestyle=(0, (3, 3)))
    ax.text(97.5, 9, "96 kHz: past here a signal\nfolds back into the band", color=INK2, fontsize=8.5, va="top")
    ax.annotate("75.13: this lobe folds to 78-96 kHz\nfrom centre, outside its clean band", (283, -53), (205, -42),
                color=INK2, fontsize=8.5, arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.8))

    ax.plot(f / 1e3, d_old, color=ORANGE, linewidth=2, label="75.12 design (CIC only)")
    ax.plot(f / 1e3, d_new, color=BLUE, linewidth=2, label="75.13 design (CIC + FIR)")
    keep_o, keep_n = old["off"] <= 310, new["off"] <= 310
    ax.plot(old["off"][keep_o], old["meas"][keep_o], "o", color=ORANGE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2, label="75.12 measured")
    ax.plot(new["off"][keep_n], new["meas"][keep_n], "s", color=BLUE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2, label="75.13 measured")

    ax.set_xlim(0, 310)
    ax.set_ylim(-125, 12)
    ax.set_xlabel("Carrier offset from receiver centre (kHz)", color=INK, fontsize=11)
    ax.set_ylabel("Level relative to a carrier at +10 kHz (dBc)", color=INK, fontsize=11)
    ax.set_title("HL2 12-receiver gateware: response and alias rejection at 192 ksps",
                 color=INK, fontsize=13, loc="left", pad=26)
    ax.text(0, 1.025, "TinySA carrier, 18.13 MHz at -30 dBm, LNA +20 dB; each point is one receiver. "
            "Lines are calculated from the gateware filters.",
            transform=ax.transAxes, color=INK2, fontsize=9)
    leg = ax.legend(loc="upper right", frameon=True, fontsize=9.5)
    leg.get_frame().set_facecolor(SURFACE)
    leg.get_frame().set_edgecolor(GRID)
    fig.tight_layout()
    fig.savefig("sweep_rejection.png", facecolor=SURFACE)
    plt.close(fig)

    # ---- 2: passband
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    style(ax)
    fp = f <= 100e3
    ax.plot(f[fp] / 1e3, d_old[fp], color=ORANGE, linewidth=2, label="75.12 design")
    ax.plot(f[fp] / 1e3, d_new[fp], color=BLUE, linewidth=2, label="75.13 design")
    po, pn = old["off"] <= 100, new["off"] <= 100
    ax.plot(old["off"][po], old["meas"][po], "o", color=ORANGE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2, label="75.12 measured")
    ax.plot(new["off"][pn], new["meas"][pn], "s", color=BLUE, markersize=8,
            markeredgecolor=SURFACE, markeredgewidth=2, label="75.13 measured")
    i75o = int(np.argmin(np.abs(old["off"] - 75)))
    i75n = int(np.argmin(np.abs(new["off"] - 75)))
    ax.annotate(f"{new['meas'][i75n]:.1f} dB at 75 kHz", (75, new["meas"][i75n]), (58, -3.2),
                color=INK, fontsize=9.5, arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.8))
    ax.annotate(f"{old['meas'][i75o]:.1f} dB at 75 kHz", (75, old["meas"][i75o]), (48, -12.5),
                color=INK, fontsize=9.5, arrowprops=dict(arrowstyle="-", color=INK2, linewidth=0.8))
    ax.set_xlim(0, 100)
    ax.set_ylim(-20, 1.5)
    ax.set_xlabel("Carrier offset from receiver centre (kHz)", color=INK, fontsize=11)
    ax.set_ylabel("Level relative to +10 kHz (dB)", color=INK, fontsize=11)
    ax.set_title("HL2 12-receiver gateware: passband flatness",
                 color=INK, fontsize=13, loc="left", pad=26)
    ax.text(0, 1.025, "Same sweep, first 100 kHz. The 100 kHz point is already an alias: "
            "it appears at -92 kHz.",
            transform=ax.transAxes, color=INK2, fontsize=9)
    leg = ax.legend(loc="lower left", frameon=True, fontsize=9.5)
    leg.get_frame().set_facecolor(SURFACE)
    leg.get_frame().set_edgecolor(GRID)
    fig.tight_layout()
    fig.savefig("sweep_passband.png", facecolor=SURFACE)
    plt.close(fig)
    print(f"measurement limit {limit:.1f} dBc; references {old['ref']} / {new['ref']}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
