"""Check if LLMLingua compression destroys structure compared to TDF."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    sec = ROOT / "bench" / "sec_filing_llmlingua.txt"
    handbook = ROOT / "bench" / "handbook_llmlingua.txt"
    
    if sec.exists():
        text = sec.read_text()
        print("SEC Filing LLMLingua snippet:")
        print(text[:500])
        print("\n" + "-"*40 + "\n")
        
    if handbook.exists():
        text = handbook.read_text()
        print("Handbook LLMLingua snippet:")
        print(text[:500])
        print("\n" + "-"*40 + "\n")

if __name__ == "__main__":
    main()
