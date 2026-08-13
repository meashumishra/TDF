"""Benchmark LLMLingua against TDF on out-of-training-data documents."""

import sys
import time
from pathlib import Path

# Patch torch.cuda.is_available to return False before importing llmlingua
import torch
def _is_available():
    return False
torch.cuda.is_available = _is_available

try:
    from llmlingua import PromptCompressor
except ImportError:
    print("Run `uv pip install llmlingua torch transformers accelerate` first", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf.readers import read
from tdf.emit import render_markdown, render_tdf
from tdf.tokens import count

def run_benchmark():
    compressor = PromptCompressor(
        model_name="microsoft/llmlingua-2-xlm-roberta-large-meetingbank",
        use_llmlingua2=True,
        device_map="cpu", # Force CPU
    )
    
    files_to_bench = [
        ROOT / "samples_real" / "sec_filing.html",
        ROOT / "samples" / "handbook.html",
    ]
    
    print("| Document | Markdown Tokens | TDF Tokens | TDF Saving | LLMLingua Tokens | LLM Lingua Saving | LLMLingua Time (s) |")
    print("|---|---|---|---|---|---|---|")
    
    for path in files_to_bench:
        if not path.exists():
            continue
            
        doc = read(path)
        md = render_markdown(doc)
        tdf = render_tdf(doc, legend=False)
        
        md_toks = count(md)
        tdf_toks = count(tdf)
        
        target_ratio = tdf_toks / md_toks
        
        t0 = time.perf_counter()
        results = compressor.compress_prompt(
            [md],
            rate=target_ratio,
            force_tokens=['\n', '?']
        )
        t_llm = time.perf_counter() - t0
        
        # LLMLingua doesn't always hit exact target
        llm_toks = count(results['compressed_prompt'])
        
        print(f"| {path.name} | {md_toks:,} | {tdf_toks:,} | {100*(1-tdf_toks/md_toks):.1f}% | {llm_toks:,} | {100*(1-llm_toks/md_toks):.1f}% | {t_llm:.2f}s |")
        
        out_path = ROOT / "bench" / f"{path.stem}_llmlingua.txt"
        out_path.write_text(results['compressed_prompt'])

if __name__ == "__main__":
    run_benchmark()
