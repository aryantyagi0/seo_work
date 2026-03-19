import json
import os
import shutil
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import hashlib
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from rank_bm25 import BM25Okapi

# --- Constants ---
KB_DIR = os.path.dirname(os.path.abspath(__file__))
AUDITS_DIR = os.path.join(KB_DIR, "audits")
REPORTS_DIR = os.path.join(KB_DIR, "reports")
INDEX_FILE = os.path.join(KB_DIR, "kb_index.json")
AUDIT_HISTORY_FILE = os.path.join(KB_DIR, 'audit_history.json')
MODEL_NAME = 'all-MiniLM-L6-v2' # A good default, small and fast

# --- KB File I/O Functions ---
def _load_index() -> Dict[str, Any]:
    if not os.path.exists(INDEX_FILE):
        return {"audits": [], "reports": []}
    try:
        with open(INDEX_FILE, "r") as f:
            return json.load(f) or {"audits": [], "reports": []}
    except Exception:
        return {"audits": [], "reports": []}

def _save_index(index: Dict[str, Any]):
    os.makedirs(KB_DIR, exist_ok=True)
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f, indent=2)

def save_audit_results(audit_id: Optional[str], audit_data: Dict[str, Any]) -> str:
    os.makedirs(AUDITS_DIR, exist_ok=True)
    if not audit_id:
        audit_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    audit_path = os.path.join(AUDITS_DIR, f"audit_{audit_id}.json")
    with open(audit_path, "w") as f:
        json.dump(audit_data, f, indent=2)
    index = _load_index()
    index["audits"].append({"audit_id": audit_id, "path": audit_path})
    _save_index(index)
    return audit_id

def save_report_file(report_path: str, audit_id: Optional[str] = None) -> Optional[str]:
    if not report_path or not os.path.exists(report_path):
        return None
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filename = os.path.basename(report_path)
    target_path = os.path.join(REPORTS_DIR, filename)
    shutil.copy2(report_path, target_path)
    index = _load_index()
    index["reports"].append({"audit_id": audit_id, "path": target_path})
    _save_index(index)
    return target_path

def get_latest_report_path() -> Optional[str]:
    index = _load_index()
    reports = index.get("reports", [])
    if not reports:
        return None
    return reports[-1].get("path")

def get_latest_audit_path() -> Optional[str]:
    index = _load_index()
    audits = index.get("audits", [])
    if not audits:
        return None
    return audits[-1].get("path")

def get_latest_audit_data() -> Optional[Dict[str, Any]]:
    audit_path = get_latest_audit_path()
    if not audit_path or not os.path.exists(audit_path):
        return None
    try:
        with open(audit_path, "r") as f:
            return json.load(f)
    except Exception:
        return None

def find_latest_audit_for_url(url: str) -> Optional[Dict[str, Any]]:
    index = _load_index()
    audits = index.get("audits", [])
    if not audits:
        return None
    # Search from most recent
    for entry in reversed(audits):
        path = entry.get("path")
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r") as f:
                data = json.load(f)
            pages = data.get("pages", {})
            if url in pages:
                return data
        except Exception:
            continue
    return None

# --- Atomization Logic ---
def _load_audit_history() -> List[Dict[str, Any]]:
    if not os.path.exists(AUDIT_HISTORY_FILE): return []
    try:
        with open(AUDIT_HISTORY_FILE, 'r') as f:
            return json.load(f) or []
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error loading audit history: {e}")
        return []

