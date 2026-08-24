#!/usr/bin/env python3
"""Plot a CSV captured by read_imu.py.

    python plot_csv.py walk.csv
    python plot_csv.py walk.csv --save walk.png

Six raw channels against the device clock. Nothing is filtered or derived.
"""

from __future__ import annotations

import argparse
import csv
import sys


def load(path: str) -> dict[str, list[float]]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"{path} has no data rows")
    cols = {k: [] for k in rows[0]}
    for row in rows:
        for k, v in row.items():
            cols[k].append(float(v))
    return cols


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", help="CSV file written by read_imu.py")
    p.add_argument("--save", help="write the figure to this PNG instead of showing a window")
    args = p.parse_args()

    try:
        import matplotlib
    except ImportError:
        print("matplotlib is not installed:  pip install matplotlib", file=sys.stderr)
        return 1
    if args.save:
        matplotlib.use("Agg")  # must precede the pyplot import
    import matplotlib.pyplot as plt

    cols = load(args.csv)
    t0 = cols["t_ms"][0]
    t = [(v - t0) / 1000.0 for v in cols["t_ms"]]

    fig, (ax_a, ax_g) = plt.subplots(2, 1, sharex=True, figsize=(11, 6.5))
    for name, colour in (("ax_g", "#d62728"), ("ay_g", "#2ca02c"), ("az_g", "#1f77b4")):
        ax_a.plot(t, cols[name], colour, lw=0.9, label=name[:2].upper())
    ax_a.set_ylabel("accel (g)")
    ax_a.legend(loc="upper right", ncol=3, fontsize=8)
    ax_a.grid(alpha=0.25)

    for name, colour in (("gx_dps", "#d62728"), ("gy_dps", "#2ca02c"), ("gz_dps", "#1f77b4")):
        ax_g.plot(t, cols[name], colour, lw=0.9, label=name[:2].upper())
    ax_g.set_ylabel("gyro (deg/s)")
    ax_g.set_xlabel("time (s, device clock)")
    ax_g.legend(loc="upper right", ncol=3, fontsize=8)
    ax_g.grid(alpha=0.25)

    fig.suptitle(f"{args.csv} — {len(t)} samples, {t[-1]:.1f}s")
    fig.tight_layout()

    if args.save:
        fig.savefig(args.save, dpi=140)
        print(f"wrote {args.save}")
    else:
        plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
