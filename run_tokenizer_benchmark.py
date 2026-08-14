import tiktoken
import sys
from pathlib import Path
from tdf.readers import read
from tdf.emit import render_markdown, render_tdf

def count(text: str, model: str) -> int:
    enc = tiktoken.get_encoding(model)
    return len(enc.encode(text, allowed_special="all"))

SAMPLES = Path("samples")
files = sorted(p for p in SAMPLES.iterdir() if p.is_file() and not p.name.startswith("."))

tokenizers = ["o200k_base", "cl100k_base"] # Testing GPT-4o and GPT-4 tokenizers

results = {t: [] for t in tokenizers}

for p in files:
    doc = read(p)
    md = render_markdown(doc)
    tdf = render_tdf(doc, legend=False)
    
    for t in tokenizers:
        md_toks = count(md, t)
        tdf_toks = count(tdf, t)
        saving = round(100 * (1 - tdf_toks / md_toks), 1)
        results[t].append((p.name, md_toks, tdf_toks, saving))

for t in tokenizers:
    print(f"\nTokenizer: {t}")
    for name, md_t, tdf_t, sav in results[t]:
        print(f"  {name}: MD {md_t} -> TDF {tdf_t} ({sav}% savings)")
