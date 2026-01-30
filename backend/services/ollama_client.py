import os
import requests
from typing import Optional

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

def ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False

def generate_with_ollama(prompt: str, model: str = "llama3.1") -> Optional[str]:
    """
    Returns raw text response from Ollama, or None if not available.
    """
    if not ollama_available():
        return None

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.7}
    }
    r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data.get("response")
