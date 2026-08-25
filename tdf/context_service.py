"""Lazy-context service: the logic behind the MCP server.

Every tool the server exposes is a thin wrapper over a function here, and
nothing in this module knows that MCP exists. That separation keeps the
interesting decisions -- what an agent sees first, what an expansion costs,
why ids are stable across calls -- testable without any SDK.

Design notes:

- **Two axes, one cache.** ``tier()`` mutates a Doc (replacing index-like
  regions with Elision markers) and returns {eid: original_text}; the skeleton
  is computed on the *untiered* document so section ids reflect the full
  structure. The cache therefore keeps both copies plus the store, keyed by
  path + mtime + size (+ max_pages), so repeated tool calls never re-parse a
  PDF and ids stay stable for the lifetime of the file version.
- **Every number is real.** Token counts come from tdf.tokens.count on the
  exact strings being compared -- the same accounting `tdf stats` prints --
  because an agent deciding "expand or not" needs costs it can trust.
- **Errors are data, not exceptions.** A wrong id returns {"error": ...,
  "available": [...]} so the model can self-correct in one turn instead of
  crashing the call.
"""

from __future__ import annotations

import copy
import re
from collections import OrderedDict
from pathlib import Path

from .columnar import encode_columns
from .diff import diff_docs
from .emit import extract_sections, render_markdown, render_skeleton, render_tdf
from .readers import read
from .tier import tier
from .tokens import count

# render_skeleton's output line format is the shipped, documented surface (the
# model reads these lines), so parsing IT -- rather than duplicating the walk
# in emit._section_ids -- keeps one source of truth for section numbering.
_SKELETON_LINE = re.compile(
    r"^(?P<id>\S+) (?P<title>.+?) p(?P<page>\d+) ~(?P<tok>\d+)(?: (?P<kinds>.*))?$"
)

_CACHE_MAX = 8


class _Entry:
    __slots__ = ("doc", "tiered", "store")

    def __init__(self, doc, tiered, store):
        self.doc = doc          # untiered original (sections, diffs)
        self.tiered = tiered    # tier() mutated copy (elision view)
        self.store = store      # {eid: verbatim text}


_cache: OrderedDict[str, _Entry] = OrderedDict()


def clear_cache() -> None:
    """Tests (and memory-conscious hosts) can drop all cached documents."""
    _cache.clear()


def _cache_key(path: Path, max_pages: int | None) -> str:
    try:
        st = path.stat()
        return f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}|{max_pages}"
    except OSError:
        return f"{path.resolve()}|uncached|{max_pages}"


def _entry(path: str | Path, max_pages: int | None) -> _Entry:
    p = Path(path)
    key = _cache_key(p, max_pages)
    hit = _cache.get(key)
    if hit is not None:
        _cache.move_to_end(key)
        return hit

    doc = read(str(p), max_pages=max_pages)
    original = copy.deepcopy(doc)
    store = tier(doc)  # mutates `doc` into the tiered form; ids x1..xN
    entry = _Entry(original, doc, store)

    _cache[key] = entry
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return entry


def _elisions(tiered_doc) -> list[dict]:
    from .ir import Elision  # local import keeps ir dependency-free

    return [
        {"id": b.eid, "kind": b.kind, "tokens": b.tokens,
         "items": b.items, "gist": b.gist}
        for b in tiered_doc.blocks if isinstance(b, Elision)
    ]


def open_document(path: str | Path, max_pages: int | None = None) -> dict:
    """The first call an agent should make: navigation + declared omissions +
    exact token economics for every view. Returns everything needed to decide
    what to fetch next."""
    e = _entry(path, max_pages)
    p = Path(path)

    md = render_markdown(copy.deepcopy(e.doc))
    skel = render_skeleton(copy.deepcopy(e.doc))

    # deepcopy before every optimized render: optimize() mutates blocks, and
    # these Docs share block objects with the cache (same trap cmd_stats
    # documents in cli.py).
    books_t = encode_columns(copy.deepcopy(e.tiered))
    tiered_txt = render_tdf(copy.deepcopy(e.tiered), legend=False, codebooks=books_t)
    books_f = encode_columns(copy.deepcopy(e.doc))
    full_txt = render_tdf(copy.deepcopy(e.doc), legend=False, codebooks=books_f)

    sections = []
    for line in skel.splitlines():
        m = _SKELETON_LINE.match(line.strip())
        if m:
            sections.append({"id": m["id"], "title": m["title"],
                             "page": int(m["page"]), "tokens": int(m["tok"]),
                             "kinds": m["kinds"] or ""})

    el = _elisions(e.tiered)
    manifest = ""
    if el:
        lines = ["", "# Elided regions -- index-like content declared, not pasted.",
                 "# Expand with expand_region(id); token counts below are exact."]
        lines += [f"!E {d['id']} {d['kind']} {d['tokens']} {d['items']} {d['gist']}"
                  for d in el]
        manifest = "\n".join(lines)

    return {
        "path": str(p),
        "title": e.doc.title or p.name,
        "view": skel + manifest,
        "sections": sections,
        "elisions": el,
        "tokens": {
            "markdown_full": count(md),
            "tdf_full_no_legend": count(full_txt),
            "tdf_tiered_no_legend": count(tiered_txt),
            "this_view": count(skel + manifest),
        },
    }


def expand_region(path: str | Path, region_id: str,
                  max_pages: int | None = None) -> dict:
    """Resolve one !E id to the verbatim text it stands for."""
    e = _entry(path, max_pages)
    text = e.store.get(region_id)
    if text is None:
        return {"error": f"no elided region {region_id!r}",
                "available": sorted(e.store)}
    return {"id": region_id, "tokens": count(text), "text": text}


def read_section(path: str | Path, section_ids: list[str],
                 max_pages: int | None = None) -> dict:
    """Expand chosen skeleton sections (an id also pulls its N.x children --
    extract_sections' own rule, so this matches `tdf expand`)."""
    e = _entry(path, max_pages)
    skel = render_skeleton(copy.deepcopy(e.doc))
    available = [m.group(1) for m in
                 (_SKELETON_LINE.match(l.strip()) for l in skel.splitlines())
                 if m]
    wanted = [s for s in section_ids if s in set(available)]
    if not wanted:
        return {"error": "no requested section ids exist",
                "available": available}

    sec_doc = extract_sections(copy.deepcopy(e.doc), wanted)
    books = encode_columns(copy.deepcopy(sec_doc))
    out = render_tdf(copy.deepcopy(sec_doc), legend=False, codebooks=books)
    return {"requested": wanted, "text": out, "tokens": count(out),
            "available_sections": available}


def diff_documents(old_path: str | Path, new_path: str | Path,
                   granularity: str = "block", context: int = 1,
                   summary_only: bool = False,
                   max_pages: int | None = None) -> dict:
    """Structural !DIFF between two versions -- the minimal-delta update that
    lets an agent revise its understanding without re-reading anything that
    did not change."""
    old_e = _entry(old_path, max_pages)
    new_e = _entry(new_path, max_pages)
    out = diff_docs(old_e.doc, new_e.doc, granularity=granularity,
                    context=context, summary_only=summary_only,
                    old_name=Path(old_path).name, new_name=Path(new_path).name)
    new_md = render_markdown(copy.deepcopy(new_e.doc))
    t_md = count(new_md)
    t_d = count(out)
    return {
        "diff": out,
        "tokens_diff": t_d,
        "tokens_new_document_markdown": t_md,
        "saved_pct": round(100 * (1 - t_d / t_md), 1) if t_md else 0.0,
    }