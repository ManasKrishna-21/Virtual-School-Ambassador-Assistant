"""calibrate_threshold.py — Find the optimal retrieval similarity threshold.

Computes best-chunk cosine similarity for every question in question_bank.jsonl,
reports in-scope and out-of-scope distributions, and proposes a min_similarity
value that achieves:
  - false-accept rate (out-of-scope questions that pass) ≤ 10%
  - maximises in-scope recall

Usage:
    python calibrate_threshold.py                  # print analysis only
    python calibrate_threshold.py --apply          # write best threshold to config.yaml

Synchronous Python — no async/await.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

# Windows console encoding fix
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)

# Ensure HF offline flag is set (models are already cached)
os.environ["HF_HUB_OFFLINE"] = "1"


def load_config() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_question_bank() -> List[Dict[str, Any]]:
    qb_path = BASE_DIR / "tests" / "question_bank.jsonl"
    entries = []
    with open(qb_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def get_best_similarity(retriever, question: str) -> float:
    """Return the highest cosine similarity across all returned chunks (0 if none)."""
    import chromadb
    from sentence_transformers import SentenceTransformer
    from retriever import _encode_query, _normalize_query

    cfg = load_config()
    ret_cfg = cfg.get("retrieval", cfg.get("rag", {}))
    chroma_dir = str(BASE_DIR / ret_cfg.get("chroma_dir", "chroma_db"))
    model_name = retriever._model_name
    glossary = retriever._glossary
    collection_name = retriever._collection_name

    client = chromadb.PersistentClient(path=chroma_dir)
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        return 0.0

    normalized_q = _normalize_query(question, glossary)
    q_emb = _encode_query(retriever._embed_model_instance, model_name, normalized_q)

    try:
        results = collection.query(
            query_embeddings=[q_emb],
            n_results=1,
            include=["distances"],
        )
        distances = results.get("distances", [[]])[0]
        if distances:
            return 1.0 - float(distances[0])
    except Exception:
        pass
    return 0.0


class QuickRetriever:
    """Minimal retriever wrapper for calibration (no threshold)."""
    def __init__(self, cfg: dict) -> None:
        import chromadb
        from sentence_transformers import SentenceTransformer
        from retriever import _get_embedding_model_name, _get_collection_name

        self._model_name = _get_embedding_model_name(cfg)
        self._collection_name = _get_collection_name(self._model_name)
        ret_cfg = cfg.get("retrieval", cfg.get("rag", {}))
        chroma_dir = str(BASE_DIR / ret_cfg.get("chroma_dir", "chroma_db"))
        from retriever import _load_glossary
        self._glossary = _load_glossary(ret_cfg.get("glossary_path", "glossary.yaml"))

        print(f"  Loading embedding model: {self._model_name}…")
        self._embed_model_instance = SentenceTransformer(
            self._model_name, trust_remote_code=True, local_files_only=True
        )

        self._client = chromadb.PersistentClient(path=chroma_dir)
        self._collection = self._client.get_collection(self._collection_name)

    def best_similarity(self, question: str) -> float:
        from retriever import _normalize_query, _encode_query
        norm_q = _normalize_query(question, self._glossary)
        q_emb = _encode_query(self._embed_model_instance, self._model_name, norm_q)
        try:
            results = self._collection.query(
                query_embeddings=[q_emb],
                n_results=1,
                include=["distances"],
            )
            distances = results.get("distances", [[]])[0]
            if distances:
                return 1.0 - float(distances[0])
        except Exception:
            pass
        return 0.0


def main(apply_flag: bool = False) -> None:
    print("══════════════════════════════════════════════════════════")
    print("  AI School Ambassador — Retrieval Threshold Calibration")
    print("══════════════════════════════════════════════════════════\n")

    cfg = load_config()
    entries = load_question_bank()

    print(f"  Question bank entries: {len(entries)}")

    qr = QuickRetriever(cfg)

    in_scope_sims: List[float] = []
    out_scope_sims: List[float] = []

    print("\n  Evaluating questions…")
    for i, entry in enumerate(entries):
        q = entry["question"]
        qtype = entry.get("expected_type", "grounded")
        sim = qr.best_similarity(q)

        if qtype in ("grounded",):
            in_scope_sims.append(sim)
        elif qtype in ("fallback", "decline"):
            out_scope_sims.append(sim)

        if (i + 1) % 10 == 0:
            print(f"  Processed {i + 1}/{len(entries)} questions…")

    print(f"\n  In-scope questions:  {len(in_scope_sims)}")
    print(f"  Out-of-scope questions: {len(out_scope_sims)}")

    if not in_scope_sims or not out_scope_sims:
        print("  ERROR: Need both in-scope and out-of-scope questions.")
        return

    in_scope_sims.sort()
    out_scope_sims.sort()

    in_scope_min = min(in_scope_sims)
    in_scope_max = max(in_scope_sims)
    in_scope_avg = sum(in_scope_sims) / len(in_scope_sims)
    out_scope_min = min(out_scope_sims)
    out_scope_max = max(out_scope_sims)
    out_scope_avg = sum(out_scope_sims) / len(out_scope_sims)

    print(f"\n  In-scope similarity:   min={in_scope_min:.3f}, max={in_scope_max:.3f}, avg={in_scope_avg:.3f}")
    print(f"  Out-of-scope similarity: min={out_scope_min:.3f}, max={out_scope_max:.3f}, avg={out_scope_avg:.3f}")

    # Find threshold that minimises false-accept rate to ≤ 10% while maximising in-scope recall
    print("\n  Threshold Analysis:")
    print(f"  {'Threshold':>10} | {'In-Scope Recall':>15} | {'False-Accept Rate':>17}")
    print(f"  {'-'*10}-+-{'-'*15}-+-{'-'*17}")

    best_threshold = 0.5
    best_score = -1.0

    for t_int in range(10, 95, 5):
        t = t_int / 100.0
        in_recall = sum(1 for s in in_scope_sims if s >= t) / len(in_scope_sims)
        fa_rate = sum(1 for s in out_scope_sims if s >= t) / len(out_scope_sims)
        print(f"  {t:>10.2f} | {in_recall:>14.1%} | {fa_rate:>16.1%}  {'<-- ACCEPTABLE' if fa_rate <= 0.10 else ''}")

        if fa_rate <= 0.10:
            score = in_recall - fa_rate
            if score > best_score:
                best_score = score
                best_threshold = t

    print(f"\n  Recommended threshold: {best_threshold:.2f}")
    print(f"  (false-accept <= 10%, max in-scope recall)")

    current_cfg = load_config()
    current_thresh = current_cfg.get("retrieval", {}).get("min_similarity", 0.5)
    print(f"  Current config threshold: {current_thresh}")

    if apply_flag:
        with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as fh:
            config_text = fh.read()

        # Update retrieval.min_similarity
        import re
        config_text = re.sub(
            r"(min_similarity\s*:\s*)[0-9.]+",
            f"\\g<1>{best_threshold:.2f}",
            config_text,
        )
        # Also update rag.score_floor for backward compat
        config_text = re.sub(
            r"(score_floor\s*:\s*)[0-9.]+",
            f"\\g<1>{best_threshold:.2f}",
            config_text,
        )
        with open(BASE_DIR / "config.yaml", "w", encoding="utf-8") as fh:
            fh.write(config_text)
        print(f"  Applied threshold {best_threshold:.2f} to config.yaml")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Calibrate retrieval similarity threshold")
    parser.add_argument("--apply", action="store_true", help="Write best threshold to config.yaml")
    args = parser.parse_args()
    main(apply_flag=args.apply)

