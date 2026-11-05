## ADR-005: Chunking, embedding and storage (Amendment ADR-003)
```
Status: Accepted,
Date: 2026-11-04
Scope: Second step: turning the clean JSON (ADR-001, ADR-002) into an indexed, deployable vector store. Retrieval and answer generation are out of scope (future ADR).
```
#### Evaluation result (2026-11-04)
 
The trial was evaluated with `evaluate_retrieval.py` on the 50-question set `eval/eval_questions_en.jsonl`. The questions were drafted with AI assistance (Claude Opus 5.5) and reviewed by a human. The evaluation used vector search only on the 323-node index.
 
| Metric | Result | Threshold |
|---|---|---|
| Article in top 5 | **98 %** (49/50) | 90 % |
| Article at rank 1 | 88 % | – |
 
**Decision: the trial is confirmed.** One node per article becomes the chunking rule of this ADR, and splitting long articles at their sub-items is abandoned.
 
**The only miss, q17** ("Does the engine have to be switched off for a driver change?", sub-topic of 12.2.2):
 
- **Ranks.** The expected article 12.2.2 is ranked 6th. The top 5 are 9.1.8, 12.2.1, 12.3.1, 6.6 and Appendix 9-9.6.
- **12.2.1 also answers the question.** It is ranked 2nd and states that personnel may be in the working area only when the car is stopped with its engine off. It also states that drivers may not unbuckle before the engine is stopped, and that the same principle applies to driver changes. The answer is therefore reachable from the top 5. The question set lists only 12.2.2 as expected; this was left unchanged, so the measured score stays 98 %.
- **The risk named in this amendment did occur once.** 12.2.2, which holds the explicit rule ("properly stopped, engine off"), was ranked below four less relevant articles that only share the word "engine" (9.1.8, 12.3.1, 6.6, Appendix 9-9.6). The driver-change sub-topic is diluted in a five-topic article.
- **Remedy.** This is left to the retrieval step (next ADR): a reranker is expected to rank 12.2.2 above these keyword-only matches. Long-article sub-topic questions must be watched again once retrieval changes.
**Limits of this result**
 
- The questions were written from the text of the articles. They probably reuse more of the regulation's wording than real general-public questions would, so the score is likely optimistic.
- With 50 questions, one question is worth 2 points: the result is a coarse measure.
- The blocking validation checks of the original decision (coverage, table integrity, dimensions, cosine distance, unique ids) have not been run yet.
