import hashlib
import json
import os
import time
from pathlib import Path
from urllib import request, error

CACHE_DIR = Path("eval/runner/.cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def generate(prompt: str, model: str = "gpt-4o-mini", temperature: float = 0.0, seed: int = 1) -> str:
    # Use sha256 of prompt+model+seed for caching
    key_input = f"{prompt}|{model}|{seed}".encode("utf-8")
    cache_key = hashlib.sha256(key_input).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if cache_file.exists():
        with open(cache_file, "r") as f:
            return json.load(f)["response"]
            
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        # Require API key instead of silently inventing fake results
        raise RuntimeError("OPENAI_API_KEY environment variable is required to run the evaluation.")
        
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "seed": seed
    }
    
    req = request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
    for attempt in range(3):
        try:
            with request.urlopen(req) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                answer = resp_data["choices"][0]["message"]["content"]
                
                with open(cache_file, "w") as f:
                    json.dump({"response": answer}, f)
                    
                return answer
        except error.HTTPError as e:
            if e.code == 429: # Rate limit
                time.sleep(2 ** attempt)
            else:
                raise
    raise Exception("API failed after retries")
