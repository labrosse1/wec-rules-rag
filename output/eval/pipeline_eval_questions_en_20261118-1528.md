# Retrieval evaluation – full pipeline 

- Date: 2026-11-18 15:28
- Questions: `eval/eval_questions_en.jsonl` (50: 50 with expected articles, 0 off-topic, 0 follow-ups)
- Index: voyage-4-lite (1024 dims), pipeline built 2026-11-04
- Pipeline: rewriting of follow-ups → vector + BM25 (reciprocal rank fusion) → 10 candidates → rerank-3-lite → 5 articles; no relevance threshold

**Hit@5 (articles handed to the LLM): 100% (50/50) – threshold 90% – PASS**

| Metric | Full pipeline | Vector only (baseline) |
|---|---|---|
| Hit@5 | 100% | 98% |
| Rank 1 | 100% | 88% |
| Candidate recall@10 | 100% | – |

Candidate pool (ADR-004): expected article missing from the 10 candidates for 0 question(s) – pool of 10 kept.

## By question type

| Type | Questions | Hit@5 | Rank 1 | Baseline hit@5 |
|---|---|---|---|---|
| fact | 11 | 100% | 100% | 100% |
| figure | 3 | 100% | 100% | 100% |
| long_article_subtopic | 8 | 100% | 100% | 88% |
| procedure | 9 | 100% | 100% | 100% |
| short_article | 3 | 100% | 100% | 100% |
| source_ambiguity | 2 | 100% | 100% | 100% |
| table | 14 | 100% | 100% | 100% |

## Misses (0)

None.

## Long articles

- q11: expected APPENDIX 4 – rank after reranking 1 ✓
- q12: expected APPENDIX 4 – rank after reranking 1 ✓
- q15: expected 12.2.2 – rank after reranking 1 ✓
- q16: expected 12.2.2 – rank after reranking 1 ✓
- q17: expected 12.2.2 – rank after reranking 1 ✓
- q18: expected 6.3.1 – rank after reranking 1 ✓
- q19: expected 6.3.2 – rank after reranking 1 ✓
- q20: expected 14.4.2 – rank after reranking 1 ✓
- q21: expected 1.4.1 – rank after reranking 1 ✓
- q23: expected DRAWING 1, 12.2.2 – rank after reranking 1 ✓
- q30: expected 10.2.3 – rank after reranking 1 ✓

## Calibration data for the relevance threshold (best reranker score)

- In-scope questions (50): min 0.712 · p10 0.811 · median 0.880 · p90 0.919 · max 0.924
- Off-topic questions (0): n/a
