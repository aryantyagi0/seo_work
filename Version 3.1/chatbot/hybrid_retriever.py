import re
from typing import List, Optional, Dict, Any, Tuple
from collections import defaultdict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kb.kb_manager import SEOIndexManager, atomize_audit_data

FILLER_WORDS = [
    'what', 'is', 'the', 'for', 'a', 'an', 'are', 'in', 'of', 'tell', 'me',
    'about', 'can', 'you', 'show', 'give', 'list', 'how', 'does', 'work',
    'my', 'on', 'please', 'check', 'of'
]

class HybridRetriever:
    """
    A retriever that performs a hybrid search using both BM25 (keyword) and
    FAISS (vector) search, then fuses the results using Reciprocal Rank Fusion.
    """

    def __init__(self):
        """Initializes the retriever and the underlying index manager."""
        self.filler_words_regex = re.compile(
            r'\b(' + r'|'.join(re.escape(word) for word in FILLER_WORDS) + r')\b',
            re.IGNORECASE
        )
        # Eagerly load and index the data on initialization.
        self.atoms = atomize_audit_data()
        if self.atoms:
            self.index_manager = SEOIndexManager(self.atoms)
        else:
            self.index_manager = None
            print("Warning: HybridRetriever initialized with no atoms from the knowledge base.")

    def _clean_query(self, query: str) -> str:
        """Strips filler words for better keyword search accuracy."""
        cleaned_query = self.filler_words_regex.sub('', query).strip()
        return re.sub(r'\s+', ' ', cleaned_query)

    def _reciprocal_rank_fusion(self, search_results_lists: List[List[Tuple[Dict, float]]], k: int = 60) -> List[Tuple[Dict, float]]:
        """
        Performs RRF on multiple lists of search results.
        
        Args:
            search_results_lists: A list where each item is a list of (atom, score) tuples.
            k: A constant used in the RRF formula, defaults to 60.

        Returns:
            A single, re-ranked list of (atom, score) tuples.
        """
        rrf_scores = defaultdict(float)
        
        # Maps atom IDs to the full atom dictionary to avoid duplicates
        atom_id_map = {}

        for results in search_results_lists:
            for rank, (atom, _) in enumerate(results, 1):
                atom_id = atom['id']
                rrf_scores[atom_id] += 1.0 / (k + rank)
                if atom_id not in atom_id_map:
                    atom_id_map[atom_id] = atom

        # Sort atoms based on their fused RRF score
        sorted_atom_ids = sorted(rrf_scores.keys(), key=lambda id: rrf_scores[id], reverse=True)
        
        # Create the final sorted list of (atom, score) tuples
        final_results = [(atom_id_map[atom_id], rrf_scores[atom_id]) for atom_id in sorted_atom_ids]
        
        return final_results

    def search(self, query: str, target_url: Optional[str] = None, top_n: int = 5) -> List[Tuple[Dict[str, Any], float]]:
        """
        Searches the KB using hybrid search (BM25 + Vector) and RRF.

        Args:
            query: The user's raw query.
            target_url: An optional URL to force-filter the search results.
            top_n: The number of top results to return *after* fusion.

        Returns:
            A list of (atom, score) tuples, sorted by relevance.
        """
        if not self.index_manager:
            return []

        # 1. Prepare query and filters
        cleaned_query = self._clean_query(query)
        if not cleaned_query:
            # If query is only filler words, vector search might still work
            cleaned_query = query 
            
        filter_metadata = {}
        if target_url:
            filter_metadata['url'] = target_url

        # 2. Perform both searches
        # Use a higher top_n for individual searches to provide more candidates for fusion
        search_top_n = top_n * 3 
        
        bm25_results = self.index_manager.search_bm25(
            query=cleaned_query,
            filter_metadata=filter_metadata or None,
            top_n=search_top_n
        )
        
        vector_results = self.index_manager.search_vectors(
            query=query, # Use original query for semantic search
            filter_metadata=filter_metadata or None,
            top_n=search_top_n
        )
        
        # 3. Fuse the results
        fused_results = self._reciprocal_rank_fusion([bm25_results, vector_results])
        
        return fused_results[:top_n]
