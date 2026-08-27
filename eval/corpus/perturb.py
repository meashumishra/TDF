import json
import pickle
import random
import re
from pathlib import Path
from tdf.readers import read
from tdf.ir import Doc, Table, Para, Heading, KV, ListBlock, Code

def perturb_text(text: str, entity_map: dict, num_map: dict) -> str:
    # Very basic perturbation: 
    # Swap some common names if they appear
    for k, v in entity_map.items():
        text = text.replace(k, v)
        
    # Shift numbers
    def repl_num(m):
        val = m.group(0)
        if val not in num_map:
            if "." in val:
                num_map[val] = str(round(float(val) * random.uniform(0.5, 1.5), 2))
            else:
                num_map[val] = str(int(int(val) * random.uniform(0.5, 1.5)))
        return num_map[val]
        
    text = re.sub(r'\b\d+(?:\.\d+)?\b', repl_num, text)
    return text

def perturb_doc(doc: Doc) -> (Doc, dict):
    d = Doc(title=doc.title, blocks=[])
    d.meta = doc.meta.copy()
    
    entity_map = {
        "Kubernetes": "Cybernetes",
        "Pod": "Module",
        "Deployment": "Rollout",
        "Company": "CorpInc",
        "Revenue": "Income"
    }
    num_map = {}
    
    for b in doc.blocks:
        if isinstance(b, Para):
            d.add(Para(perturb_text(b.text, entity_map, num_map)))
        elif isinstance(b, Heading):
            d.add(Heading(b.level, perturb_text(b.text, entity_map, num_map)))
        elif isinstance(b, ListBlock):
            d.add(ListBlock([perturb_text(i, entity_map, num_map) for i in b.items], b.ordered))
        elif isinstance(b, Table):
            new_cols = [perturb_text(c, entity_map, num_map) for c in b.cols]
            new_rows = [[perturb_text(c, entity_map, num_map) for c in r] for r in b.rows]
            d.add(Table(new_cols, new_rows, perturb_text(b.caption, entity_map, num_map), b.group))
        elif isinstance(b, KV):
            new_pairs = [(perturb_text(k, entity_map, num_map), perturb_text(v, entity_map, num_map)) for k, v in b.pairs]
            d.add(KV(new_pairs, perturb_text(b.caption, entity_map, num_map)))
        elif isinstance(b, Code):
            d.add(Code(perturb_text(b.text, entity_map, num_map), b.lang))
        else:
            d.add(b)
            
    return d, {"entity_map": entity_map, "num_map": num_map}

def main():
    with open("eval/corpus/manifest.json", "r") as f:
        manifest = json.load(f)
        
    out_dir = Path("eval/corpus/perturbed")
    out_dir.mkdir(exist_ok=True)
    
    for m in manifest:
        print(f"Perturbing {m['id']}...")
        try:
            doc = read(Path(m['path']))
        except ValueError as e:
            print(f"  SKIP {m['id']}: {e}")
            continue

        # If it's the co2 dataset, it's huge, maybe trim it to 100 rows for eval speed
        if m['id'] == 'co2_data':
            for b in doc.blocks:
                if isinstance(b, Table):
                    b.rows = b.rows[:100]
                    
        p_doc, p_map = perturb_doc(doc)
        
        with open(out_dir / f"{m['id']}.pkl", "wb") as f:
            pickle.dump(p_doc, f)
            
        with open(out_dir / f"{m['id']}_map.json", "w") as f:
            json.dump(p_map, f, indent=2)

if __name__ == "__main__":
    random.seed(42)
    main()
