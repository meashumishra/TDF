"""Benchmark LLMLingua against TDF on out-of-training-data documents."""

import sys
import time
from pathlib import Path

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
    )
    
    # We will use recent documents, e.g. the SEC filing or worldbank CSV 
    # to avoid training data contamination as much as possible.
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
        
        # We target LLMLingua to compress to approximately the same token budget as TDF
        # so we can compare the fidelity of the output.
        target_ratio = tdf_toks / md_toks
        
        t0 = time.perf_counter()
        # Compress with LLMLingua
        results = compressor.compress_prompt(
            [md],
            rate=target_ratio,
            force_tokens=['\n', '?']
        )
        t_llm = time.perf_counter() - t0
        
        llm_toks = results['compressed_tokens']
        
        print(f"| {path.name} | {md_toks:,} | {tdf_toks:,} | {100*(1-tdf_toks/md_toks):.1f}% | {llm_toks:,} | {100*(1-llm_toks/md_toks):.1f}% | {t_llm:.2f}s |")
        
        # Save output for inspection
        out_path = ROOT / "bench" / f"{path.stem}_llmlingua.txt"
        out_path.write_text(results['compressed_prompt'])
        print(f"  -> Wrote LLMLingua output to {out_path}", file=sys.stderr)

if __name__ == "__main__":
    run_benchmark()
"""Benchmark LLMLingua against TDF on out-of-training-data documents."""

import sys
import time
from pathlib import Path

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
        device_map="cpu", # Force CPU to avoid CUDA error on Mac
    )
    
    # We will use recent documents, e.g. the SEC filing or worldbank CSV 
    # to avoid training data contamination as much as possible.
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
        
        # We target LLMLingua to compress to approximately the same token budget as TDF
        # so we can compare the fidelity of the output.
        target_ratio = tdf_toks / md_toks
        
        t0 = time.perf_counter()
        # Compress with LLMLingua
        results = compressor.compress_prompt(
            [md],
            rate=target_ratio,
            force_tokens=['\n', '?']
        )
        t_llm = time.perf_counter() - t0
        
        llm_toks = results['compressed_tokens']
        
        print(f"| {path.name} | {md_toks:,} | {tdf_toks:,} | {100*(1-tdf_toks/md_toks):.1f}% | {llm_toks:,} | {100*(1-llm_toks/md_toks):.1f}% | {t_llm:.2f}s |")
        
        # Save output for inspection
        out_path = ROOT / "bench" / f"{path.stem}_llmlingua.txt"
        out_path.write_text(results['compressed_prompt'])
        print(f"  -> Wrote LLMLingua output to {out_path}", file=sys.stderr)

if __name__ == "__main__":
    run_benchmark()
