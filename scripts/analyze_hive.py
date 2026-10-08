#!/usr/bin/env python
"""Summarise hive runs (protocol 'hive'): how much each sharing mode lets the agents know.

    python scripts/analyze_hive.py results/hive [more dirs...] [--curve]

Per variant (mode-nN[-fF]), at the last wave: laws an average agent can use (its view), laws in the
global seed, laws the hive saw at all (collective), wrong laws, messages; then how a newcomer does
with the shared memory on held-out test worlds. --curve adds known laws per wave.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load(paths, name):
    rows = []
    for p in paths:
        for f in Path(p).rglob(name):
            rows += [json.loads(x) for x in f.open() if x.strip()]
    return rows


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--curve", action="store_true")
    a = ap.parse_args()
    waves = load(a.paths, "hive.jsonl")
    eps = [r for r in load(a.paths, "episodes.jsonl") if r.get("protocol") == "hive"]
    if not waves:
        print("no hive rows")
        return
    def key_of(r):
        fm = r.get("faulty_mode", "scattered") if r["faulty"] else ""
        sh = f"w{r['shift_wave']}x{r['shift_share']:g}" if r.get("shift_wave") else ""
        return (r["env"], r["hive_mode"], r["hive_n"], r["faulty"], fm, sh)

    by = defaultdict(list)
    for r in waves:
        by[key_of(r)].append(r)
    test = defaultdict(list)
    for r in eps:
        if r["phase"] == "test":
            test[key_of(r)].append(r)
    hdr = ["env", "mode", "agents", "faulty", "lies", "shift", "waves", "laws", "known/agent", "wrong/agent",
           "known global", "wrong global", "merged raw", "messages", "redundant", "audits", "distrusted",
           "test success", "test board"]
    print("| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    order = ["isolated", "serial", "groups", "hive", "sync", "hive_verified", "hive_directed", "hive_full",
             "hive_audit", "hive_provenance", "hive_recent"]

    def sort_key(k):
        return (k[0], k[5], k[4], k[3], order.index(k[1]) if k[1] in order else 99, k[2])

    for key in sorted(by, key=sort_key):
        rs = by[key]
        last = max(r["wave"] for r in rs)
        fin = [r for r in rs if r["wave"] == last]
        t = test.get(key, [])
        board = [r["board_done"] / r["board_total"] for r in t if r.get("board_total")]
        print(f"| {key[0]} | {key[1]} | {key[2]} | {key[3]:g} | {key[4] or '-'} | {key[5] or '-'} | {last} | "
              f"{fin[0]['total_laws']} | "
              f"{mean(r['known_agents'] for r in fin):.1f} | {mean(r['wrong_agents'] for r in fin):.1f} | "
              f"{mean(r['known_global'] for r in fin):.1f} | {mean(r['wrong_global'] for r in fin):.1f} | "
              f"{mean(r['known_collective'] for r in fin):.1f} | {mean(r['messages'] for r in fin):.0f} | "
              f"{mean(r.get('redundant_share', float('nan')) for r in rs):.2f} | "
              f"{mean(r.get('audits', 0) for r in fin):.0f} | {mean(r.get('distrusted', 0) for r in fin):.0f} | "
              f"{mean(bool(r['success']) for r in t):.2f} | {mean(board):.2f} |")
    shifted = [k for k in by if k[5]]
    if shifted:
        print("\nFrom the law shift on, per wave: stale laws in the global seed / in a moved agent's view "
              "(changed laws still believed at their old value), laws the global seed gets right now (for a regional "
              "hive: the seed of agent 0's region), and with two regions what moved and staying agents know "
              "right and wrong about their own region:")
        for key in sorted(shifted, key=sort_key):
            per = defaultdict(list)
            for r in by[key]:
                per[r["wave"]].append(r)
            ws = sorted(per)
            print(f"  {key[1]:16s} n={key[2]:<3} shift {key[5]} (changed {max(x.get('changed_laws', 0) for x in by[key])}):")
            cols = [("stale global", "stale_global"), ("stale agent", "stale_agents"),
                    ("right global", "known_global_now")]
            if any("right_moved" in x for x in by[key]):  # two regions: each agent against its own region
                cols += [("right moved", "right_moved"), ("wrong moved", "wrong_moved"),
                         ("right stay", "right_stay"), ("wrong stay", "wrong_stay"), ("split laws", "split_laws")]
            for name, col in cols:
                cells = [mean(x[col] for x in per[w] if col in x) for w in ws]
                print(f"    {name:12s} " + " ".join("    -" if c != c else f"{c:5.1f}" for c in cells))
    if a.curve:
        print("\nLaws an average agent knows, per wave:")
        for key in sorted(by, key=sort_key):
            per = defaultdict(list)
            for r in by[key]:
                per[r["wave"]].append(r["known_agents"])
            print(f"  {key[1]:14s} n={key[2]:<4} f={key[3]:g}: " + " ".join(f"{mean(per[w]):5.1f}" for w in sorted(per)))


if __name__ == "__main__":
    main()
