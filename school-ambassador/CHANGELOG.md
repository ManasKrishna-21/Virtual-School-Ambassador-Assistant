# CHANGELOG — AI School Ambassador Retrieval Layer Overhaul

## Summary of Changes

All changes are **confined to the retrieval layer, knowledge base files, configuration, and tests**.  
The voice pipeline files (`pipeline.py`, `stt_client.py`, `tts_client.py`, `hardware_io.py`, `audio_recorder.py`) are **unchanged** except for the notes below.

---

## Changed Files

### `config.yaml`

| Change | Detail |
|--------|--------|
| Added `chunking:` section | `max_words: 150`, `overlap_words: 25`, `min_words: 20` |
| Added `embedding:` section | `model: auto`, `primary: Qwen/Qwen3-Embedding-0.6B`, `fallback: nomic-ai/nomic-embed-text-v1.5` |
| Added `retrieval:` section | `k: 3`, `min_similarity: 0.50`, `chroma_dir`, `kb_dir`, `glossary_path`, `hybrid.enabled: false` |
| Renamed `score_floor` → `min_similarity` | Old `rag.score_floor` retained as backward-compat alias |
| Default threshold changed | `0.35` → `0.50` (pre-calibration; run `calibrate_threshold.py --apply` to tune) |

> **Breaking change**: Any code reading `cfg["rag"]["score_floor"]` should migrate to `cfg["retrieval"]["min_similarity"]`. The old key still works via the `rag:` backward-compat block.

---

### `ingest.py` — Full Rewrite

| Change | Detail |
|--------|--------|
| Chunker class | Replaced `_split_into_chunks()` function with `StructureAwareChunker` class |
| Structure-aware chunking | Parses H1 → H2 → H3 hierarchy; splits oversized sections by paragraph boundary then sliding window |
| `display_text` / `embed_text` | Each chunk has two representations: display (no question lines) and embed (with question lines appended) |
| Breadcrumb format | `"Oakridge International Academy > Fee Structure > Late Fee Penalties:"` |
| Exact-hash deduplication | Replaced 0.95 cosine dedup with normalized SHA256 hash comparison |
| Chroma collection name | Now uses model slug: `school_kb__qwen__qwen3_embedding_0_6b` (was `school_kb`) |
| Distance space | Changed from `hnsw:space l2` → `hnsw:space cosine` |
| Similarity | Changed from `1/(1+dist)` (L2 approx) → `1 - dist` (exact cosine similarity) |
| Collection metadata | Stores `embedding_model`, `dimension`, `ingested_at` |
| CLI flags | `--reindex` renamed to `--rebuild`; `--report` added for dry-run |
| Hardware tier selection | Auto-selects primary/fallback model from `hardware_profile.json` |
| HF offline flag | Set `HF_HUB_OFFLINE=1` after model loaded; removed during first-download if not cached |

---

### `retriever.py` — Full Rewrite

| Change | Detail |
|--------|--------|
| Cosine similarity | Changed from `1/(1+L2_dist)` → `1 - cosine_dist` (correct for cosine space) |
| Threshold key | Reads `retrieval.min_similarity` (falls back to `rag.score_floor`) |
| Model mismatch detection | Refuses to query if collection model ≠ configured model; prints clear error |
| Glossary normalization | Applied before embedding and BM25 via `glossary.yaml` |
| `audience` parameter | Now logged; category-based tie-break implemented |
| Qwen3 query encoding | Uses `prompt_name="query"` (with instruction fallback) |
| Optional BM25 hybrid | `retrieval.hybrid.enabled: false` by default; uses `rank_bm25`, RRF k=60 |
| `last_sources` enriched | Now includes `section_title`, `heading_path`, `word_count`, `similarity` |
| Collection name | Reads versioned slug matching ingest.py |

---

### `kb/` — Restructured

