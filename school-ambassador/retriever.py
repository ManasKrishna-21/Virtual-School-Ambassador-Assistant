"""Retriever — structure-aware RAG retrieval with glossary normalization.

Features:
  - Glossary-based STT misrecognition normalization (glossary.yaml)
  - Cosine similarity via ChromaDB (hnsw:space cosine)
  - Calibrated similarity threshold gate (retrieval.min_similarity)
  - Optional hybrid BM25 + dense reciprocal-rank fusion (off by default)
  - Model mismatch detection: refuses to query if collection model differs

Public interface (unchanged from prior version):
  retriever = Retriever()
  chunks = retriever.query(question, audience="visitor")  -> Optional[List[str]]
  sources = retriever.last_sources                       -> List[dict]

Synchronous Python — no async/await.
"""

from __future__ import annotations

import os
import re
import sys
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
import yaml

# Windows console encoding fix
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# Module-level singletons (lazy-loaded)
_embed_model = None
_chroma_client = None
_chroma_collection = None
_bm25_index = None
_bm25_corpus: List[str] = []
_bm25_chunk_ids: List[str] = []


# ─── Configuration Helpers ─────────────────────────────────────────
def _load_config() -> dict:
    config_path = BASE_DIR / "config.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def _load_glossary(glossary_path: str) -> Dict[str, List[str]]:
    """Load the STT normalization glossary."""
    path = BASE_DIR / glossary_path
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("glossary", {})
    except FileNotFoundError:
        return {}


def _load_hardware_tier() -> str:
    """Read hardware tier from hardware_profile.json (defaults to B)."""
    profile_path = BASE_DIR / "hardware_profile.json"
    try:
        with open(profile_path, "r", encoding="utf-8") as fh:
            profile = json.load(fh)
        return profile.get("tier", "B")
    except (FileNotFoundError, json.JSONDecodeError):
        return "B"


def _get_embedding_model_name(cfg: dict) -> str:
    """Select embedding model name based on hardware tier or explicit config."""
    emb_cfg = cfg.get("embedding", {})
    configured = emb_cfg.get("model", "auto")
    if configured and configured != "auto":
        return configured
    tier = _load_hardware_tier()
    if tier in ("A", "B"):
        return emb_cfg.get("primary", "Qwen/Qwen3-Embedding-0.6B")
    else:
        return emb_cfg.get("fallback", "nomic-ai/nomic-embed-text-v1.5")


def _get_model_slug(model_name: str) -> str:
    slug = model_name.lower().replace("/", "__").replace("-", "_").replace(".", "_")
    slug = re.sub(r"[^a-z0-9_]+", "", slug)
    return slug


def _get_collection_name(model_name: str) -> str:
    return f"school_kb__{_get_model_slug(model_name)}"


# ─── Glossary Normalization ────────────────────────────────────────
def _normalize_query(text: str, glossary: Dict[str, List[str]]) -> str:
    """Replace STT misrecognitions with canonical terms (case-insensitive whole-word)."""
    if not glossary:
        return text

    result = text
    for canonical, variants in glossary.items():
        for variant in variants:
            # Case-insensitive whole-word/phrase replacement
            pattern = r"(?<!\w)" + re.escape(variant) + r"(?!\w)"
            result = re.sub(pattern, canonical, result, flags=re.IGNORECASE)

    if result != text:
        print(f"  [Glossary] Normalized: '{text}' -> '{result}'")
    return result


# ─── Embedding Encode Query ────────────────────────────────────────
def _encode_query(model, model_name: str, query_text: str) -> List[float]:
    """Encode a query string using model-specific instruction format."""
    is_nomic = "nomic" in model_name.lower()
    is_qwen = "qwen" in model_name.lower()

    if is_nomic:
        formatted = f"search_query: {query_text}"
        emb = model.encode(formatted, normalize_embeddings=True)
    elif is_qwen:
        # Qwen3-Embedding: use prompt_name="query" or manual instruction format
        instruction = (
            "Instruct: Given a question asked by a visitor to a school kiosk, "
            "retrieve the school information that answers it\nQuery: "
        )
        try:
            emb = model.encode(
                query_text,
                prompt_name="query",
                normalize_embeddings=True,
            )
        except (TypeError, ValueError):
            emb = model.encode(
                instruction + query_text,
                normalize_embeddings=True,
            )
    else:
        emb = model.encode(query_text, normalize_embeddings=True)

    return emb.tolist()


