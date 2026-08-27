"""Phase 6: expand the eval corpus family-by-family.

- Fetches new remote documents from sources.FAMILIES into
  eval/corpus/raw/<family>/<filename> (skips ids already in the manifest --
  existing perturbed pkls are NEVER regenerated, preserving the v1 benchmark
  inputs per mission section 29).
- Synthesises offline families (logs, code documentation) deterministically.
- Merges into eval/corpus/manifest.json (append-only; prefix order of the
  original five entries is preserved so perturb.py's seeded RNG stream stays
  identical for them).
- Prints a per-family coverage table.

Afterwards run `python -m eval.corpus.perturb` to fold new documents into
eval/corpus/perturbed/*.pkl for the runner.
"""

import hashlib
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval.corpus.sources import FAMILIES, SYNTHETIC_FAMILIES  # noqa: E402

MANIFEST = Path("eval/corpus/manifest.json")
RAW = Path("eval/corpus/raw")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fetch(entry: dict, family: str) -> dict | None:
    dest = RAW / family / entry["filename"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(entry["url"],
                                     headers={"User-Agent": "tdf-corpus/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
    except Exception as e:
        print(f"  SKIP {entry['id']}: {type(e).__name__}: {e}")
        return None
    return {
        "id": entry["id"], "family": family, "url": entry["url"],
        "filename": f"{family}/{entry['filename']}",
        "type": entry["filename"].rsplit(".", 1)[-1],
        "sha256": _sha(dest), "path": str(dest),
    }


def _synthesise_logs(family: str) -> list[dict]:
    """Deterministic nginx-like access log document."""
    out = []
    lines = []
    for i in range(400):
        code = (200, 200, 200, 301, 404, 500)[i % 6]
        lines.append(
            f'10.0.{i % 8}.{i % 250} - - [01/Jan/2026:{i % 24:02d}:00:00 +0000] '
            f'"GET /api/v{i % 3}/items/{i} HTTP/1.1" {code} {300 + i * 7} '
            f'"-" "tdf-synth/{i % 5}"'
        )
    text = "# synthetic access log\ntime_format: ISO-ish\n" + "\n".join(lines)
    dest = RAW / family / "access.log"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)
    out.append({"id": "access_log", "family": family,
                "url": "generate:logs", "filename": f"{family}/access.log",
                "type": "log", "sha256": _sha(dest), "path": str(dest)})
    return out


def _synthesise_code_docs(family: str) -> list[dict]:
    """Docstrings of a few stdlib modules as markdown (offline, stable)."""
    import inspect
    import dataclasses
    import decimal

    out = []
    for mod_name in ("dataclasses", "decimal"):
        mod = {"dataclasses": dataclasses, "decimal": decimal}[mod_name]
        lines = [f"# {mod_name}", "", f"Synthesised API doc for {mod.__name__}.", ""]
        names = sorted(n for n in dir(mod) if not n.startswith("_"))[:40]
        for n in names:
            obj = getattr(mod, n)
            doc = (inspect.getdoc(obj) or "").split("\n")[0]
            kind = type(obj).__name__
            lines += [f"## {n}", f"kind: {kind}", "", doc or "(no docstring)", ""]
        dest = RAW / family / f"{mod_name}_api.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines))
        out.append({"id": f"code_doc_{mod_name}", "family": family,
                    "url": f"generate:code_docs/{mod_name}",
                    "filename": f"{family}/{mod_name}_api.md",
                    "type": "md", "sha256": _sha(dest), "path": str(dest)})
    return out


def main() -> None:
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    have = {m["id"] for m in manifest}
    per_family: dict[str, int] = {}

    def register(entry: dict | None) -> None:
        if entry is None or entry["id"] in have:
            return
        manifest.append(entry)
        have.add(entry["id"])
        per_family[entry["family"]] = per_family.get(entry["family"], 0) + 1

    for family, entries in FAMILIES.items():
        print(f"[{family}]")
        for e in entries:
            if e["id"] in have:
                continue
            register(_fetch(e, family))

    if "logs_synthetic" in SYNTHETIC_FAMILIES and "access_log" not in have:
        for m in _synthesise_logs("logs_synthetic"):
            register(m)
    if "code_documentation" in SYNTHETIC_FAMILIES \
            and "code_doc_dataclasses" not in have:
        for m in _synthesise_code_docs("code_documentation"):
            register(m)

    MANIFEST.write_text(json.dumps(manifest, indent=2))

    fams = {}
    for m in manifest:
        fams.setdefault(m.get("family", "legacy"), 0)
        fams[m.get("family", "legacy")] += 1
    print("\nManifest coverage by family:")
    for f, n in sorted(fams.items()):
        print(f"  {f:20s} {n}")
    print(f"TOTAL documents: {len(manifest)} "
          f"(+{sum(per_family.values())} added this run)")


if __name__ == "__main__":
    main()