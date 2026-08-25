"""Phase 12: encoding/decoding performance benchmarks.

Measures, per document size class (1 KB .. 100 MB):
  encode latency      render_tdf (optimized=True, codebooks)
  decode latency      parse_tdf
  markdown baseline   render_markdown
  throughput          bytes/sec and tokens/sec for each stage
  peak memory         tracemalloc during the heaviest stage

Synthetic documents scale a fixed structure (headings + paragraphs + a wide
repeating table) to the target byte size, so growth is attributable to size
alone rather than changing content mix. Results land in
reports/performance.json plus a stdout table.

Run: .venv/bin/python scripts/perf_benchmark.py [--max-kb 1024]
"""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path

sys_insert = None  # placeholder removed below


def _build_doc(target_bytes: int):
    """Deterministic document whose serialized Markdown is ~target_bytes."""
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tdf.ir import Doc, Heading, Para, Table

    doc = Doc(title="Perf Benchmark")

    # Measure a real sample row so table sizing tracks actual bytes.
    sample_cells = ["region0", "segment0", "1000.50", "5.5%", "note " + "x" * 10]
    row_bytes = len(("| " + " | ".join(sample_cells) + " |").encode()) + 1

    table_budget = int(target_bytes * 0.5)
    prose_budget = target_bytes - table_budget
    n_rows = max(2, table_budget // row_bytes)
    cols = ["region", "segment", "amount", "growth", "notes"]
    rows = [[f"region{i % 7}", f"segment{i % 4}",
             f"{1000 + i}.50", f"{(i * 37) % 90}.5%",
             "note " + "x" * 10] for i in range(n_rows)]

    # Prose: emit sections until the prose budget is spent.
    produced = 0
    s = 0
    while produced < prose_budget:
        doc.blocks.append(Heading(2, f"Section {s}: performance probe"))
        produced += len(f"## Section {s}: performance probe") + 1
        for p in range(3):
            words = " ".join(f"word{i % 97}" for i in range(60))
            text = f"[{s}.{p}] {words}."
            doc.blocks.append(Para(text))
            produced += len(text.encode()) + 1
        s += 1
        if s > 100_000:            # hard safety stop
            break

    doc.blocks.append(Table(cols=cols, rows=rows))
    return doc


def _timed(fn, *a, **k):
    t0 = time.perf_counter()
    result = fn(*a, **k)
    return result, time.perf_counter() - t0


def measure(target_bytes: int) -> dict:
    from copy import deepcopy

    from tdf.emit import render_markdown, render_tdf
    from tdf.columnar import encode_columns
    from tdf.parse import parse_tdf
    from tdf.tokens import count

    doc = _build_doc(target_bytes)

    md, t_md = _timed(render_markdown, deepcopy(doc))
    work = deepcopy(doc)
    books, t_books = _timed(encode_columns, work)
    wire, t_enc = _timed(render_tdf, work, legend=False, codebooks=books)
    parsed, t_dec = _timed(parse_tdf, wire)

    tok_wire = count(wire)

    tracemalloc.start()
    work2 = deepcopy(doc)
    books2 = encode_columns(work2)
    _, t_enc_mem = _timed(render_tdf, work2, legend=False, codebooks=books2)
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "target_bytes": target_bytes,
        "wire_bytes": len(wire.encode()),
        "tokens": tok_wire,
        "encode_seconds": round(t_enc + t_books, 4),
        "decode_seconds": round(t_dec, 4),
        "markdown_seconds": round(t_md, 4),
        "encode_bytes_per_sec": int(len(wire.encode()) / max(t_enc + t_books, 1e-9)),
        "decode_bytes_per_sec": int(len(wire.encode()) / max(t_dec, 1e-9)),
        "encode_tokens_per_sec": int(tok_wire / max(t_enc + t_books, 1e-9)),
        "peak_encode_memory_mb": round(peak / 1e6, 2),
        "blocks": len(doc.blocks),
    }


SIZES_KB = [1, 10, 100, 1024]          # 1 MB default ceiling; 10/100 MB opt-in


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-kb", type=int, default=1024,
                    help="largest size class to run (10=10MB, 102400=100MB)")
    ap.add_argument("--out", default="reports/performance.json")
    args = ap.parse_args()

    sizes = [kb for kb in SIZES_KB if kb <= args.max_kb]
    results = []
    print(f'{"size":>8s} {"blocks":>7s} {"enc_s":>8s} {"dec_s":>8s} '
          f'{"tok":>10s} {"enc_tok/s":>11s} {"peak_MB":>8s}')
    for kb in sizes:
        r = measure(kb * 1000)
        results.append(r)
        print(f'{kb:>7d}KB {r["blocks"]:7d} {r["encode_seconds"]:8.3f} '
              f'{r["decode_seconds"]:8.3f} {r["tokens"]:10,d} '
              f'{r["encode_tokens_per_sec"]:11,d} {r["peak_encode_memory_mb"]:8.1f}')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": results}, indent=1))
    print(f'\nwrote {args.out}')


if __name__ == "__main__":
    main()