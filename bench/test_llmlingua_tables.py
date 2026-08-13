"""Check if LLMLingua compression destroys structure compared to TDF."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    handbook = ROOT / "bench" / "handbook_llmlingua.txt"
    if handbook.exists():
        text = handbook.read_text()
        print("Handbook LLMLingua full snippet:")
        print(text[500:1500])
        print("\n" + "-"*40 + "\n")

if __name__ == "__main__":
    main()
"""Check if LLMLingua compression destroys structure compared to TDF."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def main():
    handbook = ROOT / "bench" / "handbook_llmlingua.txt"
    if handbook.exists():
        text = handbook.read_text()
        print("Handbook LLMLingua looking for tables...")
        print(text[1500:])
        print("\n" + "-"*40 + "\n")

if __name__ == "__main__":
    main()
