## ADR-001: Text extraction and formating
```
Status: Accepted
Date: 2026-09-29
Scope: First step: tranforming the source PDF into clean JSON to prepare for indexing.
```
### Context and data property

I am building a RAG system over the FIA World Endurance Championship Sporting Regulations 2026 using LlamaIndex, Voyage-4-lite for embeddings, ChromaDB and Gemini 3.5 flash as final answer LLM.

The source is a pdf file (2026_WEC.pdf) which is 90 pages long (60 pages text + 30 pages appendix).
The rules are stated in two columns one in french and its translation in English.
The document has a strong hierarchy and split between chapters, sections, parts, appendix, articles, titles, pages number...

### Decision

- Since the document is in two languages, I've decided to only keep and process the english text part to avoid adding noise in the extract.
Only the english column will need to be retrieved (right part of the page).
- The document is segmented into articles that are quite short (less than 400 words). I will keep this organisation for extraction
- I chose the output to be on JSON format to be able to preserve the document hierarchy which is important for understanding and to be able to enrich with metadata to improve retrieval accuracy.
- Metadata that will be implemented for each article will be: appendix, chapter, section, part, article, title.
- The system will need to be able to cite the sources in the original document using those metadata.
- Articles that are split between two pages will need to be grouped in a single one to preserve meaning.

### Consequences

**Positive**

- Preserves text structure and makes every retrieved chunk directly citable.

**Accepted trade-offs**

- Only english version of the text will be preserved even though the french version of the text will be used should any dispute arise between the english and french text interpretation.
- One change in an article will need a full reindex