# ─── BM25 Hybrid Index ─────────────────────────────────────────────
def _build_bm25_index(documents: List[str], chunk_ids: List[str]):
    """Build an in-memory BM25 index over display_text corpus."""
    global _bm25_index, _bm25_corpus, _bm25_chunk_ids
    try:
        from rank_bm25 import BM25Okapi
        tokenized = [doc.lower().split() for doc in documents]
        _bm25_index = BM25Okapi(tokenized)
        _bm25_corpus = documents
        _bm25_chunk_ids = chunk_ids
    except ImportError:
        print("  [Warning] rank_bm25 not installed; BM25 hybrid disabled.")
        _bm25_index = None


def _bm25_scores(query_tokens: List[str]) -> Dict[str, float]:
    """Return BM25 scores as {chunk_id: score}."""
    if _bm25_index is None:
        return {}
    scores = _bm25_index.get_scores(query_tokens)
    return {_bm25_chunk_ids[i]: float(scores[i]) for i in range(len(_bm25_chunk_ids))}


def _reciprocal_rank_fusion(
    dense_results: List[Dict], bm25_scores_map: Dict[str, float], k: int = 60
) -> List[Dict]:
    """Fuse dense and BM25 rankings via reciprocal rank fusion (RRF)."""
    dense_ranked = {r["id"]: (i + 1) for i, r in enumerate(dense_results)}
    bm25_ranked_ids = sorted(bm25_scores_map, key=lambda x: bm25_scores_map[x], reverse=True)
    bm25_ranked = {cid: (i + 1) for i, cid in enumerate(bm25_ranked_ids)}

    all_ids = set(dense_ranked) | set(bm25_ranked)
    rrf_scores = {}
    for cid in all_ids:
        dense_rank = dense_ranked.get(cid, len(dense_ranked) + 100)
        bm25_rank = bm25_ranked.get(cid, len(bm25_ranked) + 100)
        rrf_scores[cid] = 1.0 / (k + dense_rank) + 1.0 / (k + bm25_rank)

    # Rebuild result list sorted by RRF
    id_to_result = {r["id"]: r for r in dense_results}
    sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
    fused = []
    for cid in sorted_ids:
        if cid in id_to_result:
            r = id_to_result[cid]
            r["rrf_score"] = rrf_scores[cid]
            fused.append(r)
    return fused


