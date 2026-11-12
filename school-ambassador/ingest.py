"""Knowledge Base Ingestion & Embedding Pipeline.

Transforms markdown KB files into structure-aware chunks, generates dense
embeddings via the configured embedding model (Qwen3-Embedding-0.6B primary,
Nomic-embed-text-v1.5 fallback), and indexes them into ChromaDB using cosine distance.

Synchronous Python — no async/await.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb
import yaml
from sentence_transformers import SentenceTransformer

# Windows console encoding fix
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)


# ─── Configuration Loader ──────────────────────────────────────────
def load_config() -> dict:
    """Load configuration from config.yaml with backward compatibility."""
    config_path = BASE_DIR / "config.yaml"
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}


def load_hardware_tier() -> str:
    """Read hardware tier from hardware_profile.json (defaults to B)."""
    profile_path = BASE_DIR / "hardware_profile.json"
    try:
        with open(profile_path, "r", encoding="utf-8") as fh:
            profile = json.load(fh)
        return profile.get("tier", "B")
    except (FileNotFoundError, json.JSONDecodeError):
        return "B"


def get_embedding_model_name(cfg: dict) -> str:
    """Select embedding model name based on hardware tier or explicit config."""
    emb_cfg = cfg.get("embedding", {})
    configured = emb_cfg.get("model", "auto")
    if configured and configured != "auto":
        return configured

    tier = load_hardware_tier()
    if tier in ("A", "B"):
        return emb_cfg.get("primary", "Qwen/Qwen3-Embedding-0.6B")
    else:
        return emb_cfg.get("fallback", "nomic-ai/nomic-embed-text-v1.5")


def get_model_slug(model_name: str) -> str:
    """Derive a safe collection name slug from model identifier."""
    slug = model_name.lower().replace("/", "__").replace("-", "_").replace(".", "_")
    slug = re.sub(r"[^a-z0-9_]+", "", slug)
    return slug


def get_collection_name(model_name: str) -> str:
    """Get versioned Chroma collection name for a given model."""
    slug = get_model_slug(model_name)
    return f"school_kb__{slug}"


# ─── Structure-Aware Chunker ───────────────────────────────────────
class StructureAwareChunker:
    """Structure-aware chunker driven by markdown headings and config."""

    def __init__(self, cfg: dict) -> None:
        chunk_cfg = cfg.get("chunking", {})
        self.max_words = int(chunk_cfg.get("max_words", 150))
        self.overlap_words = int(chunk_cfg.get("overlap_words", 25))
        self.min_words = int(chunk_cfg.get("min_words", 20))
        self.school_name = cfg.get("school_name", "Oakridge International Academy")
        self.company_name = cfg.get("company_name", "Weguide")

    def chunk_file(self, file_path: Path, category: str, file_hash: str) -> List[Dict[str, Any]]:
        """Parse markdown file into structured chunks with display and embed representations.
        
        Supports both single consolidated files (with multiple H1 sections) and modular files.
        """
        file_path = Path(file_path).resolve()
        content = file_path.read_text(encoding="utf-8")
        try:
            rel_path = str(file_path.relative_to(BASE_DIR)).replace("\\", "/")
        except ValueError:
            rel_path = file_path.name

        # Split into H1 sections (if file has multiple # sections, or just 1)
        h1_sections = re.split(r"\n(?=# [^#])", content.strip())
        chunks: List[Dict[str, Any]] = []

        for h1_sec in h1_sections:
            sec_lines = h1_sec.strip().splitlines()
            if not sec_lines:
                continue

            h1 = ""
            for line in sec_lines:
                if line.startswith("# "):
                    h1 = line.lstrip("# ").strip()
                    break
            if not h1:
                h1 = file_path.stem.replace("_", " ").title()

            # Determine category: check H1 text, header lines, or file path
            sec_cat = category
            if "partnership" in h1.lower() or any("category: partnership" in l.lower() for l in sec_lines[:4]):
                sec_cat = "partnership"
            elif any("category: school" in l.lower() for l in sec_lines[:4]):
                sec_cat = "school"

            # Split into H2 sections within this H1 block
            raw_sections = re.split(r"\n(?=##\s+)", h1_sec)

            for raw_sec in raw_sections:
                if raw_sec.strip().startswith("# ") and not raw_sec.strip().startswith("## "):
                    continue  # Skip top-level header preamble

                h2_lines = raw_sec.strip().splitlines()
                if not h2_lines:
                    continue

                h2_match = re.match(r"^##\s+(.+)$", h2_lines[0].strip())
                if not h2_match:
                    continue
                h2 = h2_match.group(1).strip()

                questions: List[str] = []
                audience = "parent, student, teacher, visitor"
                body_lines: List[str] = []

                for line in h2_lines[1:]:
                    stripped = line.strip()
                    if stripped.lower().startswith("questions this answers:"):
                        q_part = stripped.split(":", 1)[1].strip()
                        questions.extend([q.strip() for q in q_part.split("|") if q.strip()])
                    elif stripped.lower().startswith("audience:"):
                        audience = stripped.split(":", 1)[1].strip()
                    elif stripped.lower().startswith("category:"):
                        continue
                    else:
                        body_lines.append(line)

                body = "\n".join(body_lines).strip()
                if not body:
                    continue

                prefix = self.company_name if sec_cat == "partnership" else self.school_name
                breadcrumb = f"{prefix} > {h1} > {h2}:"

                # Check for H3 subheadings if oversized or distinct sub-topics
                body_words = body.split()
                if len(body_words) <= self.max_words:
                    disp_text = f"{breadcrumb}\n\n{body}"
                    emb_text = disp_text
                    if questions:
                        emb_text += "\n\nQuestions this answers: " + " | ".join(questions)

                    chunks.append({
                        "source_file": rel_path,
                        "category": sec_cat,
                        "heading_path": f"{h1} > {h2}",
                        "section_title": h2,
                        "display_text": disp_text,
                        "embed_text": emb_text,
                        "word_count": len(disp_text.split()),
                        "audience": audience,
                        "file_hash": file_hash,
                        "has_questions": len(questions) > 0,
                        "questions": questions,
                    })
                else:
                    # Oversized: check for H3 subheadings first
                    h3_sections = re.split(r"\n(?=###\s+)", body)
                    if len(h3_sections) > 1:
                        for h3_sec in h3_sections[1:]:
                            h3_lines = h3_sec.strip().splitlines()
                            h3_title = h3_lines[0].lstrip("# ").strip()
                            h3_body = "\n".join(h3_lines[1:]).strip()
                            sub_breadcrumb = f"{prefix} > {h1} > {h2} > {h3_title}:"
                            sub_disp = f"{sub_breadcrumb}\n\n{h3_body}"
                            sub_emb = sub_disp
                            if questions:
                                sub_emb += "\n\nQuestions this answers: " + " | ".join(questions)

                            chunks.append({
                                "source_file": rel_path,
                                "category": sec_cat,
                                "heading_path": f"{h1} > {h2} > {h3_title}",
                                "section_title": h3_title,
                                "display_text": sub_disp,
                                "embed_text": sub_emb,
                                "word_count": len(sub_disp.split()),
                                "audience": audience,
                                "file_hash": file_hash,
                                "has_questions": len(questions) > 0,
                                "questions": questions,
                            })
                    else:
                        # Paragraph / sentence boundary sliding window
                        paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
                        cur_words: List[str] = []
                        part_idx = 1
                        for para in paragraphs:
                            p_words = para.split()
                            if len(cur_words) + len(p_words) <= self.max_words:
                                cur_words.extend(p_words)
                            else:
                                if cur_words:
                                    part_body = " ".join(cur_words)
                                    disp_text = f"{breadcrumb} (Part {part_idx})\n\n{part_body}"
                                    emb_text = disp_text
                                    if questions:
                                        emb_text += "\n\nQuestions this answers: " + " | ".join(questions)
                                    chunks.append({
                                        "source_file": rel_path,
                                        "category": sec_cat,
                                        "heading_path": f"{h1} > {h2} (Part {part_idx})",
                                        "section_title": f"{h2} (Part {part_idx})",
                                        "display_text": disp_text,
                                        "embed_text": emb_text,
                                        "word_count": len(disp_text.split()),
                                        "audience": audience,
                                        "file_hash": file_hash,
                                        "has_questions": len(questions) > 0,
                                        "questions": questions,
                                    })
                                    part_idx += 1
                                    cur_words = cur_words[-self.overlap_words:] + p_words
                                else:
                                    cur_words = p_words

                        if cur_words:
                            part_body = " ".join(cur_words)
                            disp_text = f"{breadcrumb} (Part {part_idx})\n\n{part_body}"
                            emb_text = disp_text
                            if questions:
                                emb_text += "\n\nQuestions this answers: " + " | ".join(questions)
                            chunks.append({
                                "source_file": rel_path,
                                "category": sec_cat,
                                "heading_path": f"{h1} > {h2} (Part {part_idx})",
                                "section_title": f"{h2} (Part {part_idx})",
                                "display_text": disp_text,
                                "embed_text": emb_text,
                                "word_count": len(disp_text.split()),
                                "audience": audience,
                                "file_hash": file_hash,
                                "has_questions": len(questions) > 0,
                                "questions": questions,
                            })


        # Priority 5: Merge small chunks (< min_words) with preceding chunk under same parent
        merged: List[Dict[str, Any]] = []
        for c in chunks:
            if merged and c["word_count"] < self.min_words:
                prev = merged[-1]
                if prev["source_file"] == c["source_file"] and (prev["word_count"] + c["word_count"]) <= self.max_words:
                    prev["display_text"] += f"\n\n{c['display_text']}"
                    prev["embed_text"] += f"\n\n{c['embed_text']}"
                    prev["word_count"] = len(prev["display_text"].split())
                    continue
            merged.append(c)

        return merged


# ─── Embedding Helper ──────────────────────────────────────────────
def encode_documents(model: SentenceTransformer, model_name: str, texts: List[str]) -> List[List[float]]:
    """Encode texts using model-specific document formatting and normalization."""
    is_nomic = "nomic" in model_name.lower()

    if is_nomic:
        formatted = [f"search_document: {t}" for t in texts]
    else:
        formatted = texts

    embeddings = model.encode(formatted, normalize_embeddings=True, show_progress_bar=False)
    return [e.tolist() for e in embeddings]


# ─── Ingestion Routine ─────────────────────────────────────────────
def run_ingest(dry_run: bool = False, rebuild: bool = False) -> int:
    """Execute ingestion pipeline or print report on dry-run."""
    cfg = load_config()
    retrieval_cfg = cfg.get("retrieval", cfg.get("rag", {}))
    kb_dir = BASE_DIR / retrieval_cfg.get("kb_dir", "kb")
    chroma_dir = BASE_DIR / retrieval_cfg.get("chroma_dir", "chroma_db")
    model_name = get_embedding_model_name(cfg)
    collection_name = get_collection_name(model_name)

    print("════════════════════════════════════════════════════════════")
    print("  AI School Ambassador — Structure-Aware Knowledge Ingest")
    print("════════════════════════════════════════════════════════════")
    print(f"  KB Directory:     {kb_dir}")
    print(f"  Embedding Model:  {model_name}")
    print(f"  Collection Name:  {collection_name}")
    print(f"  Distance Space:   cosine (hnsw:space)")
    print(f"  Action:           {'REPORT DRY-RUN' if dry_run else ('REBUILD COLLECTION' if rebuild else 'INCREMENTAL INDEX')}")
    print("────────────────────────────────────────────────────────────\n")

    if not kb_dir.is_dir():
        print(f"❌  KB directory not found: {kb_dir}")
        return 1

    # Find all .md files
    kb_files = sorted(list(kb_dir.rglob("*.md")))
    if not kb_files:
        print(f"❌  No markdown files found in {kb_dir}")
        return 1

    chunker = StructureAwareChunker(cfg)
    all_chunks: List[Dict[str, Any]] = []
    file_stats: Dict[str, int] = {}

    for fpath in kb_files:
        content = fpath.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        category = "partnership" if "partnership" in str(fpath).lower() else "school"
        chunks = chunker.chunk_file(fpath, category, file_hash)
        file_stats[fpath.name] = len(chunks)
        all_chunks.extend(chunks)

    # Exact-hash deduplication on normalized display_text
    seen_hashes = set()
    deduped_chunks: List[Dict[str, Any]] = []
    dropped_count = 0

    for chunk in all_chunks:
        norm_text = re.sub(r"\s+", " ", chunk["display_text"]).strip().lower()
        chunk_hash = hashlib.sha256(norm_text.encode("utf-8")).hexdigest()
        if chunk_hash in seen_hashes:
            dropped_count += 1
            continue
        seen_hashes.add(chunk_hash)
        chunk["chunk_index"] = len(deduped_chunks)
        chunk["embedding_model"] = model_name
        deduped_chunks.append(chunk)

    word_counts = [c["word_count"] for c in deduped_chunks]
    min_w = min(word_counts) if word_counts else 0
    max_w = max(word_counts) if word_counts else 0
    avg_w = sum(word_counts) / len(word_counts) if word_counts else 0
    no_q_chunks = [c for c in deduped_chunks if not c["has_questions"]]
    oversized = [c for c in deduped_chunks if c["word_count"] > chunker.max_words]
    undersized = [c for c in deduped_chunks if c["word_count"] < chunker.min_words]

    # Print Summary Report
    print(f"📊  Chunking Statistics:")
    print(f"   • Total Files Processed:    {len(kb_files)}")
    print(f"   • Total Chunks Extracted:   {len(all_chunks)}")
    print(f"   • Exact-Hash Dedup Dropped: {dropped_count}")
    print(f"   • Active Unique Chunks:     {len(deduped_chunks)}")
    print(f"   • Word Count Range:         min={min_w}, max={max_w}, mean={avg_w:.1f} words")
    print(f"   • Oversized (>150 words):   {len(oversized)}")
    print(f"   • Undersized (<20 words):   {len(undersized)}")
    print(f"   • Missing Questions Lines:  {len(no_q_chunks)}\n")

    print(f"📁  Per-File Distribution:")
    for fname, count in sorted(file_stats.items()):
        print(f"   • {fname:25s}: {count:2d} chunks")
    print()

    if dry_run:
        print("✅  Dry-run report complete. No changes written to ChromaDB.")
        return 0

    # Ingest into ChromaDB
    print(f"⚙️   Initializing ChromaDB PersistentClient at {chroma_dir}…")
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))

    if rebuild:
        try:
            client.delete_collection(name=collection_name)
            print(f"   🗑️  Dropped existing collection: {collection_name}")
        except Exception:
            pass

    # Ensure offline mode for loading cached model
    os.environ["HF_HUB_OFFLINE"] = "1"
    print(f"🤖  Loading embedding model: {model_name}…")
    try:
        embed_model = SentenceTransformer(
            model_name,
            trust_remote_code=True,
            local_files_only=True,
        )
    except Exception as exc:
        print(f"⚠️   Offline load failed ({exc}), attempting with hub…")
        os.environ.pop("HF_HUB_OFFLINE", None)
        embed_model = SentenceTransformer(
            model_name,
            trust_remote_code=True,
        )

    # Encode documents
    print(f"⚡  Generating embeddings for {len(deduped_chunks)} chunks…")
    t0 = time.time()
    embed_texts = [c["embed_text"] for c in deduped_chunks]
    embeddings = encode_documents(embed_model, model_name, embed_texts)
    emb_dim = len(embeddings[0]) if embeddings else 1024
    elapsed = time.time() - t0
    print(f"   ✅  Generated {len(embeddings)} embeddings ({emb_dim}-d) in {elapsed:.2f}s ({elapsed*1000/len(embeddings):.1f}ms/chunk)")

    # Create/get Chroma collection with cosine distance
    col_metadata = {
        "hnsw:space": "cosine",
        "embedding_model": model_name,
        "dimension": emb_dim,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata=col_metadata,
    )

    ids = [f"{c['source_file']}::chunk_{c['chunk_index']}" for c in deduped_chunks]
    documents = [c["display_text"] for c in deduped_chunks]
    metadatas = [
        {
            "source_file": c["source_file"],
            "category": c["category"],
            "heading_path": c["heading_path"],
            "section_title": c["section_title"],
            "chunk_index": c["chunk_index"],
            "word_count": c["word_count"],
            "audience": c["audience"],
            "file_hash": c["file_hash"],
            "embedding_model": model_name,
            "has_questions": c["has_questions"],
        }
        for c in deduped_chunks
    ]

    collection.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    print(f"\n🎉  Successfully indexed {len(ids)} chunks into '{collection_name}' (space: cosine).")
    return 0


# ─── Main CLI Entrypoint ──────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest KB markdown into ChromaDB")
    parser.add_argument("--report", action="store_true", help="Dry run: print chunking report without writing to Chroma")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild: drop existing collection and re-index from scratch")
    args = parser.parse_args()

    sys.exit(run_ingest(dry_run=args.report, rebuild=args.rebuild))
