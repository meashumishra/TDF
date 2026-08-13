"""Intermediate representation shared by every reader and every emitter.

Keeping one IR is what makes the benchmark fair: Markdown and TDF are produced
from the *same* parse, so any token delta is attributable to the format alone
and not to a better or worse PDF parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class Para:
    text: str


@dataclass
class ListBlock:
    items: list[str]
    ordered: bool = False


@dataclass
class Table:
    cols: list[str]
    rows: list[list[str]]
    caption: str = ""
    group: str = ""

    def __post_init__(self) -> None:
        """Force a rectangular grid.

        Real documents (SEC filings especially) frequently have a short or empty
        header row with much wider data rows. Sizing the table by the header
        alone silently truncates real data, so the width is the widest row.
        """
        width = max([len(self.cols)] + [len(r) for r in self.rows]) if (self.cols or self.rows) else 0
        if len(self.cols) < width:
            self.cols = list(self.cols) + [f"c{i + 1}" for i in range(len(self.cols), width)]
        self.rows = [list(r) + [""] * (width - len(r)) for r in self.rows]


@dataclass
class KV:
    """Form fields, metadata blocks, `key: value` runs."""

    pairs: list[tuple[str, str]]
    caption: str = ""


@dataclass
class Figure:
    desc: str
    kind: str = "image"


@dataclass
class Code:
    text: str
    lang: str = ""


@dataclass
class Quote:
    text: str


@dataclass
class PageMark:
    number: int


@dataclass
class Elision:
    """A region deliberately left out, but declared so the model knows it exists.

    This is the difference between compression and truncation. Summarisation and
    context-window truncation both remove text *silently*: the model cannot tell
    whether it is reasoning over a whole document or a fragment. An Elision keeps
    the loss on the record -- kind, exact token count, a gist, and an id that can
    be expanded on demand -- so the omission is auditable and reversible.
    """

    eid: str
    kind: str
    tokens: int
    gist: str = ""
    items: int = 0


Block = Union[Heading, Para, ListBlock, Table, KV, Figure, Code, Quote, PageMark, Elision]


@dataclass
class Doc:
    title: str = ""
    source: str = ""
    blocks: list[Block] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def add(self, block: Block) -> None:
        self.blocks.append(block)
