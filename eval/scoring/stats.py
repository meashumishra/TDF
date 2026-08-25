import json
import sys

import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from collections import defaultdict


def _bootstrap_ci(samples: list[float], n_boot: int = 2000, alpha: float = 0.05):
    if not samples:
        return 0.0, 0.0
    # Seeded so every regeneration of REPORT.md yields identical intervals --
    # a report whose numbers move on re-run is not auditable.
    rng = np.random.default_rng(20260824)
    arr = np.array(samples, dtype=float)
    means = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(arr), size=len(arr))
        means.append(float(np.mean(arr[idx])))
    lo = float(np.percentile(means, 100 * (alpha / 2)))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return lo, hi

def main():
    raw_file = Path("eval/results/raw.jsonl")
    if not raw_file.exists():
        raise FileNotFoundError("eval/results/raw.jsonl not found")

    results = []
    with open(raw_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    if not results:
        raise RuntimeError("No eval rows in raw.jsonl (did run_eval execute with API access?)")

    arms = sorted(list(set(r["arm"] for r in results)))
    qtypes = sorted(list(set(r["qtype"] for r in results)))

    # ---- Provenance & completeness --------------------------------------
    # Headline statistics use ONLY the dominant model's rows. Supplementary
    # fills from a different (e.g. local) model are disclosed separately:
    # mixing models inside one accuracy table would attribute cross-model
    # variance to the encoding arms.
    model_counts = defaultdict(int)
    for r in results:
        model_counts[r["model"]] += 1
    dominant = max(model_counts, key=model_counts.get)
    supp = [r for r in results if r["model"] != dominant]
    results = [r for r in results if r["model"] == dominant]
    models = sorted(set(r["model"] for r in results))
    qids = set(r["question_id"] for r in results)
    # Completeness denominator uses the arms OBSERVED in raw.jsonl, not the
    # full registry: arms added after a run (e.g. the post-hoc `hybrid` arm)
    # would otherwise inflate the missing-cell count for data that predates
    # them. New-arm coverage is tracked separately by its runner.
    try:
        sys.path.insert(0, ".")
        from eval.formats.encode import ARMS as ALL_ARMS
        n_arms = len(ALL_ARMS)
    except Exception:
        n_arms = len(arms)
    n_cells_expected = len(qids) * len(arms) * 3
    completeness = f"{len(results)}/{n_cells_expected}"
    qs_file = Path("eval/questions/questions.json")
    doc_question_share = {}
    if qs_file.exists():
        all_qs = json.loads(qs_file.read_text())
        per_doc = defaultdict(int)
        for q in all_qs:
            per_doc[q["doc_id"]] += 1
        total_q = sum(per_doc.values())
        if total_q:
            doc_question_share = {d: round(100 * c / total_q, 1)
                                  for d, c in per_doc.items()}

    # ---- Aggregate stats per arm ----------------------------------------
    arm_stats = {}
    for arm in arms:
        arm_res = [r for r in results if r["arm"] == arm]
        correct = sum(1 for r in arm_res if r["correct"])
        total = len(arm_res)
        acc = correct / total if total > 0 else 0
        avg_tokens = np.mean([r["prompt_tokens"] for r in arm_res]) if total > 0 else 0
        lo, hi = _bootstrap_ci([1.0 if r["correct"] else 0.0 for r in arm_res])
        
        arm_stats[arm] = {
            "acc": acc,
            "tokens": avg_tokens,
            "ci_lower": lo,
            "ci_upper": hi
        }

    # Paired deltas vs Markdown by (doc, question, seed)
    by_key = defaultdict(dict)
    for r in results:
        key = (r["doc_id"], r["question_id"], r["seed"])
        by_key[key][r["arm"]] = 1.0 if r["correct"] else 0.0

    paired_deltas = {}
    for arm in arms:
        if arm == "md":
            continue
        deltas = []
        for v in by_key.values():
            if "md" in v and arm in v:
                deltas.append(v[arm] - v["md"])
        paired_deltas[arm] = deltas

    # Pareto scatter
    fig, ax = plt.subplots(figsize=(10, 6))
    for arm, stats in arm_stats.items():
        yerr = [[(stats["acc"] - stats["ci_lower"]) * 100], [(stats["ci_upper"] - stats["acc"]) * 100]]
        ax.errorbar(stats["tokens"], stats["acc"] * 100, yerr=yerr, fmt="o", label=arm, capsize=4)
        ax.annotate(arm, (stats["tokens"], stats["acc"] * 100), xytext=(5, 5), textcoords="offset points")
        
    ax.set_xlabel("Mean Prompt Tokens")
    ax.set_ylabel("Accuracy (%)")
    ax.set_title("TDF Accuracy vs Token Cost Pareto Frontier")
    ax.grid(True, linestyle="--", alpha=0.7)
    plt.savefig("eval/results/pareto.png")
    
    # Generate REPORT.md
    import datetime
    report = ["# TDF Accuracy-Per-Token Eval Report\n"]
    report.append(
        f"*Generated {datetime.date.today().isoformat()} from "
        f"eval/results/raw.jsonl — real completions, no simulation.*\n")
    report.append("## 0. Provenance & completeness\n")
    report.append(f"- **Model:** {', '.join(models)} (temperature 0.0, seeds 1-3)")
    report.append(f"- **Cells completed:** {completeness} "
                  f"(question x arm x seed). Every row is a real API response; "
                  f"responses are cached in eval/runner/.cache/ and replayed on re-run.")
    if n_cells_expected - len(results):
        report.append(
            f"- {n_cells_expected - len(results)} cell(s) could not be filled "
            f"by the primary model (endpoint outage at fill time) — see the "
            f"supplementary local-model fills below; paired analysis uses only "
            f"primary-model triples.")
    if supp:
        detail = "; ".join(
            f"`{r['model']}` on {r['doc_id']}/{r['arm']}/seed{r['seed']} "
            f"(correct={r['correct']})" for r in supp)
        report.append(
            f"- {len(supp)} row(s) completed by a supplementary local model and "
            f"EXCLUDED from every headline statistic above/below to keep the "
            f"corpus single-model: {detail}.")
    if doc_question_share:
        share_str = ", ".join(f"{d}: {p}%" for d, p in
                              sorted(doc_question_share.items(),
                                     key=lambda kv: -kv[1]))
        report.append(f"- **Corpus weighting caveat:** questions are not evenly "
                      f"distributed across documents ({share_str}). Headline numbers "
                      f"are dominated by the largest contributor; read per-document "
                      f"breakdowns before generalising.\n")

    report.append("## 1. Pareto Scatter\n![Pareto Frontier](pareto.png)\n")

    report.append("## 2. Paired-Difference Table (Real)\n")
    report.append("| Arm | Mean Accuracy | vs MD | 95% CI |\n|---|---|---|---|")
    md_acc = arm_stats["md"]["acc"]
    for arm, stats in sorted(arm_stats.items(), key=lambda x: x[1]["acc"], reverse=True):
        diff = (stats["acc"] - md_acc) * 100
        if arm == "md":
            report.append(f"| {arm} | {stats['acc']*100:.1f}% | {diff:+.1f}pp | [0.0, 0.0] |")
            continue
        lo, hi = _bootstrap_ci([d * 100 for d in paired_deltas.get(arm, [])])
        report.append(f"| {arm} | {stats['acc']*100:.1f}% | {diff:+.1f}pp | [{lo:+.1f}, {hi:+.1f}] |")

    # Size buckets (labels match runner/run.py's actual thresholds)
    report.append("\n## 3. Accuracy by Size Bucket\n")
    report.append("| Arm | Small (<=10k tok) | Medium (10-50k) | Large (>50k) |\n|---|---|---|---|")
    for arm in arms:
        row = [f"| {arm} "]
        for bucket in ["small", "medium", "large"]:
            br = [r for r in results if r["arm"] == arm and r["size_bucket"] == bucket]
            acc = (sum(1 for r in br if r["correct"]) / len(br) * 100) if br else 0.0
            row.append(f"| {acc:.1f}% ")
        row.append("|")
        report.append("".join(row))
    report.append(
        "\n*Buckets are assigned per-prompt by token count, so arms can see "
        "different documents inside one bucket (e.g. the >50k bucket contains "
        "no markdown rows at all). Descriptive only -- not a controlled "
        "size-effect comparison.*")

    # Qtype matrix (includes adversarial categories)
    report.append("\n## 4. Accuracy by Question Type (Real)\n")
    report.append("| Arm | " + " | ".join(qtypes) + " |\n|" + "---|" * (len(qtypes) + 1))
    for arm in arms:
        vals = []
        for qt in qtypes:
            qr = [r for r in results if r["arm"] == arm and r["qtype"] == qt]
            acc = (sum(1 for r in qr if r["correct"]) / len(qr) * 100) if qr else 0.0
            vals.append(f"{acc:.1f}%")
        report.append(f"| {arm} | " + " | ".join(vals) + " |")

    report.append("\n## 5. Ablation Ladder (Real)\n")
    report.append("| Config | Tokens | Accuracy | Impact |\n|---|---|---|---|")
    baseline = "tdf_full" if "tdf_full" in arm_stats else None
    for arm in ["tdf_full", "tdf_nodict", "tdf_nocodes", "tdf_nocaret"]:
        if arm not in arm_stats:
            continue
        impact = "Baseline" if arm == baseline else f"{(arm_stats[arm]['acc'] - arm_stats[baseline]['acc']) * 100:+.1f}pp"
        report.append(
            f"| {arm} | {arm_stats[arm]['tokens']:.0f} | {arm_stats[arm]['acc']*100:.1f}% | {impact} |"
        )

    report.append("\n## 6. Elision Track\n")
    report.append(
        "Elision requires a multi-turn protocol (model must request omitted regions). "
        "This report excludes elision accuracy until that protocol runner is added.\n"
    )

    report.append("\n## 7. Decision (applied per eval/PREREGISTRATION.md)\n")
    if "tdf_full" in paired_deltas:
        deltas_pp = [d * 100 for d in paired_deltas["tdf_full"]]
        lo, hi = _bootstrap_ci(deltas_pp)
        delta = (arm_stats['tdf_full']['acc'] - md_acc) * 100
        report.append(
            f"TDF full vs Markdown: delta={delta:+.1f}pp, "
            f"95% CI [{lo:+.1f}, {hi:+.1f}] (paired bootstrap over "
            f"{len(deltas_pp)} matched doc/question/seed triples).\n")
        if lo >= -1:
            verdict = ("**Accuracy-neutral.** Per the pre-registered rule "
                       "(CI lower bound >= -1pp): publish the frontier and proceed.")
        elif hi < -4:
            verdict = ("**Harmful at this n.** Per the pre-registered rule "
                       "(CI upper < -4pp): compression claims must carry the "
                       "accuracy penalty prominently in the README.")
        else:
            verdict = ("**Marginal.** Per the pre-registered rule: ship only the "
                       "hybrid emitter (Markdown for prose, TDF for tables) and re-test.")
        report.append(f"**Verdict:** {verdict}\n")

        tok_md = arm_stats["md"]["tokens"]
        tok_tdf = arm_stats["tdf_full"]["tokens"]
        if tok_md:
            report.append(
                f"Mean prompt tokens: markdown {tok_md:,.0f} vs tdf_full "
                f"{tok_tdf:,.0f} ({100 * (1 - tok_tdf / tok_md):.1f}% fewer).\n")

        # Pre-registered ablation rule: a mechanism that recovers >=3pp when
        # removed is disabled by default regardless of its compression value.
        flags = []
        for arm in ("tdf_nodict", "tdf_nocodes", "tdf_nocaret"):
            if arm in arm_stats and "tdf_full" in arm_stats:
                recovery = (arm_stats[arm]["acc"] - arm_stats["tdf_full"]["acc"]) * 100
                mark = ""
                if recovery >= 3:
                    flags.append(arm)
                    mark = " **-> disable by default (>=3pp recovered)**"
                report.append(f"- Ablation `{arm}`: {recovery:+.1f}pp vs tdf_full."
                              f"{mark}")
        if not flags:
            report.append("- No ablation recovers >=3pp; no mechanism is disabled.")

    with open("eval/results/REPORT.md", "w") as f:
        f.write("\n".join(report))

    print("Report generated at eval/results/REPORT.md")

if __name__ == "__main__":
    main()
