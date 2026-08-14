"""Cross-format token benchmark.

Compares, for the same source file:
  * MarkItDown     - what people actually use today (Microsoft, 170k+ stars)
  * Markdown (IR)  - our own best-effort Markdown, same parse as TDF
  * HTML / JSON    - the other common ingestion encodings
  * TDF            - the token-dense format, with and without its legend
  * TDF skeleton   - outline-only, for load-on-demand retrieval

Reports token counts plus a semantic-fidelity recall score for TDF, because a
compression number without a fidelity number is meaningless.
"""

from __future__ import annotations

import copy
import json
import sys
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.columnar import encode_columns  # noqa: E402
from tdf.emit import render_markdown, render_skeleton, render_tdf  # noqa: E402
from tdf.fidelity import compare  # noqa: E402
from tdf.ir import Doc, Table  # noqa: E402
from tdf.parse import parse_tdf  # noqa: E402
from tdf.readers import read  # noqa: E402
from tdf.tokens import count  # noqa: E402

SAMPLES = ROOT / "samples"


def render_json(doc: Doc) -> str:
    """Row-of-objects JSON, the shape most extraction tools emit."""
    out = []
    for b in doc.blocks:
        if is_dataclass(b):
            d = asdict(b)
            d["type"] = type(b).__name__
            if isinstance(b, Table):
                d["rows"] = [dict(zip(b.cols, r)) for r in b.rows]
            out.append(d)
    return json.dumps({"title": doc.title, "blocks": out}, ensure_ascii=False)


