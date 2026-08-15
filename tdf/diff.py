from __future__ import annotations
import copy
import hashlib
from collections import defaultdict
from difflib import SequenceMatcher

from .ir import Doc, Block, Heading, Para, ListBlock, Table, KV, Figure, Code, Quote, PageMark, Elision
from .optimize import optimize

def _hash_block(b: Block) -> str:
    # return a normalized hash of the block's content
    if isinstance(b, Heading):
        content = f"H{b.level}:{b.text}"
    elif isinstance(b, Para):
        content = f"P:{b.text}"
    elif isinstance(b, ListBlock):
        content = f"L:{b.ordered}:" + "|".join(b.items)
    elif isinstance(b, Table):
        content = f"T:" + "|".join(b.cols) + ":" + "|".join("|".join(r) for r in b.rows)
    elif isinstance(b, KV):
        content = f"KV:" + "|".join(f"{k}={v}" for k, v in b.pairs)
    elif isinstance(b, Figure):
        content = f"F:{b.desc}"
    elif isinstance(b, Code):
        content = f"C:{b.lang}:{b.text}"
    elif isinstance(b, Quote):
        content = f"Q:{b.text}"
    elif isinstance(b, PageMark):
        content = f"PM:{b.number}"
    elif isinstance(b, Elision):
        content = f"E:{b.eid}:{b.gist}"
    else:
        content = str(b)
        
    return hashlib.sha256(content.encode('utf-8')).hexdigest()

def _strip_noise(doc: Doc) -> Doc:
    # "Ignore running headers/footers and page numbers (!R, !P content) — page-break shifts otherwise dominate PDF diffs."
    d = copy.deepcopy(doc)
    d.blocks = [b for b in d.blocks if not isinstance(b, PageMark)]
    return d

def diff_docs(old_doc: Doc, new_doc: Doc, granularity="block", context=1, summary_only=False, old_name="old", new_name="new") -> str:
    old_work = _strip_noise(old_doc)
    new_work = _strip_noise(new_doc)
    
    # Run optimize on both to remove boilerplate (!R) so it's not in the block list
    old_arts = optimize(old_work)
    new_arts = optimize(new_work)
    
    old_blocks = old_work.blocks
    new_blocks = new_work.blocks
    
    # 1. Anchor pass
    old_hashes = [_hash_block(b) for b in old_blocks]
    new_hashes = [_hash_block(b) for b in new_blocks]
    
    # ... implementation pending ...
    return f"!DIFF {old_name} -> {new_name}\n"


def _similar(b1: Block, b2: Block) -> bool:
    if type(b1) != type(b2):
        return False
    # Simple similarity based on text representation
    s1 = str(b1)
    s2 = str(b2)
    return SequenceMatcher(None, s1, s2).ratio() > 0.6

def _align_blocks(old_blocks: list[Block], new_blocks: list[Block]) -> list[tuple[int|None, int|None]]:
    old_hashes = [_hash_block(b) for b in old_blocks]
    new_hashes = [_hash_block(b) for b in new_blocks]
    
    sm = SequenceMatcher(None, old_hashes, new_hashes)
    matches = []
    
    # sm.get_opcodes() gives: ('replace'|'delete'|'insert'|'equal', i1, i2, j1, j2)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for i, j in zip(range(i1, i2), range(j1, j2)):
                matches.append((i, j))
        else:
            # We have a region of unanchored blocks: old_blocks[i1:i2] and new_blocks[j1:j2]
            # Pass 2: Structural / Similarity pass
            # For simplicity right now, try to match by similarity in order
            o_idx = i1
            n_idx = j1
            while o_idx < i2 and n_idx < j2:
                if _similar(old_blocks[o_idx], new_blocks[n_idx]):
                    matches.append((o_idx, n_idx))
                    o_idx += 1
                    n_idx += 1
                else:
                    # Mismatch. We'll just emit as delete then insert for now.
                    # A better greedy match could search ahead.
                    # Let's do a mini N^2 similarity search
                    best_ratio = 0
                    best_o = -1
                    best_n = -1
                    for oi in range(o_idx, i2):
                        for ni in range(n_idx, j2):
                            if type(old_blocks[oi]) == type(new_blocks[ni]):
                                ratio = SequenceMatcher(None, str(old_blocks[oi]), str(new_blocks[ni])).ratio()
                                if ratio > best_ratio and ratio > 0.6:
                                    best_ratio = ratio
                                    best_o = oi
                                    best_n = ni
                    
                    if best_ratio > 0.6:
                        # Found a match!
                        # Everything before best_o is deleted
                        for oi in range(o_idx, best_o):
                            matches.append((oi, None))
                        # Everything before best_n is inserted
                        for ni in range(n_idx, best_n):
                            matches.append((None, ni))
                        
                        matches.append((best_o, best_n))
                        o_idx = best_o + 1
                        n_idx = best_n + 1
                    else:
                        matches.append((o_idx, None))
                        o_idx += 1
            
            while o_idx < i2:
                matches.append((o_idx, None))
                o_idx += 1
            while n_idx < j2:
                matches.append((None, n_idx))
                n_idx += 1
                
    return matches

