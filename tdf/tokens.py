"""Token counting helpers.

Uses tiktoken's ``o200k_base`` (GPT-4o/5 family) by default. Claude's tokenizer
is not public; o200k_base is the standard public proxy and the same one the TOON
benchmarks use, so numbers here are comparable to published work.
"""

from __future__ import annotations

from functools import lru_cache

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


@lru_cache(maxsize=4)
def _enc(name: str):
    if tiktoken is None:
        raise RuntimeError("tiktoken is not installed: pip install tiktoken")
    return tiktoken.get_encoding(name)


def count(text: str, encoding: str = "o200k_base") -> int:
    if not text:
        return 0
    return len(_enc(encoding).encode(text, disallowed_special=()))


def cheapest(*candidates: str, encoding: str = "o200k_base") -> str:
    """Return whichever rendering costs the fewest tokens."""
    return min(candidates, key=lambda c: count(c, encoding))
