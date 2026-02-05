import os
import requests
from typing import Optional

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=8)
        return r.status_code == 200
    except Exception as e:
        print(f"[Ollama] /api/tags not reachable: {e}")
        return False

def generate_with_ollama(prompt: str, model: str = "llama3.2:3b") -> Optional[str]:

    """
    Returns raw text response from Ollama, or None if Ollama is slow/unavailable.
    """
    if not ollama_available():

        return None

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1,
                    "num_predict": 1200
                    }
    }

    try:
        # increase timeout a bit, but still safe
        r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=300)
        r.raise_for_status()
        data = r.json()
        return data.get("response")
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
        print(f"[Ollama] Timeout/Connection error → fallback. Details: {e}")
        return None
    except Exception as e:
        print(f"[Ollama] Error → fallback. Details: {e}")
        return None