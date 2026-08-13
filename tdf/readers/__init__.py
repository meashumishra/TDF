"""Format dispatch."""

from __future__ import annotations

from pathlib import Path

from ..ir import Doc

_MAP = {
    ".md": "markdown", ".markdown": "markdown", ".mdx": "markdown",
    ".htm": "html", ".html": "html", ".xhtml": "html",
    ".csv": "csv", ".tsv": "csv",
    ".txt": "text", ".log": "text", ".mmd": "text",
    ".docx": "docx", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pptx": "pptx",
    ".pdf": "pdf",
}

SUPPORTED = sorted(_MAP)


def read(path, **kw) -> Doc:
    p = Path(path)
    kind = _MAP.get(p.suffix.lower())
    if kind is None:
        raise ValueError(f"unsupported extension {p.suffix!r}; supported: {', '.join(SUPPORTED)}")

    if kind in ("markdown", "html", "csv", "text"):
        from . import text_formats as tf
        return {"markdown": tf.read_markdown, "html": tf.read_html,
                "csv": tf.read_csv, "text": tf.read_text}[kind](p)
    if kind in ("docx", "xlsx", "pptx"):
        from . import office
        return {"docx": office.read_docx, "xlsx": office.read_xlsx,
                "pptx": office.read_pptx}[kind](p)
    from .pdf import read_pdf
    return read_pdf(p, max_pages=kw.get("max_pages"))
