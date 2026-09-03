"""Phase 22: analyze the broad-corpus eval (mission section 14, macro/micro
averages across document families -- not dominated by one SEC filing).

Reads eval/results/raw_broad_2048.jsonl: 19 documents, 431 questions,
5 arms (md, tdf_full, toon, json, tdf_nocaret0), 1 seed, budget=2048.
tdf_grouped and the other TDF ablation arms are deliberately excluded --
see the run's launch discussion for why (tdf_grouped is byte-identical to
tdf_full on every document except grouped_metrics, already tested
separately; the other ablations were already characterized on the
SEC-filing-dominated corpus in the v1/v2 reports and this run's budget
went to breadth instead).

Reports both a MICRO average (every question weighted equally -- what the
old SEC-filing-dominated corpus effectively was) and a MACRO average
(every document weighted equally, then averaged across documents) so one
large document can't dominate the headline number the way sec_filing did
in every prior report.

Run: .venv/bin/python eval/results/analyze_broad.py
"""

import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PATH = ROOT / "eval/results/raw_broad_2048_combined.jsonl"


def load() -> list[dict]:
    return [json.loads(l) for l in PATH.open() if l.strip()]


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
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot)]


def main():
    rows = load()
    if not rows:
        print(f"No data yet at {PATH} -- run still in progress?")
        return

    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)
    arms = sorted(by_arm)

    print("=" * 100)
    print(f"BROAD CORPUS EVAL -- {len(rows)} rows, {len({r['doc_id'] for r in rows})} documents, "
          f"budget=2048")
    print("=" * 100)

    print("\n-- MICRO average (every question weighted equally) --")
    for arm in arms:
        rs = by_arm[arm]
        acc = sum(r["correct"] for r in rs) / len(rs)
        avg_tok = sum(r["prompt_tokens"] for r in rs) / len(rs)
        print(f"  {arm:<16} n={len(rs):<5} acc={acc*100:5.1f}%  avg_prompt_tokens={avg_tok:.0f}")

    print("\n-- MACRO average (per-document accuracy, then averaged across documents) --")
    for arm in arms:
        rs = by_arm[arm]
        by_doc = defaultdict(list)
        for r in rs:
            by_doc[r["doc_id"]].append(r["correct"])
        doc_accs = [sum(v) / len(v) for v in by_doc.values()]
        macro = sum(doc_accs) / len(doc_accs)
        print(f"  {arm:<16} docs={len(doc_accs):<3} macro_acc={macro*100:5.1f}%")

    print("\n-- Per-document question count (checking no single doc dominates) --")
    doc_counts = defaultdict(int)
    for r in by_arm.get("md", rows):
        doc_counts[r["doc_id"]] += 1
    total = sum(doc_counts.values())
    for doc_id, n in sorted(doc_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {doc_id:<22} {n:<4} ({100*n/total:.1f}% of questions)")

    print("\n-- Paired diff vs md (micro, pp), 95% bootstrap CI --")
    md_by_key = {(r["doc_id"], r["question_id"], r["seed"]): r for r in by_arm.get("md", [])}
    for arm in arms:
        if arm == "md":
            continue
        diffs = []
        for r in by_arm[arm]:
            key = (r["doc_id"], r["question_id"], r["seed"])
            md_r = md_by_key.get(key)
            if md_r is None:
                continue
            diffs.append(int(r["correct"]) - int(md_r["correct"]))
        if diffs:
            mean_diff = sum(diffs) / len(diffs) * 100
            lo, hi = bootstrap_ci(diffs)
            print(f"  {arm:<16} n={len(diffs):<5} {mean_diff:+6.1f}pp  "
                  f"CI[{lo*100:+6.1f}, {hi*100:+6.1f}]")

    print("\n-- Accuracy by document family --")
    FAMILY = {
        "co2_data": "legacy", "k8s_deployment": "legacy", "sec_filing": "legacy",
        "operating_review": "legacy", "sales_report": "legacy",
        "k8s_services": "kubernetes_docs", "k8s_configmap": "kubernetes_docs",
        "rfc2616_http": "rfc_technical", "rfc1035_dns": "rfc_technical",
        "alice_prose": "prose_books", "frankenstein_prose": "prose_books",
        "pride_prose": "prose_books",
        "readme_requests": "md_readmes", "readme_fastapi": "md_readmes",
        "access_log": "logs_synthetic",
        "code_doc_dataclasses": "code_documentation", "code_doc_decimal": "code_documentation",
        "github_terms": "legal_policy", "grouped_metrics": "grouped_metrics",
    }
    for arm in arms:
        by_fam = defaultdict(list)
        for r in by_arm[arm]:
            by_fam[FAMILY.get(r["doc_id"], "?")].append(r["correct"])
        print(f"  {arm}:")
        for fam, vals in sorted(by_fam.items()):
            print(f"    {fam:<20} n={len(vals):<4} acc={100*sum(vals)/len(vals):5.1f}%")


if __name__ == "__main__":
    main()
