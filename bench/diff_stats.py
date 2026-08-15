from tdf.readers import read
import copy
import random
from tdf.diff import diff_docs
from tdf.tokens import count
from tdf.emit import render_tdf

def measure():
    base_doc = read("samples/services_agreement.docx")
    
    out = []
    out.append("# TDF Diff Token Efficiency")
    out.append("")
    out.append("This document evaluates the token efficiency of `tdf diff` compared to the alternative of pasting both documents into an LLM context.")
    out.append("")
    out.append("| Changes | Both Docs Tokens | Diff Tokens | Savings |")
    out.append("|---|---|---|---|")
    
    for pct in [0, 0.01, 0.05, 0.1, 0.2, 0.5]:
        doc = copy.deepcopy(base_doc)
        new_doc = copy.deepcopy(doc)
        changes = 0
        for b in new_doc.blocks:
            if type(b).__name__ == "Para":
                if random.random() < pct:
                    b.text += " (modified)"
                    changes += 1
            if type(b).__name__ == "Table":
                for r in b.rows:
                    if random.random() < pct:
                        if r: r[-1] += "x"
                        changes += 1
        
        diff_text = diff_docs(doc, new_doc)
        diff_toks = count(diff_text)
        
        doc1_toks = count(render_tdf(copy.deepcopy(doc)))
        doc2_toks = count(render_tdf(copy.deepcopy(new_doc)))
        both_toks = doc1_toks + doc2_toks
        
        savings = 100 * (1 - diff_toks / both_toks)
        out.append(f"| {int(pct*100)}% | {both_toks:,} | {diff_toks:,} | {savings:.1f}% |")

    out.append("")
    out.append("## Change Detection Accuracy")
    out.append("The token reduction implies models will experience significantly fewer distractors. A future eval harness run on consecutive financial filings will measure exact QA recall vs raw text pasting.")
    with open("bench/results_diff.md", "w") as f:
        f.write("\n".join(out))
        f.write("\n")

if __name__ == "__main__":
    measure()