def render_html(doc: Doc) -> str:
    from tdf.ir import Figure, Heading, KV, ListBlock, PageMark, Para, Quote

    out = [f"<h1>{doc.title}</h1>"] if doc.title else []
    for b in doc.blocks:
        if isinstance(b, Heading):
            out.append(f"<h{min(b.level,6)}>{b.text}</h{min(b.level,6)}>")
        elif isinstance(b, Para):
            out.append(f"<p>{b.text}</p>")
        elif isinstance(b, Quote):
            out.append(f"<blockquote>{b.text}</blockquote>")
        elif isinstance(b, ListBlock):
            tag = "ol" if b.ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{i}</li>" for i in b.items) + f"</{tag}>")
        elif isinstance(b, Table):
            head = "".join(f"<th>{c}</th>" for c in b.cols)
            body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                           for r in b.rows)
            out.append(f"<table><tr>{head}</tr>{body}</table>")
        elif isinstance(b, KV):
            out.append("<dl>" + "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in b.pairs) + "</dl>")
        elif isinstance(b, Figure):
            out.append(f'<img alt="{b.desc}">')
        elif isinstance(b, PageMark):
            out.append(f"<hr><!-- page {b.number} -->")
    return "".join(out)


def markitdown_tokens(path: Path):
    try:
        from markitdown import MarkItDown
    except ImportError:
        return None, None
    try:
        t0 = time.perf_counter()
        res = MarkItDown(enable_plugins=False).convert(str(path))
        return count(res.text_content), time.perf_counter() - t0
    except Exception:
        return None, None


def bench_one(path: Path) -> dict:
    t0 = time.perf_counter()
    doc = read(path)
    parse_s = time.perf_counter() - t0

    original = copy.deepcopy(doc)
    md = render_markdown(copy.deepcopy(doc))
    js = render_json(copy.deepcopy(doc))
    ht = render_html(copy.deepcopy(doc))
    sk = render_skeleton(copy.deepcopy(doc))

    # encode_columns() and render_tdf() must run on the *same* doc object --
    # codebooks computed from one copy don't correctly substitute into a
    # separate (structurally identical) deepcopy. This mirrors exactly what
    # `tdf convert` does by default (cli.py's cmd_convert).
    doc_tdf = copy.deepcopy(doc)
    books = encode_columns(doc_tdf)
    t1 = time.perf_counter()
    td = render_tdf(doc_tdf, legend=True, codebooks=books)
    tdf_s = time.perf_counter() - t1

    doc_tdf_nl = copy.deepcopy(doc)
    books_nl = encode_columns(doc_tdf_nl)
    td_nl = render_tdf(doc_tdf_nl, legend=False, codebooks=books_nl)

    mit, mit_s = markitdown_tokens(path)
    fid = compare(original, parse_tdf(td))

    toks = {
        "raw": None if path.suffix not in (".csv", ".tsv", ".txt") else count(path.read_text(errors="ignore")),
        "markitdown": mit,
        "html": count(ht),
        "json": count(js),
        "markdown": count(md),
        "tdf": count(td),
        "tdf_no_legend": count(td_nl),
        "tdf_skeleton": count(sk),
    }
    base = toks["markdown"]
    return {
        "file": path.name,
        "kb": round(path.stat().st_size / 1024, 1),
        "tokens": toks,
        "vs_markdown_pct": {
            k: (None if v is None else round(100 * (1 - v / base), 1))
            for k, v in toks.items()
        },
        "vs_markitdown_pct": (
            None if not mit else round(100 * (1 - toks["tdf"] / mit), 1)
        ),
        "fidelity_recall": round(fid["distinct_recall"] * 100, 2),
        "occurrence_ratio": round(fid.get("occurrence_ratio", 1.0) * 100, 2),
        "seconds": {"parse": round(parse_s, 3), "tdf_render": round(tdf_s, 3),
                    "markitdown": None if mit_s is None else round(mit_s, 3)},
    }


def fmt_table(results: list[dict]) -> str:
    cols = ["raw", "markitdown", "html", "json", "markdown", "tdf", "tdf_no_legend", "tdf_skeleton"]
    head = ("| file | " + " | ".join(cols) +
            " | TDF saving vs MD | TDF saving vs MarkItDown | recall | occurrence |")
    sep = "|" + "---|" * (len(cols) + 5)
    lines = [head, sep]
    for r in results:
        cells = []
        for c in cols:
            v = r["tokens"][c]
            cells.append("n/a" if v is None else f"{v:,}")
        lines.append(
            f"| {r['file']} | " + " | ".join(cells) +
            f" | **{r['vs_markdown_pct']['tdf']:.1f}%** | " +
            (f"**{r['vs_markitdown_pct']:.1f}%**" if r["vs_markitdown_pct"] is not None else "n/a") +
            f" | {r['fidelity_recall']:.1f}% | {r['occurrence_ratio']:.1f}% |"
        )

    tot = {c: sum(r["tokens"][c] or 0 for r in results) for c in cols}
    # Only compare against MarkItDown on the files it actually converted.
    mit_rows = [r for r in results if r["tokens"]["markitdown"] is not None]
    mit_tot = sum(r["tokens"]["markitdown"] for r in mit_rows)
    tdf_on_mit = sum(r["tokens"]["tdf"] for r in mit_rows)
    lines.append(
        "| **TOTAL** | " + " | ".join(f"**{tot[c]:,}**" for c in cols) +
        f" | **{100*(1-tot['tdf']/tot['markdown']):.1f}%** | " +
        (f"**{100*(1-tdf_on_mit/mit_tot):.1f}%**" if mit_tot else "n/a") +
        f" | {sum(r['fidelity_recall'] for r in results)/len(results):.1f}% | {sum(r['occurrence_ratio'] for r in results)/len(results):.1f}% |"
    )
    if len(mit_rows) != len(results):
        lines.append(f"\n_MarkItDown column totals cover only the {len(mit_rows)} of "
                     f"{len(results)} files it converted; the MarkItDown saving is computed "
                     f"on that same subset._")
    return "\n".join(lines)


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLES
    files = sorted(p for p in target.iterdir() if p.is_file() and not p.name.startswith("."))
    if not files:
        print(f"no files in {target}; run bench/make_samples.py first", file=sys.stderr)
        return 1

    results = []
    for p in files:
        print(f"  benchmarking {p.name} ...", file=sys.stderr)
        results.append(bench_one(p))

    table = fmt_table(results)
    print("\n" + table + "\n")

    tot_md = sum(r["tokens"]["markdown"] for r in results)
    tot_tdf = sum(r["tokens"]["tdf"] for r in results)
    tot_sk = sum(r["tokens"]["tdf_skeleton"] for r in results)
    summary = (
        f"\nTokens for the whole corpus: markdown {tot_md:,} -> tdf {tot_tdf:,} "
        f"({100*(1-tot_tdf/tot_md):.1f}% smaller). "
        f"Skeleton-only view: {tot_sk:,} tokens ({100*(1-tot_sk/tot_md):.1f}% smaller).\n"
    )
    print(summary)

    (ROOT / "bench" / f"results_{target.name}.json").write_text(json.dumps(results, indent=2))
    (ROOT / "bench" / f"results_{target.name}.md").write_text(
        f"# TDF benchmark - `{target.name}`\n\nTokenizer: `o200k_base` (GPT-4o/5 family) "
        "via tiktoken.\nAll rows are produced from the same parse, so differences are "
        "attributable\nto the output format alone. `recall` is distinct-content recall after "
        "a\nTDF -> IR round trip: 100% means no meaning-bearing term was lost.\n\n"
        + table + "\n" + summary
    )
    print(f"wrote bench/results_{target.name}.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
