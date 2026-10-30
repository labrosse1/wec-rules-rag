## ADR-003: Chunking, embedding and storage
```
Status: Accepted
Date: 2026-10-29
Scope: Second step: turning the clean JSON (ADR-001, ADR-002) into an indexed, deployable vector store. Retrieval and answer generation are out of scope (future ADR).
```
### Context and data property

ADR-001 and ADR-002 produce `output/2026_WEC_rules_en.v2.json`: one record per article with its hierarchy, pages, tables rewritten as one self-contained line per row, figure records, references and flags. It passes the quality gate (`qa_rules.py`).

The record set has the following properties:

- **Size.** 342 records, of which 19 belong to Appendix 1. Appendix 1 is a blank model of Supplementary Regulations full of "XX" placeholders.
- **Length.** Most articles are short. A few are long and cover several sub-topics, each introduced by "a)", "b)"… or "1)", "2)". The longest is 12.2.2 (pit stop procedure: arrival, driver change, refuelling, intervention, departure).
- **Very short articles.** Some articles are a single sentence, such as Appendix 9-4.2 "This limitation is Championship-specific.". They mean nothing without their place in the hierarchy.
- **Tables.** Thirteen tables are present. Twelve are small. The Appendix 4 table (technical penalties) lists 17 infringements and is about 1,000 tokens long.
- **Figures.** Five figures are records of their own, with human-verified descriptions.
- **Flags.** Two records carry a `source_ambiguity` flag (4.2.5, 10.2.3), which is kept on purpose (ADR-002).

The target is a RAG for the **general public**, asking **generalist questions in English**. Users phrase questions in their own words rather than in the regulation's vocabulary, so the quality of the semantic embedding matters more than exact keyword matching.

The stack is LlamaIndex, Voyage `voyage-4-lite` embeddings and ChromaDB. The target deployment is a Hugging Face Space with a Gradio interface. A Space's disk is ephemeral: anything written at runtime is lost when the Space restarts.

ADR-002 states that `run_pipeline.py` chains extraction → QA → chunking. This is no longer true: `run_pipeline.py` stops after the QA, and chunking is done by LlamaIndex as defined here.

### Decision

**Scope and language**

- English only. The corpus is the English column (ADR-001) and questions are expected in English. French queries are out of scope.
- Appendix 1 is **excluded** from the index. The other 323 records, figure records included, are indexed.

**Chunking**

- **One chunk per article** by default (ADR-001). This also applies to very short articles, which are kept as they are.
- An article above **about 600 tokens** is split:
  1. first at its own sub-items ("a)", "b)", "1)", "2)"…);
  2. then at paragraph boundaries if a sub-item is still too long;
  3. with a target size of **400 to 500 tokens** and **no overlap**.

  Cuts fall on boundaries of meaning, so overlap would only duplicate text. Each part keeps the article's hierarchy and is labelled "part k/n".
- **A table is never split.** A chunk that contains a table may exceed the threshold. This applies to Appendix 4, whose table is kept whole in a single chunk.
- Figure records are indexed as chunks of their own.

**Identifiers**

- Chunk ids are derived from the article: `12.2.2` for a whole article, `12.2.2#1`, `12.2.2#2`… for the parts of a split article. They are set explicitly; LlamaIndex's random ids are not used.

**Metadata**

Each metadata field has one of three roles:

| Role | Fields | Effect |
|---|---|---|
| Embedded with the text | `breadcrumb` (hierarchy path, which includes the article title) | Gives context to short articles and adds topic words ("Tyres", "Pit stops") to the vector |
| Shown to the answer LLM | `citation`, `flags`, `breadcrumb` | Lets the answer cite its source and report a `source_ambiguity` instead of choosing a value |
| Stored only | everything else: `rule_id`, `appendix`, `chapter`, `part`, `section`, `article`, `title`, `pages`, `page_start`, `level`, `has_table`, `is_figure`, `references`, versions | Filtering (none for now), display, debugging, traceability |

- Pages, ids, flags and references are **not embedded**: they are codes and numbers without meaning, and they would blur the vector.
- Metadata values are converted to scalars (string, number, boolean), as required by ChromaDB. For example, lists of pages are stored as "40, 41" plus an integer `page_start`.
- No metadata filtering is used at query time for now.

