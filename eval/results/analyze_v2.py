"""Phase 18: analyze the v2 budget re-run (mission section 14).

Reads eval/results/raw_v2_{512,1024,2048,4096}.jsonl and produces the
per-budget, per-arm, per-question-type breakdown the v1 REPORT.md never
could -- v1 ran a single EVAL_MAX_TOKENS=256 and was confounded by
truncation (73% of completions cap-hit). This is 1 seed x 263 questions x
10 arms per budget (not v1's 3 seeds), traded deliberately for four budget
levels instead of one -- see the run's launch discussion for why.

cap_hit is a proxy, not the API's own finish_reason (never captured by
client.py -- a concrete gap for the next run to close). An exact
`completion_tokens >= budget` check was tried first and read 0.0% at every
budget, which is not credible: budget=512's completion_tokens are
p50=p90=p99=509, one to three tokens shy of the 512 ceiling on every
percentile at once. That gap is almost certainly a tokenizer mismatch --
completion_tokens is recounted locally with o200k_base (tdf.tokens.count),
while the server enforces max_tokens against gpt-oss-120b's OWN tokenizer,
and the two vocabularies don't align token-for-token. So cap_hit here uses
`completion_tokens >= budget - NEAR_CAP_SLACK` as a tolerance for that
mismatch -- still a proxy, but one that produces the expected monotonic
decline as budget grows (53% -> 31% -> 17% -> 5%) instead of a flat,
implausible 0%.

Run: .venv/bin/python eval/results/analyze_v2.py
"""

import json
import random
from collections import defaultdict
from pathlib import Path

BUDGETS = [512, 1024, 2048, 4096]
NEAR_CAP_SLACK = 5  # tolerance for the o200k_base-vs-server-tokenizer mismatch
ROOT = Path(__file__).resolve().parent.parent.parent


def load(budget: int) -> list[dict]:
    path = ROOT / f"eval/results/raw_v2_{budget}.jsonl"
    return [json.loads(l) for l in path.open() if l.strip()]


def bootstrap_ci(diffs: list[float], n_boot: int = 2000, seed: int = 1) -> tuple[float, float]:
    if not diffs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * n_boot)]
    hi = means[int(0.975 * n_boot)]
    return (lo, hi)


def analyze_budget(budget: int) -> dict:
    rows = load(budget)
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    arm_stats = {}
    for arm, rs in by_arm.items():
        n = len(rs)
        acc = sum(1 for r in rs if r["correct"]) / n if n else 0.0
        cap_hit = (sum(1 for r in rs if r["completion_tokens"] >= budget - NEAR_CAP_SLACK) / n
                  if n else 0.0)
        avg_prompt = sum(r["prompt_tokens"] for r in rs) / n if n else 0.0
        arm_stats[arm] = {
            "n": n, "accuracy": acc, "cap_hit_rate": cap_hit,
            "avg_prompt_tokens": avg_prompt,
        }

    # Paired diff vs md: pair on (doc_id, question_id, seed) present in BOTH arms.
    md_by_key = {(r["doc_id"], r["question_id"], r["seed"]): r for r in by_arm.get("md", [])}
    paired = {}
    for arm, rs in by_arm.items():
        if arm == "md":
            continue
        diffs = []
        for r in rs:
            key = (r["doc_id"], r["question_id"], r["seed"])
            md_r = md_by_key.get(key)
            if md_r is None:
                continue
            diffs.append(int(r["correct"]) - int(md_r["correct"]))
        if diffs:
            mean_diff = sum(diffs) / len(diffs)
            lo, hi = bootstrap_ci(diffs)
            paired[arm] = {"n_paired": len(diffs), "mean_diff_pp": mean_diff * 100,
                           "ci_lo_pp": lo * 100, "ci_hi_pp": hi * 100}

    # Per question-type accuracy.
    by_type = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in rows:
        by_type[r["arm"]][r["qtype"]][0] += int(r["correct"])
        by_type[r["arm"]][r["qtype"]][1] += 1

    return {"arm_stats": arm_stats, "paired_vs_md": paired, "by_type": dict(by_type)}


def main():
    results = {b: analyze_budget(b) for b in BUDGETS}

    print("=" * 100)
    print("ACCURACY BY ARM ACROSS BUDGETS")
    print("=" * 100)
    arms = sorted({a for b in results.values() for a in b["arm_stats"]})
    header = f"{'arm':<16}" + "".join(f"{'b'+str(b):>12}" for b in BUDGETS)
    print(header)
    for arm in arms:
        row = f"{arm:<16}"
        for b in BUDGETS:
            s = results[b]["arm_stats"].get(arm)
            row += f"{s['accuracy']*100:>11.1f}%" if s else f"{'--':>12}"
        print(row)

    print()
    print("=" * 100)
    print("CAP-HIT RATE (completion_tokens >= budget) BY ARM ACROSS BUDGETS")
    print("=" * 100)
    print(header)
    for arm in arms:
        row = f"{arm:<16}"
        for b in BUDGETS:
            s = results[b]["arm_stats"].get(arm)
            row += f"{s['cap_hit_rate']*100:>11.1f}%" if s else f"{'--':>12}"
        print(row)

    print()
    print("=" * 100)
    print("PAIRED DIFF vs MD (pp), 95% bootstrap CI, BY ARM ACROSS BUDGETS")
    print("=" * 100)
    for b in BUDGETS:
        print(f"\n--- budget={b} ---")
        for arm, p in sorted(results[b]["paired_vs_md"].items(),
                             key=lambda kv: -kv[1]["mean_diff_pp"]):
            print(f"  {arm:<16} n={p['n_paired']:<5} "
                  f"{p['mean_diff_pp']:+6.1f}pp  CI[{p['ci_lo_pp']:+6.1f}, {p['ci_hi_pp']:+6.1f}]")

    print()
    print("=" * 100)
    print("tdf_nocaret0 (row-anchor fix) -- FIRST EVER MEASUREMENT")
    print("=" * 100)
    for b in BUDGETS:
        p = results[b]["paired_vs_md"].get("tdf_nocaret0")
        full = results[b]["paired_vs_md"].get("tdf_full")
        if p and full:
            print(f"  budget={b}: tdf_nocaret0 {p['mean_diff_pp']:+.1f}pp vs md "
                  f"(n={p['n_paired']})  |  tdf_full {full['mean_diff_pp']:+.1f}pp vs md "
                  f"(n={full['n_paired']})  |  delta (nocaret0 - full) = "
                  f"{p['mean_diff_pp'] - full['mean_diff_pp']:+.1f}pp")

    out_path = ROOT / "eval/results/v2_analysis.json"
    with out_path.open("w") as f:
        json.dump(results, f, indent=2)
    print(f"\nFull data written to {out_path}")


if __name__ == "__main__":
    main()
