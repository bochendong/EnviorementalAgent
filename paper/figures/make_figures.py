"""Figures for the paper draft. Numbers are copied from the audited run READMEs and
docs/netscale-report.md (gpt-6.1-sol, seeds 100-102). Run: python paper/figures/make_figures.py"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(__file__).parent
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e4e3dd"

plt.rcParams.update({
    "font.family": "serif", "font.size": 8, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "legend.frameon": False,
    "lines.linewidth": 1.5, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})

# Width 16, depth 4, grain 4.
N = [1, 2, 4, 8, 16, 32]
T_SEEDS = [[330, 330, 330], [199, 180, 185], [100, 99, 119], [62, 59, 72], [44, 58, 50], [39, 38, 37]]
T_LB = [325, 163, 82, 41, 25, 25]
T_REF = [325, 173, 93, 53, 33, 31]
# Width 16, depth 4, grain 1 (means only).
N_G1, T_G1, T_LB_G1 = [1, 2, 4, 8], [135, 83.7, 70.7, 33.7], [130, 65, 33, 17]


def mean(xs):
    return sum(xs) / len(xs)


def scaling():
    fig, (a, b) = plt.subplots(1, 2, figsize=(6.75, 2.2))
    t = [mean(s) for s in T_SEEDS]
    a.plot(N, T_LB, color=MUTED, ls="--", lw=1, label=r"lower bound $T_{lb}$")
    a.plot(N, T_REF, color=AQUA, marker="s", ms=4, label=r"scripted team $T_{ref}$")
    a.plot(N, t, color=BLUE, marker="o", ms=4, label="LLM team $T$")
    for n, s in zip(N, T_SEEDS):
        a.scatter([n] * 3, s, s=6, color=BLUE, alpha=0.35, lw=0, zorder=3)
    a.set_xscale("log", base=2)
    a.set_yscale("log", base=2)
    a.set_xticks(N, [str(n) for n in N])
    a.set_yticks([25, 50, 100, 200, 330], ["25", "50", "100", "200", "330"])
    a.set_xlabel("agents $N$")
    a.set_ylabel("lockstep rounds")
    a.set_title("(a) time to solve, grain 4", loc="left", fontsize=8)
    a.legend(loc="lower left", fontsize=7)

    b.plot(N, [lb / x for lb, x in zip(T_LB, t)], color=BLUE, marker="o", ms=4, label="grain 4")
    b.plot(N_G1, [lb / x for lb, x in zip(T_LB_G1, T_G1)], color=ORANGE, marker="^", ms=4, label="grain 1")
    b.set_xscale("log", base=2)
    b.set_xticks(N, [str(n) for n in N])
    b.set_ylim(0, 1.05)
    b.set_xlabel("agents $N$")
    b.set_ylabel(r"efficiency $b = T_{lb}/T$")
    b.set_title("(b) efficiency against the bound", loc="left", fontsize=8)
    b.legend(loc="lower left", fontsize=7)
    b.annotate("16 agents: one per task", xy=(16, 0.49), xytext=(3.2, 0.30), fontsize=7, color=MUTED,
               arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.6))
    fig.savefig(OUT / "scaling.pdf")


def losses():
    fig, (a, b) = plt.subplots(1, 2, figsize=(6.75, 2.2))
    n = [2, 4, 8, 16, 32]
    handoff = [4.3, 4.1, 5.0, 5.1, 2.7]
    a.bar(range(len(n)), handoff, width=0.6, color=[BLUE] * 4 + [ORANGE])
    a.axhspan(1.2, 1.6, color=AQUA, alpha=0.35, lw=0, zorder=3, label="scripted team (1.2-1.6)")
    a.legend(loc="upper left", fontsize=7)
    a.set_ylim(0, 6.2)
    a.set_xticks(range(len(n)), [str(x) for x in n])
    a.set_xlabel("agents $N$")
    a.set_ylabel("rounds lost per layer")
    a.set_title("(a) handoff loss, layers 1-3", loc="left", fontsize=8)
    a.text(4, 2.9, "two crews", ha="center", fontsize=7, color=INK)

    # (store reads by the join's solver, rounds the join lost), every grain-4 width-16 run with N >= 2.
    plain = [(0, 1), (0, 4), (0, 1), (0, 3), (0, 3), (0, 1), (0, 2), (0, 2), (0, 3),
             (0, 2), (15, 16), (6, 7), (0, 2), (0, 2), (0, 3)]
    cols = [(15, 16), (15, 16), (3, 4)]
    b.plot([0, 16], [1, 17], color=MUTED, ls="--", lw=1, label="1 + reads")
    b.scatter(*zip(*plain), s=14, color=BLUE, label="plain teams", zorder=3)
    b.scatter(*zip(*cols), s=18, marker="D", facecolor="none", edgecolor=ORANGE, lw=1,
              label="no second crew", zorder=4)
    b.set_xlabel("answers the join's solver read from the store")
    b.set_ylabel("rounds the join lost")
    b.set_title("(b) join loss", loc="left", fontsize=8)
    b.legend(loc="upper left", fontsize=7)
    fig.savefig(OUT / "losses.pdf")


def interventions():
    fig, (a, b) = plt.subplots(1, 2, figsize=(3.4, 1.9))
    seeds = ["100", "101", "102"]

    def paired(ax, left, right, labels, colors, ylabel, title):
        for l, r in zip(left, right):
            ax.plot([0, 1], [l, r], color=GRID, lw=1, zorder=1)
        ax.scatter([0] * 3, left, color=colors[0], s=16, zorder=3)
        ax.scatter([1] * 3, right, color=colors[1], s=16, zorder=3)
        ax.set_xticks([0, 1], labels)
        ax.set_xlim(-0.4, 1.4)
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left", fontsize=7)
        ax.tick_params(labelsize=6)

    paired(a, [3.3, 3.7, 3.3], [2.0, 2.3, 2.3], ["8 agents\none/task", "16 agents\ntwo/task"],
           [BLUE, ORANGE], "rounds lost per layer", "(a) width 8")
    paired(b, [3.0, 2.7, 2.3], [4.7, 4.7, 6.3], ["32 plain", "32 no\nsecond crew"],
           [ORANGE, BLUE], None, "(b) intervention")
    a.set_ylim(0, 7)
    b.set_ylim(0, 7)
    fig.savefig(OUT / "interventions.pdf")


if __name__ == "__main__":
    scaling()
    losses()
    interventions()