def _get_heading_path(blocks: list[Block], idx: int) -> str:
    path = []
    for i in range(idx):
        b = blocks[i]
        if isinstance(b, Heading):
            # keep latest heading at each level
            while path and path[-1].level >= b.level:
                path.pop()
            path.append(b)
    if not path:
        return "document start"
    return path[-1].text

def _region_name(blocks: list[Block], idx: int) -> str:
    b = blocks[idx]
    path = _get_heading_path(blocks, idx)
    if isinstance(b, Heading):
        return b.text
    elif isinstance(b, Table):
        return f"{path}  table {len(b.rows)}x{len(b.cols)}"
    elif isinstance(b, Para):
        return f"{path}  paragraph"
    elif isinstance(b, ListBlock):
        return f"{path}  list"
    elif isinstance(b, KV):
        return f"{path}  key-value"
    elif isinstance(b, Figure):
        return f"{path}  figure"
    elif isinstance(b, Code):
        return f"{path}  code"
    return f"{path}  {type(b).__name__.lower()}"


def _diff_table(old_t: Table, new_t: Table) -> tuple[list[str], str]:
    out = []
    # If columns don't match exactly, maybe just diff row by row?
    # Simple table row diff:
    out.append("!C\t" + "\t".join(new_t.cols))
    
    # Try to find a primary key (a column with all unique values)
    # Prefer leftmost
    pk_idx = -1
    if old_t.rows and new_t.rows:
        for c in range(min(len(old_t.cols), len(new_t.cols))):
            old_vals = [r[c] for r in old_t.rows if c < len(r)]
            new_vals = [r[c] for r in new_t.rows if c < len(r)]
            if len(set(old_vals)) == len(old_vals) and len(set(new_vals)) == len(new_vals):
                pk_idx = c
                break
                
    if pk_idx >= 0:
        # Match by primary key
        old_map = {r[pk_idx]: r for r in old_t.rows if pk_idx < len(r)}
        new_map = {r[pk_idx]: r for r in new_t.rows if pk_idx < len(r)}
        
        # Determine order from new_t
        seen_keys = set()
        for r in new_t.rows:
            if pk_idx >= len(r):
                out.append("+\t" + "\t".join(r))
                continue
            k = r[pk_idx]
            seen_keys.add(k)
            if k in old_map:
                old_r = old_map[k]
                if old_r != r:
                    # Cell level diff
                    row_diff = []
                    for i in range(max(len(old_r), len(r))):
                        ov = old_r[i] if i < len(old_r) else ""
                        nv = r[i] if i < len(r) else ""
                        if ov == nv:
                            row_diff.append(nv)
                        else:
                            row_diff.append(f"{ov}->{nv}")
                    out.append("~\t" + "\t".join(row_diff))
            else:
                out.append("+\t" + "\t".join(r))
                
        # Removed rows
        for r in old_t.rows:
            if pk_idx < len(r) and r[pk_idx] not in seen_keys:
                out.append("-\t" + "\t".join(r))
    else:
        # Positional matching
        sm = SequenceMatcher(None, [str(r) for r in old_t.rows], [str(r) for r in new_t.rows])
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                pass # Unchanged rows are skipped in table diff
            elif tag == 'replace':
                for oi, ni in zip(range(i1, i2), range(j1, j2)):
                    old_r = old_t.rows[oi]
                    new_r = new_t.rows[ni]
                    row_diff = []
                    for i in range(max(len(old_r), len(new_r))):
                        ov = old_r[i] if i < len(old_r) else ""
                        nv = new_r[i] if i < len(new_r) else ""
                        if ov == nv:
                            row_diff.append(nv)
                        else:
                            row_diff.append(f"{ov}->{nv}")
                    out.append("~\t" + "\t".join(row_diff))
                # If lengths mismatch, add or remove the rest
                for oi in range(i1 + (j2-j1), i2):
                    out.append("-\t" + "\t".join(old_t.rows[oi]))
                for ni in range(j1 + (i2-i1), j2):
                    out.append("+\t" + "\t".join(new_t.rows[ni]))
            elif tag == 'insert':
                for ni in range(j1, j2):
                    out.append("+\t" + "\t".join(new_t.rows[ni]))
            elif tag == 'delete':
                for oi in range(i1, i2):
                    out.append("-\t" + "\t".join(old_t.rows[oi]))
    return out, f"(matched by key: {old_t.cols[pk_idx]})" if pk_idx >= 0 else "(matched by position)"

