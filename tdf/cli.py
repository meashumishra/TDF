"""tdf - convert documents into a token-dense, LLM-native representation."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from .emit import extract_sections, render_markdown, render_skeleton, render_tdf
from .fidelity import compare
from .parse import parse_tdf
from .readers import SUPPORTED, read
from .columnar import encode_columns
from .tier import restore, tier
from .tokens import count


def _load(path: str, max_pages: int | None):
    return read(path, max_pages=max_pages)


def cmd_convert(a) -> int:
    doc = _load(a.input, a.max_pages)
    if getattr(a, "tier", False):
        store = tier(doc)
        if store:
            print(f"tiered: {len(store)} index region(s) elided, "
                  f"{sum(count(v) for v in store.values()):,} tokens", file=sys.stderr)

    if a.to == "md":
        out = render_markdown(doc)
    elif a.to == "skeleton":
        out = render_skeleton(doc)
    elif a.to == "tdf":
        books = [] if a.raw else encode_columns(doc)
        out = render_tdf(
            doc, legend=not a.no_legend, optimized=not a.raw, codebooks=books
        )
    else:
        raise SystemExit(f"unknown target {a.to}")

    if a.output:
        Path(a.output).write_text(out, encoding="utf-8")
        print(f"wrote {a.output}  ({count(out)} tokens)", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


def cmd_stats(a) -> int:
    doc = _load(a.input, a.max_pages)
    md = render_markdown(copy.deepcopy(doc))
    skel = render_skeleton(copy.deepcopy(doc))
    tdf_nl = render_tdf(copy.deepcopy(doc), legend=False)
    tdf = render_tdf(copy.deepcopy(doc), legend=True)

    t_md, t_tdf, t_nl, t_sk = count(md), count(tdf), count(tdf_nl), count(skel)
    rows = [
        ("markdown (baseline)", t_md, 0.0),
        ("tdf (with legend)", t_tdf, 100 * (1 - t_tdf / t_md) if t_md else 0),
        ("tdf (no legend)", t_nl, 100 * (1 - t_nl / t_md) if t_md else 0),
        ("tdf skeleton only", t_sk, 100 * (1 - t_sk / t_md) if t_md else 0),
    ]
    if a.json:
        print(json.dumps({"input": a.input,
                          "tokens": {k: v for k, v, _ in rows},
                          "reduction_pct": {k: round(p, 1) for k, _, p in rows}}, indent=2))
    else:
        print(f"\n{Path(a.input).name}")
        print(f"{'format':24s} {'tokens':>9s} {'vs markdown':>12s}")
        print("-" * 48)
        for name, tok, pct in rows:
            delta = "" if name.startswith("markdown") else f"{-pct:+.1f}%"
            print(f"{name:24s} {tok:9,d} {delta:>12s}")
    return 0


def cmd_verify(a) -> int:
    doc = _load(a.input, a.max_pages)
    original = copy.deepcopy(doc)
    tdf = render_tdf(doc, legend=not a.no_legend)
    restored = parse_tdf(tdf)
    res = compare(original, restored)
    res["input"] = a.input
    res["tokens_tdf"] = count(tdf)
    res["tokens_markdown"] = count(render_markdown(copy.deepcopy(original)))
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"{Path(a.input).name}: distinct-content recall "
              f"{res['distinct_recall']*100:.2f}%  "
              f"({res['distinct_missing']}/{res['distinct_original']} terms missing)")
        if res["missing_sample"]:
            print("  missing sample:", ", ".join(res["missing_sample"]))
    return 0 if res["distinct_recall"] > 0.995 else 1


def cmd_validate(a) -> int:
    """Structural validation of a .tdf file: the OTSL principle applied.

    Checks the invariants the parser relies on (rectangular grids, declared
    row counts, one-line body text, idempotent re-emission) so a malformed
    document fails loudly here instead of silently degrading downstream.
    """
    from .validate import validate
    res = validate(Path(a.input).read_text())
    for vio in res.violations:
        where = f"line {vio.line}" if vio.line >= 0 else "document"
        print(f"{where}: [{vio.rule}] {vio.detail}")
    print(f"{Path(a.input).name}: {'valid' if res.ok else f'{len(res.violations)} violation(s)'}")
    return 0 if res.ok else 1


def cmd_expand_elided(a) -> int:
    """Resolve an !E marker back to the region it stands for."""
    doc = _load(a.input, a.max_pages)
    store = tier(doc)
    if a.eid not in store:
        print(f"no elided region {a.eid!r}; available: {', '.join(store) or 'none'}",
              file=sys.stderr)
        return 1
    text = store[a.eid]
    print(f"{a.eid}: {count(text):,} tokens", file=sys.stderr)
    sys.stdout.write(text + "\n")
    return 0


def cmd_expand(a) -> int:
    doc = _load(a.input, a.max_pages)
    sub = extract_sections(doc, a.sections)
    sys.stdout.write(render_tdf(sub, legend=not a.no_legend))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="tdf",
        description="Convert documents into a token-dense LLM-native format. "
                    f"Supported inputs: {', '.join(SUPPORTED)}",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("input")
        sp.add_argument("--max-pages", type=int, default=None,
                        help="limit PDF pages (useful for quick checks)")
        sp.add_argument("--tier", action="store_true",
                        help="elide index-like regions into addressable !E markers "
                             "(lossy but declared; resolve with expand-elided)")
        sp.add_argument("--no-legend", action="store_true",
                        help="omit the self-describing header")
        return sp

    c = common(sub.add_parser("convert", help="convert a document"))
    c.add_argument("--to", choices=["tdf", "md", "skeleton"], default="tdf")
    c.add_argument("-o", "--output")
    c.add_argument("--raw", action="store_true", help="skip reduction passes")
    c.set_defaults(func=cmd_convert)

    s = common(sub.add_parser("stats", help="token counts per format"))
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stats)

    v = common(sub.add_parser("verify", help="round-trip fidelity check"))
    v.add_argument("--json", action="store_true")
    v.set_defaults(func=cmd_verify)

    e = common(sub.add_parser("expand", help="emit only chosen skeleton sections"))
    e.add_argument("sections", nargs="+", help="section ids from `convert --to skeleton`")
    e.set_defaults(func=cmd_expand)

    x = common(sub.add_parser("expand-elided", help="resolve an !E region by id"))
    x.add_argument("eid", help="elision id, e.g. x1")
    x.set_defaults(func=cmd_expand_elided)

    vd = sub.add_parser("validate", help="check a .tdf file against the structural invariants")
    vd.add_argument("input")
    vd.set_defaults(func=cmd_validate)

    a = p.parse_args(argv)
    try:
        return a.func(a)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # A converter is pointed at untrusted files by definition, so a corrupt
        # or mislabelled document must produce a diagnosable message and a
        # non-zero status, never a traceback.
        print(f"tdf: cannot convert {a.input!r}: "
              f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