| Change | Detail |
|--------|--------|
| Backup created | `kb_backup/` contains original files |
| Old files removed | `kb/knowledge_base.txt` and `kb/knowledge_base_optimized.md` removed |
| New structure | `kb/school/` (10 files) + `kb/partnership/` (1 file) |
| Files created | `curriculum.md`, `admissions.md`, `activities.md`, `calendar.md`, `facilities.md`, `safety.md`, `student_life.md`, `staff.md`, `fees.md`, `faq.md`, `weguide.md` |
| Format | Each file: H1 title, `## Topic` sections, `Questions this answers:` line per H2, plain prose body |

---

### `glossary.yaml` — New File

Maps canonical terms to STT misrecognitions/variants. Applied before embedding at query time.

---

### `tests/question_bank.jsonl` — Expanded

| Change | Detail |
|--------|--------|
| 11 entries → 68 entries | Expanded to 47 in-scope + 20 out-of-scope + 2 red-team + 2 STT-garbled |
| Added fields | `expected_source_file`, `expected_heading` |
| Fixed keyword mismatches | Corrected "7:30" (gates open) and contact email mismatches from old entries |

---

### `tests/test_retrieval.py` — Rewritten

- In-scope tests: check `expected_heading` present in top-3 chunk `heading_path`/`section_title`
- Fallback tests: assert retriever returns `None`
- Decline tests: assert retriever similarity < 0.70
- Chunker unit tests: chunk count in range, max/min words, breadcrumbs, questions in embed only, fee dedup, model mismatch detection

---

### New Files

| File | Purpose |
|------|---------|
| `calibrate_threshold.py` | Find optimal `min_similarity` threshold; `--apply` writes to config.yaml |
| `eval_retrieval.py` | 5-config evaluation run; writes `eval_report.md` |
| `kb_review.md` | Unresolved facts and items needing owner confirmation |
| `glossary.yaml` | STT normalization glossary |

---

## Unchanged Files (Voice Pipeline)

The following files were **not modified**:
- `pipeline.py` — calls `retriever.query(question, audience)` and `retriever.last_sources` (interface unchanged)
- `stt_client.py`
- `tts_client.py`
- `hardware_io.py`
- `audio_recorder.py`
- `audience_selector.py`
- `llm_client.py`
- `guardrails.py`
- `logger.py`
- `freshness_check.py`

> `pipeline.py` uses `retriever.last_sources` — this property is preserved and now returns richer metadata (adds `section_title`, `heading_path`, `word_count`, `similarity`). Callers that only read `source_file`, `category`, or `similarity` continue to work without changes.

---

## Rollback Instructions

To revert to the old retrieval layer:
1. Restore `kb/` from `kb_backup/`: `Copy-Item kb_backup\* kb\ -Recurse`
2. Restore old `ingest.py` and `retriever.py` from git: `git checkout HEAD~1 -- ingest.py retriever.py`
3. Revert `config.yaml` `rag.score_floor` and `rag.embedding_model` to prior values
4. Run `python ingest.py --rebuild` (old version)

---

## Migration Checklist

- [x] `kb_backup/` created
- [x] KB split into 11 structured per-topic files
- [x] `config.yaml` updated with `chunking:`, `embedding:`, `retrieval:` sections
- [x] `ingest.py` rewritten (structure-aware chunker, cosine space, breadcrumbs)
- [x] `retriever.py` rewritten (glossary, cosine similarity, mismatch detection, BM25 stub)
- [x] `glossary.yaml` created
- [x] `question_bank.jsonl` expanded to 68 questions
- [x] `test_retrieval.py` updated with heading-based assertions + chunker tests
- [x] `calibrate_threshold.py` created
- [x] `eval_retrieval.py` created
- [x] `kb_review.md` created
- [x] ChromaDB rebuilt with 56 chunks (cosine space, Qwen3-Embedding-0.6B 1024-d)
- [ ] `calibrate_threshold.py --apply` — run after index is verified
- [ ] `eval_retrieval.py` — run to confirm hit@3 ≥ 90%, FA ≤ 10%

