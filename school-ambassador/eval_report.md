# Retrieval Layer Evaluation Report

- **Embedding Model**: `Qwen/Qwen3-Embedding-0.6B` (1024-d, cosine distance)
- **Collection**: `school_kb__qwen__qwen3_embedding_0_6b` (56 chunks)
- **Total Benchmark Questions**: 71
- **In-Scope Questions**: 49
- **Out-of-Scope Questions**: 22

## Performance Across Configurations

| Configuration | Threshold | Hybrid BM25 | Hit@1 | Hit@3 | MRR | False-Accept | False-Reject | Avg Latency |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Config A** | 0.40 | False | 93.9% | **95.9%** | 0.949 | **36.4%** | 2.0% | 1102 ms |
| **Config B** 🌟 **Recommended** | 0.50 | False | 91.8% | **93.9%** | 0.929 | **9.1%** | 4.1% | 1102 ms |
| **Config C** | 0.60 | False | 57.1% | **57.1%** | 0.571 | **0.0%** | 42.9% | 1102 ms |
| **Config D** | 0.70 | False | 22.4% | **22.4%** | 0.224 | **0.0%** | 77.6% | 1102 ms |
| **Config E** | 0.50 | True | 91.8% | **93.9%** | 0.929 | **9.1%** | 4.1% | 1102 ms |

## Acceptance Criteria Verification

- **In-scope Hit@3 >= 90%**: Target achieved (93.9% >= 90%)
- **Out-of-scope False-Accept <= 10%**: Target achieved (9.1% <= 10%)
- **Glossary Normalization**: Verified (correctly canonicalizes STT variations such as 'we guide', 'p t m', 'oak ridge', and faculty names)
- **Model Mismatch Protection**: Enforced at startup and runtime
- **Chunk Word Limits**: All 56 chunks between 39 and 147 words (max limit 150 words)
