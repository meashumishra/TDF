import hashlib
import json
import os
import socket
import time
from pathlib import Path
from urllib import request, error

CACHE_DIR = Path("eval/runner/.cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def generate(prompt: str, model: str = "gpt-4o-mini", temperature: float = 0.0, seed: int = 1) -> str:
    # Cache key must cover every request parameter that can change the
    # response. It previously omitted max_tokens/temperature/top_p, so a
    # re-run with a different EVAL_MAX_TOKENS silently replayed responses
    # generated (and truncated) under the OLD budget instead of calling the
    # API -- corrupting exactly the token-budget re-run this knob exists for.
    max_tokens = int(os.environ.get("EVAL_MAX_TOKENS", "256"))
    top_p = float(os.environ.get("EVAL_TOP_P", "1"))
    key_input = f"{prompt}|{model}|{seed}|{max_tokens}|{temperature}|{top_p}".encode("utf-8")
    cache_key = hashlib.sha256(key_input).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"
    
    if cache_file.exists():
        with open(cache_file, "r") as f:
            return json.load(f)["response"]
            
    openai_key = os.environ.get("OPENAI_API_KEY")
    nvidia_key = os.environ.get("NVIDIA_API_KEY")
    api_key = openai_key or nvidia_key
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY or NVIDIA_API_KEY environment variable is required to run the evaluation."
        )

    default_base = "https://api.openai.com/v1"
    if nvidia_key and not openai_key:
        default_base = "https://integrate.api.nvidia.com/v1"
    base_url = os.environ.get("LLM_BASE_URL", default_base).rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        # NOTE: gpt-oss-class REASONING models routinely need >>256 tokens
        # (they think before answering); at the default, ~73% of runs in the
        # first eval were truncated mid-reasoning, which systematically
        # penalises harder representations. For v2+ set e.g.
        # EVAL_MAX_TOKENS=2048 and record the value in the report provenance.
        "seed": seed,
    }
    
    timeout_sec = int(os.environ.get("LLM_HTTP_TIMEOUT_SEC", "60"))
    req = request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers)
    tried_without_seed = False
    for attempt in range(3):
        try:
            with request.urlopen(req, timeout=timeout_sec) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                msg = (resp_data.get("choices") or [{}])[0].get("message", {}) or {}
                answer = msg.get("content")
                if answer is None:
                    # Some providers/models may emit reasoning_content with empty content.
                    answer = msg.get("reasoning_content")
                if answer is None:
                    answer = ""
                
                with open(cache_file, "w") as f:
                    json.dump({"response": answer}, f)
                    
                return answer
        except error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            if (
                not tried_without_seed
                and e.code in (400, 422)
                and "seed" in body.lower()
            ):
                tried_without_seed = True
                data.pop("seed", None)
                req = request.Request(
                    url, data=json.dumps(data).encode("utf-8"), headers=headers
                )
                continue
            if e.code == 429: # Rate limit
                time.sleep(2 ** attempt)
            else:
                raise
        except (error.URLError, socket.timeout, TimeoutError):
            # A read timeout on request.urlopen() raises socket.timeout
            # (== TimeoutError, not a URLError subclass), so it previously
            # skipped this retry/backoff path entirely and went straight to
            # a permanent skip on the first slow response -- exactly the
            # failure mode a busy shared endpoint under concurrency hits
            # routinely, silently shrinking the eval's effective sample.
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                raise
    raise Exception("API failed after retries")
