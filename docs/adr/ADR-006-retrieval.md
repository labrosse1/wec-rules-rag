## ADR-006: Retrieval
```
Status: Accepted
Date: 2026-11-18
Scope: From the user's message in the chat to the articles handed to the answer LLM. Answer generation is out of scope (future ADR).
```
### Context and data property

ADR-003, 004, 005 produced the index that retrieval works on:

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

**Question handling**

- **The first message of a conversation is searched as it is**, with no rewriting.
- **A follow-up message is rewritten into a standalone question** by the LLM, using the chat history, before the search. Example: "And for LMGT3?" becomes "How many tyres can an LMGT3 car use in a 6h race?".
  - This applies to every message that has a chat history.
  - The rewriting prompt instructs the LLM to return the message unchanged when it is already standalone.
- **No other query transformation** is used: no paraphrasing into the regulation's vocabulary, no hypothetical answer (HyDE), no splitting into sub-questions.

**Candidate search (hybrid)**

- **Two searches run on the standalone question:**
  - a vector search on the Chroma collection (Voyage, `input_type="query"`);
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
- **Le Mans detection by keywords.** It misses phrasings such as "the 24-hour race" or "the French endurance classic", and it adds 1.2.4 to every question that mentions Le Mans, even when it is not needed.
- **Five articles per question.** The LLM receives more context than with three, so there is more text to read and a higher chance of a less relevant article among them.
- **No threshold until calibrated.** Until then, off-topic questions will still receive 5 articles, and refusals depend only on the LLM.
- **Deployment.** The BM25 search needs the docstore at runtime, so it must be shipped to the Space with the Chroma collection. The reranker adds one Voyage API call per question, which needs the Voyage key at runtime.
- **First evaluation set.** It stays optimistic (questions close to the text). The 90 % criterion is checked on it, while the second set gives the more realistic picture.
