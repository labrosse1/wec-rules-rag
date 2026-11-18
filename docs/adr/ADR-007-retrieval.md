## ADR-007: Retrieval
```
Status: Accepted, completed 2026-11-18 with the evaluation results (see Evaluation result)
Date: 2026-11-18
Scope: Third step: from the user's message in the chat to the articles handed to the answer LLM. Answer generation is out of scope (future ADR).
```
### Context and data property

ADR-004 produced the index that retrieval works on:

- **Index.** A ChromaDB collection of 323 nodes, one per article (Appendix 1 excluded), embedded with `voyage-4-lite` (1024 dimensions, cosine distance).
- **Docstore.** A LlamaIndex docstore with the same nodes, kept for a keyword (BM25) search.
- **Baseline.** On the 50-question evaluation set, vector search alone puts the expected article in the **top 5 for 98 %** of the questions and at **rank 1 for 88 %**.
- **The only miss, q17.** The question was about the driver-change sub-topic of 12.2.2. The article was ranked 6th, behind articles that only share the word "engine".

The system targets the general public, asking questions in English through a **Gradio chat** on a Hugging Face Space. In a chat, a follow-up message is often incomplete. After "How many tyres can a Hypercar use in a 6h race?", the next message may be "And for LMGT3?", which holds neither "tyres" nor "6h race". Searched as it is, such a message cannot find the right article.

The regulations state that the Supplementary Regulations of the 24 Hours of Le Mans take precedence over them (Article 1.2.4). An answer about Le Mans that ignores this would be misleading.

The evaluation set was written from the text of the articles, so it probably overestimates the quality reached on real general-public questions. It also contains no off-topic and no follow-up questions.

### Decision

**Scope**

- This ADR covers retrieval only: from the user's message (and the chat history) to the articles handed to the answer LLM. How the answer is written, including the wording of a refusal, belongs to the next ADR.
- English only.

**Question handling**

- **The first message of a conversation is searched as it is**, with no rewriting.
- **A follow-up message is rewritten into a standalone question** by the LLM, using the chat history, before the search. Example: "And for LMGT3?" becomes "How many tyres can an LMGT3 car use in a 6h race?".
  - This applies to every message that has a chat history.
  - The rewriting prompt instructs the LLM to return the message unchanged when it is already standalone.
- **No other query transformation** is used: no paraphrasing into the regulation's vocabulary, no hypothetical answer (HyDE), no splitting into sub-questions.

**Candidate search (hybrid)**

- **Two searches run on the standalone question:**
  - a vector search on the Chroma collection
  - a BM25 keyword search on the docstore.
- Their results are merged with **reciprocal rank fusion** (LlamaIndex `QueryFusionRetriever`, mode `reciprocal_rerank`), which combines ranks rather than scores. The vector and BM25 scores are not on the same scale.
- The **top 10 fused candidates** are passed to the reranker.
- The hybrid search is kept as part of the design. Its effect is reported by the evaluation; the validation criterion below guards against a loss.

**Reranking**

- Model **`rerank-3-lite`** (Voyage). It accepts up to 32,000 tokens per query and document, so every article, including the longest, is reranked whole.
- It rereads the 10 candidates with the question and orders them by relevance.
- **The top 5 reranked articles are handed to the answer LLM.**
- **Candidate pool check.** The reranker can only reorder what it receives. If, on the first evaluation set, the expected article is missing from the 10 candidates for more than one question (candidate recall@10 below 98 %), the pool is raised to **20 candidates**.

**Le Mans rule**

- When the standalone question contains "Le Mans", "24 Hours" or "24h" (case ignored), **Article 1.2.4 is added** to the articles handed to the LLM, unless it is already among them.
- It is added **in addition to** the 5 articles and never replaces one.

**No filtering, no expansion**

- No metadata filter (category, appendix, chapter) is applied (ADR-003).
- Articles referenced by a retrieved article ("see Article 7.4.9", figures, drawings) are **not** added automatically: with 5 places, each added article would push out a retrieved one.