from .emit import _tdf_table, _escape_body

def _render_block(b: Block) -> list[str]:
    # Very simplified block rendering for the diff
    if isinstance(b, Heading):
        return ["#" * min(b.level, 6) + " " + b.text]
    elif isinstance(b, Para):
        return [_escape_body(b.text)]
    elif isinstance(b, ListBlock):
        return [f"{i + 1} {item}" if b.ordered else f"- {item}" for i, item in enumerate(b.items)]
    elif isinstance(b, Table):
        return _tdf_table(b)
    elif isinstance(b, Code):
        return [f"```{b.lang}"] + b.text.split("\n") + ["```"]
    elif isinstance(b, Quote):
        return [f"> {b.text}"]
    return [str(b)]

def diff_docs(old_doc: Doc, new_doc: Doc, granularity="block", context=1, summary_only=False, old_name="old", new_name="new") -> str:
    old_work = _strip_noise(old_doc)
    new_work = _strip_noise(new_doc)
    
    old_arts = optimize(old_work)
    new_arts = optimize(new_work)
    
    old_blocks = old_work.blocks
    new_blocks = new_work.blocks
    
    matches = _align_blocks(old_blocks, new_blocks)
    
    out = [f"!DIFF {old_name} -> {new_name}"]
    
    unchanged_count = 0
    
    for old_idx, new_idx in matches:
        if old_idx is not None and new_idx is not None:
            if _hash_block(old_blocks[old_idx]) == _hash_block(new_blocks[new_idx]):
                unchanged_count += 1
                continue
            
            # Modified
            if unchanged_count > 0:
                out.append(f"!= {unchanged_count}")
                unchanged_count = 0
                
            region = _region_name(new_blocks, new_idx)
            out.append(f"!~ {region}")
            if not summary_only:
                if isinstance(old_blocks[old_idx], Table) and isinstance(new_blocks[new_idx], Table) and granularity in ("block", "cell"):
                    table_diff, strategy = _diff_table(old_blocks[old_idx], new_blocks[new_idx])
                    out[-1] += f"  {strategy}"
                    out.extend(table_diff)
                else:
                    out.extend(["- " + line for line in _render_block(old_blocks[old_idx])])
                    out.extend(["+ " + line for line in _render_block(new_blocks[new_idx])])
                    
        elif old_idx is not None:
            # Deleted
            if unchanged_count > 0:
                out.append(f"!= {unchanged_count}")
                unchanged_count = 0
            region = _region_name(old_blocks, old_idx)
            out.append(f"!- {region}")
            if not summary_only:
                out.extend(["- " + line for line in _render_block(old_blocks[old_idx])])
                
        elif new_idx is not None:
            # Inserted
            if unchanged_count > 0:
                out.append(f"!= {unchanged_count}")
                unchanged_count = 0
            region = _region_name(new_blocks, new_idx)
            out.append(f"!+ {region}")
            if not summary_only:
                out.extend(["+ " + line for line in _render_block(new_blocks[new_idx])])
                
    if unchanged_count > 0:
        out.append(f"!= {unchanged_count}")
        
    return "\n".join(out)