def atomize_audit_data(audit_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Converts audit data into smaller 'atoms' for indexing.
    By default, it uses the latest audit data from the KB.
    """
    if audit_data is None:
        audit_data = get_latest_audit_data()
    
    if not audit_data:
        return []
    
    # Handle both a single audit dict or a list of audits (for backwards compatibility if needed)
    audits_to_process = [audit_data] if isinstance(audit_data, dict) and "pages" in audit_data else audit_data
    if not isinstance(audits_to_process, list):
        return []

    atoms = []
    for audit in audits_to_process:
        timestamp = audit.get("timestamp", datetime.now().isoformat())
        for url, page_data in audit.get("pages", {}).items():
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:10]
            for param_name, param_details in page_data.get("parameters", {}).items():
                if not isinstance(param_details, dict): continue
                value_str = json.dumps(param_details.get("value")) if isinstance(param_details.get("value"), (dict, list)) else str(param_details.get("value", "N/A"))
                text = (f"URL: {url} | Parameter: {param_name} | Value: {value_str} | "
                        f"Status: {param_details.get('status', 'pending')} | "
                        f"Reasoning: {param_details.get('llm_reasoning') or param_details.get('remediation_suggestion', 'No reasoning.')}")
                atoms.append({
                    "id": f"{url_hash}_{param_name}", "text": text,
                    "metadata": {"url": url, "type": param_name, "timestamp": timestamp}
                })
    return atoms

# --- Hybrid Search Index Manager ---
class SEOIndexManager:
    """Handles BM25 (keyword) and FAISS (vector) indexing and searching."""
    
    def __init__(self, atoms: List[Dict[str, Any]]):
        self.atoms = atoms
        self.corpus = [atom['text'] for atom in self.atoms]
        
        # --- BM25 Indexing ---
        self.tokenized_corpus = [doc.lower().split() for doc in self.corpus]
        self.bm25 = BM25Okapi(self.tokenized_corpus)
        
        # --- Vector Indexing (FAISS) ---
        self.model = SentenceTransformer(MODEL_NAME)
        self.embeddings = self.model.encode(self.corpus, convert_to_tensor=False, show_progress_bar=False)
        self.embeddings = np.array(self.embeddings).astype('float32')
        
        # Normalize embeddings for cosine similarity search with a L2 index
        faiss.normalize_L2(self.embeddings)
        
        self.dimension = self.embeddings.shape[1]
        self.vector_index = faiss.IndexFlatIP(self.dimension) # Using IndexFlatIP for cosine similarity on normalized vectors
        self.vector_index.add(self.embeddings)

    def search_bm25(self, query: str, filter_metadata: Optional[Dict[str, Any]] = None, top_n: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        tokenized_query = query.lower().split()
        if not filter_metadata:
            doc_scores = self.bm25.get_scores(tokenized_query)
            top_indices = sorted(range(len(doc_scores)), key=lambda i: doc_scores[i], reverse=True)[:top_n]
            return [(self.atoms[i], doc_scores[i]) for i in top_indices]

        filtered_indices = [i for i, atom in enumerate(self.atoms) if all(atom['metadata'].get(key) == value for key, value in filter_metadata.items())]
        if not filtered_indices: return []
        
        filtered_corpus = [self.tokenized_corpus[i] for i in filtered_indices]
        filtered_bm25 = BM25Okapi(filtered_corpus)
        doc_scores = filtered_bm25.get_scores(tokenized_query)
        
        top_scored_indices = sorted(range(len(doc_scores)), key=lambda i: doc_scores[i], reverse=True)[:top_n]
        results = []
        for i in top_scored_indices:
            original_index = filtered_indices[i]
            results.append((self.atoms[original_index], doc_scores[i]))
        return results

    def search_vectors(self, query: str, filter_metadata: Optional[Dict[str, Any]] = None, top_n: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        query_vector = self.model.encode([query], convert_to_tensor=False)
        query_vector = np.array(query_vector).astype('float32')
        faiss.normalize_L2(query_vector)

        if not filter_metadata:
            distances, indices = self.vector_index.search(query_vector, top_n)
            return [(self.atoms[idx], score) for idx, score in zip(indices[0], distances[0]) if idx != -1]

        filtered_indices = [i for i, atom in enumerate(self.atoms) if all(atom['metadata'].get(key) == value for key, value in filter_metadata.items())]
        if not filtered_indices: return []

        # Create a temporary FAISS index for the filtered subset
        filtered_embeddings = self.embeddings[filtered_indices]
        temp_index = faiss.IndexFlatIP(self.dimension)
        temp_index.add(filtered_embeddings)
        
        distances, temp_indices = temp_index.search(query_vector, top_n)
        
        results = []
        for i, score in zip(temp_indices[0], distances[0]):
            if i != -1:
                original_index = filtered_indices[i]
                results.append((self.atoms[original_index], score))
        return results