**Relevance threshold (method decided, value to be measured)**

- **Purpose.** The threshold lets the system refuse instead of handing unrelated articles to the LLM. If the reranker score of the **best** candidate is below the threshold, no article is handed to the LLM.
- **It is applied to the reranker score only.** Vector, BM25 and fused scores are on different scales and are not used for it.
- **Calibration** uses the second evaluation set:
  1. record the best reranker score of each question;
  2. compare the in-scope questions with the off-topic ones;
  3. place the threshold between the two groups, on the low side, because refusing a valid question is worse than handing a weak article that the LLM can still dismiss.
- **Until it is calibrated, no threshold is applied.** Its value will be added to this ADR once measured.

**Evaluation**

- **Validation criterion.** With the full pipeline (rewriting, hybrid search, reranking), the expected article must be among the **5 articles handed to the LLM** for **at least 90 %** of the questions of the first set (`eval/eval_questions_en.jsonl`).
- **Also reported** (not blocking):
  - rank-1 rate;
  - candidate recall@10, which decides the pool size;
  - the comparison with the vector-only baseline (98 % top 5, 88 % rank 1);
  - the rank of 12.2.2 for q17.
- **Second evaluation set (50 questions):**
  - **30 questions on the regulations**, phrased as the general public would, written without reading the regulation text;
  - **10 off-topic questions** that the regulations cannot answer, to calibrate the threshold;
  - **10 follow-up questions**, each with the chat history it depends on, to test the rewriting.
- `evaluate_retrieval.py` must be extended to run the full pipeline. It must replay the chat history of follow-up questions, and record the best reranker score of each question for the calibration.

### Consequences

**Positive**

- Follow-up questions in the chat become searchable without changing how first questions are handled.
- The reranker addresses the q17 case: a long multi-topic article outranked by keyword-only matches. It does so without going back to splitting articles.
- BM25 adds exact-term matching (article numbers, "FCY", "Pass-Around", "Hyperpole"), which vector search can miss.
- The validation criterion now measures exactly what the LLM receives, which is 5 articles.
- Le Mans answers always come with the rule that the Le Mans Supplementary Regulations prevail.
- A second, more realistic question set reduces the optimism of the first one and provides the data needed for the threshold.

**Accepted trade-offs**

- **Rewriting follow-ups.** It adds one LLM call to every message that has a history. This means more latency and cost, and a risk of a wrong rewriting that sends the search in the wrong direction. The 10 follow-up questions of the second set measure this risk.
- **Hybrid search kept unconditionally.** A poorly balanced fusion can lower the results below the vector-only baseline. The criterion (at least 90 % top 5) catches a large loss, but not a small one. The comparison with the baseline must be read at each evaluation.
- **Le Mans detection by keywords.** It misses phrasings such as "the 24-hour race" or "the French endurance classic", and it adds 1.2.4 to every question that mentions Le Mans, even when it is not needed.
- **Five articles per question.** The LLM receives more context than with three, so there is more text to read and a higher chance of a less relevant article among them.
- **No threshold until calibrated.** Until then, off-topic questions will still receive 5 articles, and refusals depend only on the LLM.
- **Deployment.** The BM25 search needs the docstore at runtime, so it must be shipped to the Space with the Chroma collection. The reranker adds one Voyage API call per question, which needs the Voyage key at runtime.
- **First evaluation set.** It stays optimistic (questions close to the text). The 90 % criterion is checked on it, while the second set gives the more realistic picture.

---

### Evaluation result (2026-11-18)
```
Date: 2026-11-18
Status: Accepted
Completes: Decision > Reranking (candidate pool), Decision > Relevance threshold
```
The pipeline was evaluated with `evaluate_retrieval.py` on both question sets. No relevance threshold was applied, so that all reranker scores could be recorded.

#### Results