**Embedding**

- Model `voyage-4-lite`, **1024 dimensions** (the default), float output.
- `input_type="document"` when indexing chunks, and `input_type="query"` when embedding a question. The LlamaIndex Voyage integration must be checked to apply this distinction in the installed version.

**Storage**

- **ChromaDB, persistent local client**, one collection for this corpus and model (for example `wec_2026_en`).
- The collection is created with the **cosine distance** (`{"hnsw:space": "cosine"}`). ChromaDB defaults to L2, and the distance cannot be changed once the collection exists.
- The **LlamaIndex docstore** (the nodes' text and metadata) is persisted next to the Chroma collection. A future hybrid retrieval with BM25 needs the text, not the vectors.
- Every chunk records, for traceability:
  - the source publication date (`2025-10-16`);
  - the pipeline version;
  - the embedding model name and its dimension.

  The collection records the same values. This prevents vectors from two different models from being mixed in one collection.

**Updates**

- **Full rebuild** on any change: delete the collection, then re-embed everything. Triggers are:
  - a new edition of the PDF;
  - a change to `figures.json`;
  - a change to the extractor or the chunking parameters;
  - a change of embedding model.
- Incremental updates are not implemented. The stable ids keep them possible later.

**Deployment**

- The index (Chroma collection and docstore) is **built locally** and committed to the Hugging Face Space repository.
- The Space only reads the index at runtime and never writes to it. This avoids the ephemeral-disk problem without any persistent storage add-on.
- The Voyage and Gemini API keys are configured as Space secrets. Questions are embedded at runtime, so the Voyage API is needed in production.

**Validation (blocking before deployment)**

1. **Coverage.** The number of distinct `rule_id` values in the collection equals the number of indexed records (323).
2. **Table integrity.** No table row is shared between two chunks, and every table is entirely contained in one chunk.
3. **Consistency.**
   - Chunk ids are unique.
   - Every vector has 1024 dimensions.
   - Every chunk carries the version metadata.
   - The collection uses the cosine distance.
4. **Retrieval quality.** On an evaluation set of **50 English questions**, the expected article must appear among the **top 5** results (vector search only) for **at least 90 %** of the questions. A question counts as a hit when any chunk of the expected article is retrieved.
   - The questions are written in general-public phrasing, manually or with AI assistance.
   - Each question is reviewed by a human, with its expected article and answer.
   - The set covers numeric answers taken from tables (points, tyre allocations, penalties, driving times), procedures, figures and short articles.

### Consequences

**Positive**

- Every chunk is directly citable (article, page) and keeps its hierarchy, so short articles stay understandable once embedded.
- Long multi-topic articles such as 12.2.2 get one vector per sub-topic, which should match specific questions better.
- Tables stay whole, so a numeric answer never depends on a row being reassembled from two chunks.
- Full rebuild is cheap: the corpus is about 50,000 to 60,000 tokens, a small fraction of the 200 million token budget. It also guarantees that no stale chunk survives.
- The deployed Space needs no writable storage and starts without re-embedding.
- The docstore and the stable ids prepare hybrid search and reranking without re-indexing.

**Accepted trade-offs**

- The Appendix 4 table is one vector for 17 infringements. A question about one infringement (for example cockpit temperature) may rank it lower than a focused chunk would. This must be watched in the evaluation; splitting the table by category group (Hypercar / LMGT3 / All categories) is the fallback.
- Excluding Appendix 1 means the system cannot answer what a competition's Supplementary Regulations must contain.
- Splitting at "a)" / "1)" sub-items is specific to this document. LlamaIndex's `SentenceSplitter` does not do it, so a small custom node parser is needed.
- The 600-token threshold is measured with the splitter's tokenizer, which is an approximation of Voyage's own token count.
- Every change requires rebuilding the index locally and committing it again to the Space repository.
- Questions in languages other than English are not supported.
- Retrieval choices (hybrid search, reranker, number of candidates) are left to the next ADR. The vector-only validation threshold above is therefore a minimum, not the final target.
