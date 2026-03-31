import json
import os
from typing import Dict, Any, List, Optional

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "kb", "chat_memory.json")

def _load_memory() -> List[Dict[str, Any]]:
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f) or []
    except Exception:
        return []

def _save_memory(entries: List[Dict[str, Any]]):
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    with open(MEMORY_FILE, "w") as f:
        json.dump(entries, f, indent=2)

def store_qa(user_query: str, answer: str):
    entries = _load_memory()
    entries.append(
        {
            "q": user_query.strip(),
            "a": answer.strip(),
        }
    )
    _save_memory(entries[-200:])  # keep last 200 entries

def find_exact_match(user_query: str) -> Optional[str]:
    query = user_query.strip().lower()
    for entry in reversed(_load_memory()):
        if entry.get("q", "").strip().lower() == query:
            return entry.get("a")
    return None

def get_last_question() -> Optional[str]:
    entries = _load_memory()
    if not entries:
        return None
    return entries[-1].get("q")

def get_chat_history() -> List[Dict[str, Any]]:
    return _load_memory()