**Set 1** (`eval/eval_questions_en.jsonl`, 50 in-scope questions), with 10 candidates:

| Metric | Full pipeline | Vector only (ADR-003) |
|---|---|---|
| Expected article among the 5 handed to the LLM | **100 %** | 98 % |
| Expected article at rank 1 | **100 %** | 88 % |
| Expected article among the 10 candidates | 100 % | – |

- **The validation criterion (at least 90 % in the top 5) is met.**
- **q17 is resolved.** 12.2.2 moves from rank 6 to rank 1. This is the case the reranker was meant to address.
- **Limit.** A perfect rank-1 score mainly confirms that this set is close to the wording of the regulations.

**Set 2** (`eval/eval_questions_en_set2.jsonl`: 30 regulation questions in general-public phrasing, 10 off-topic, 10 follow-ups):

| Metric | 10 candidates | 20 candidates | Vector only |
|---|---|---|---|
| Expected article among the 5 handed to the LLM (40 questions) | 95 % | **98 %** | 92 % |
| Expected article at rank 1 | 95 % | **98 %** | 90 % |
| Expected article among the candidates | 95 % | 98 % | – |
| Follow-up questions (10) | 100 % | 100 % | 100 %* |

\* The vector-only figure for follow-ups uses the rewritten question, so it does not measure a search without rewriting.

**Misses on set 2:**

- **s05**, "Can a team add fuel to a car that has stopped out on the circuit?". The expected 9.1.5 ("any replenishment of any energy or liquid on the track is prohibited") is missing from the candidates, even with 20. This is a vocabulary gap ("add fuel… circuit" vs "replenishment… track") that a larger pool does not bridge.
- **s06**, "If a car breaks down on the circuit, can the team come and fix it?". The expected 12.3.2 / 9.1.6 were missing from 10 candidates and are found with 20.

**Follow-up rewriting.**

- **All 10 follow-ups retrieve the right article.** Gemini often adds "in the FIA World Endurance Championship" to the rewritten question; this is harmless.
- **The Le Mans rule still applies after rewriting.** The rewritten Le Mans follow-up keeps "Le Mans", so the rule is triggered.
- **Rewriting is not fully deterministic, even at temperature 0.** The wording changed slightly between two runs without changing the results, so two identical evaluations can give slightly different figures.

#### Decisions

- **Candidate pool: 20 candidates** (`CANDIDATES = 20` in `retrieval.py`).
  - On set 1, the rule of this ADR would keep 10, since no expected article was missing.
  - The pool is raised on the evidence of set 2: with 20 candidates, one more general-public question is retrieved (s06).
  - The cost is negligible with `rerank-3-lite`, and the added latency is small.
- **Relevance threshold: 0.60** on the best reranker score. Below it, no article is handed to the LLM.

| Group | Best reranker score observed |
|---|---|
| In-scope questions, set 1 (50) | min 0.712 |
| In-scope questions, set 2 (40, 20 candidates) | min 0.700 (0.673 with 10 candidates) |
| Off-topic questions, set 2 (10) | max 0.678 (values: 0.411 to 0.678) |

- **Effect of 0.60.**
  - No in-scope question of either set is refused, with a margin of about 0.10 below the lowest in-scope score.
  - 8 of the 10 off-topic questions are refused.
  - The threshold is placed on the low side, as decided above.
- **The two off-topic questions above 0.60** are still handed 5 articles: s36 "Who is the current WEC Hypercar world champion?" (0.661) and s37 "How much does it cost to buy a Hypercar?" (0.678). **The answer LLM must refuse when the articles do not answer the question.** This requirement passes to the generation ADR.

#### Limits and follow-up

- **Small samples.** With 40 in-scope and 10 off-topic questions in set 2, the threshold is a first estimate. It must be reviewed with real user questions.
- **Set 2 was written with AI assistance** so it is less independent than questions from real users.
- **Vocabulary gaps such as s05 are not handled.** They are a known limit of searching the question as it is.