# ─── Main Retriever Class ──────────────────────────────────────────
class Retriever:
    """Synchronous, lazy-loading cosine-similarity RAG retriever.

    Backward-compatible public interface:
        chunks = retriever.query(question, audience="visitor")
        sources = retriever.last_sources
    """

    def __init__(self) -> None:
        cfg = _load_config()
        ret_cfg = cfg.get("retrieval", cfg.get("rag", {}))

        self._k: int = int(ret_cfg.get("k", 3))
        self._min_similarity: float = float(
            ret_cfg.get("min_similarity", ret_cfg.get("score_floor", 0.50))
        )
        self._model_name: str = _get_embedding_model_name(cfg)
        self._collection_name: str = _get_collection_name(self._model_name)
        self._chroma_dir: str = str(BASE_DIR / ret_cfg.get("chroma_dir", "chroma_db"))

        glossary_path = ret_cfg.get("glossary_path", "glossary.yaml")
        self._glossary: Dict[str, List[str]] = _load_glossary(glossary_path)

        hybrid_cfg = ret_cfg.get("hybrid", {})
        self._hybrid_enabled: bool = bool(hybrid_cfg.get("enabled", False))
        self._rrf_k: int = int(hybrid_cfg.get("bm25_k", 60))

        self._fallback_message: str = (
            cfg.get("guardrails", {})
            .get("fallback_message", "I don't have that information -- please check with the school office.")
        )

        self._last_sources: List[Dict] = []

    def _load_model_and_collection(self):
        """Lazy-load the embedding model and Chroma collection (once per process)."""
        global _embed_model, _chroma_client, _chroma_collection

        if _embed_model is None:
            print(f"  [Retriever] Loading embedding model: {self._model_name}…")
            from sentence_transformers import SentenceTransformer
            os.environ["HF_HUB_OFFLINE"] = "1"
            try:
                _embed_model = SentenceTransformer(
                    self._model_name,
                    trust_remote_code=True,
                    local_files_only=True,
                )
            except Exception as exc:
                print(f"  [Retriever] Offline load failed ({exc}). Trying with network…")
                os.environ.pop("HF_HUB_OFFLINE", None)
                _embed_model = SentenceTransformer(
                    self._model_name,
                    trust_remote_code=True,
                )

        if _chroma_client is None:
            _chroma_client = chromadb.PersistentClient(path=self._chroma_dir)

        if _chroma_collection is None:
            try:
                _chroma_collection = _chroma_client.get_collection(self._collection_name)
            except Exception:
                _chroma_collection = None

            if _chroma_collection is None:
                print(f"  [Retriever] WARNING: Collection '{self._collection_name}' not found.")
                print("  Run: python ingest.py --rebuild")
                return False

            # Model mismatch detection
            col_meta = _chroma_collection.metadata or {}
            col_model = col_meta.get("embedding_model", "")
            if col_model and col_model != self._model_name:
                raise RuntimeError(
                    f"[Retriever] Model mismatch! Collection was indexed with '{col_model}' "
                    f"but configured model is '{self._model_name}'. "
                    f"Run: python ingest.py --rebuild"
                )

            # Build BM25 index if hybrid enabled
            if self._hybrid_enabled:
                print("  [Retriever] Building BM25 hybrid index…")
                all_items = _chroma_collection.get(include=["documents", "metadatas"])
                docs = all_items.get("documents", [])
                ids = all_items.get("ids", [])
                _build_bm25_index(docs, ids)

        return True

    def query(self, question: str, audience: str = "visitor") -> Optional[List[str]]:
        """Retrieve top-k chunks for a question.

        Returns a list of display_text strings, or None if no chunk
        passes the similarity threshold (triggers the fallback line in pipeline).
        """
        self._last_sources = []

        if not self._load_model_and_collection():
            return None

        # Glossary normalization
        normalized_q = _normalize_query(question, self._glossary)

        # Encode query
        q_embedding = _encode_query(_embed_model, self._model_name, normalized_q)

        # Dense search — always fetch enough results for RRF or direct use
        n_results = self._k * 3 if self._hybrid_enabled else self._k
        try:
            results = _chroma_collection.query(
                query_embeddings=[q_embedding],
                n_results=n_results,
                include=["documents", "distances", "metadatas"],
            )
        except Exception as exc:
            print(f"  [Retriever] ChromaDB query error: {exc}")
            return None

        docs = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        ids = results.get("ids", [[]])[0] if results.get("ids") else [str(i) for i in range(len(docs))]

        # Convert cosine distances to similarities (cosine distance ∈ [0,2], similarity = 1 - distance)
        dense_items = []
        for doc, dist, meta, cid in zip(docs, distances, metadatas, ids):
            sim = 1.0 - float(dist)
            dense_items.append({"id": cid, "document": doc, "similarity": sim, "metadata": meta})

        # Hybrid BM25 RRF fusion (optional)
        if self._hybrid_enabled and _bm25_index is not None:
            query_tokens = normalized_q.lower().split()
            bm25_map = _bm25_scores(query_tokens)
            dense_items = _reciprocal_rank_fusion(dense_items, bm25_map, k=self._rrf_k)

        # Similarity threshold gate (applied on dense similarity, not RRF score)
        passed = [
            item for item in dense_items
            if item.get("similarity", 0.0) >= self._min_similarity
        ]

        # If hybrid: re-sort by similarity for threshold gate, then take top-k
        passed.sort(key=lambda x: x.get("similarity", 0.0), reverse=True)
        top_k = passed[: self._k]

        if not top_k:
            print(f"  [Retriever] No chunks passed threshold ({self._min_similarity:.2f}).")
            return None

        chunks = [item["document"] for item in top_k]
        self._last_sources = [
            {
                "source_file": item["metadata"].get("source_file", ""),
                "category": item["metadata"].get("category", ""),
                "section_title": item["metadata"].get("section_title", ""),
                "heading_path": item["metadata"].get("heading_path", ""),
                "similarity": round(item["similarity"], 4),
                "word_count": item["metadata"].get("word_count", 0),
            }
            for item in top_k
        ]

        return chunks

    @property
    def last_sources(self) -> List[Dict]:
        """Metadata for the chunks returned by the most recent query()."""
        return self._last_sources

    def check_index_exists(self) -> bool:
        """Return True if the expected Chroma collection exists and is non-empty."""
        ok = self._load_model_and_collection()
        if not ok or _chroma_collection is None:
            return False
        count = _chroma_collection.count()
        return count > 0
