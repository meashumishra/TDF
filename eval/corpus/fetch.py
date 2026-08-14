import urllib.request
import os
import json
import hashlib
from pathlib import Path

def download(url: str, dest: Path) -> Path:
    if not dest.exists():
        print(f"Downloading {url} to {dest}")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            dest.write_bytes(response.read())
    return dest

def main():
    out = Path("eval/corpus/raw")
    out.mkdir(parents=True, exist_ok=True)
    
    docs = [
        {
            "id": "co2_data",
            "url": "https://raw.githubusercontent.com/owid/co2-data/master/owid-co2-data.csv",
            "filename": "co2.csv",
            "type": "csv"
        },
        {
            "id": "k8s_deployment",
            "url": "https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/controllers/deployment.md",
            "filename": "deployment.md",
            "type": "md"
        }
    ]
    
    manifest = []
    
    for d in docs:
        dest = out / d["filename"]
        try:
            download(d["url"], dest)
            hasher = hashlib.sha256()
            hasher.update(dest.read_bytes())
            d["sha256"] = hasher.hexdigest()
            d["path"] = str(dest)
            manifest.append(d)
        except Exception as e:
            print(f"Failed to fetch {d['url']}: {e}")
            
    with open("eval/corpus/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

if __name__ == "__main__":
    main()

def add_local_samples():
    import shutil
    out = Path("eval/corpus/raw")
    manifest_path = Path("eval/corpus/manifest.json")
    with open(manifest_path, "r") as f:
        manifest = json.load(f)
        
    local_docs = [
        ("samples_real/sec_filing.html", "sec_filing.html", "html"),
        ("samples/operating_review.pdf", "operating_review.pdf", "pdf"),
        ("samples/sales_report.xlsx", "sales_report.xlsx", "xlsx")
    ]
    
    for src, filename, ftype in local_docs:
        src_path = Path(src)
        if src_path.exists():
            dest = out / filename
            shutil.copy(src_path, dest)
            hasher = hashlib.sha256()
            hasher.update(dest.read_bytes())
            manifest.append({
                "id": filename.split('.')[0],
                "url": f"local://{src}",
                "filename": filename,
                "type": ftype,
                "sha256": hasher.hexdigest(),
                "path": str(dest)
            })
            
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

if __name__ == "__main__":
    add_local_samples()
