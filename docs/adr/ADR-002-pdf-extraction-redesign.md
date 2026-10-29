## ADR-002: Layout-based extraction redesign and quality gate
```
Status: Accepted
Date: 2026-10-29
Scope: First step (amends ADR-001): extraction method, table handling and quality check.
```
### Context and data property

ADR-001 set the target: keep only the English column, one record per article, JSON output with hierarchy metadata, citable sources. The first script (`extract_rules.py`) met this target in form but not in quality. A review of its output against the PDF found defects that would make the RAG give wrong answers:

- **Tables flattened into plain text.** 13 tables (points, tyre specifications and allocations, pit lane speed penalties, driving times, Appendix 4 technical penalties, test tyre allocation...) lost their column structure, e.g. "HYPERCAR 12 4 18 26 32". These are exactly the figures users will ask about.
- **Headings guessed with regular expressions** on flattened text. List items were read as sections (Appendix 1), sections were merged (Appendix 6 article 2 inside article 1).
- **Text noise.** Line-end hyphenation left split words ("Hyper- pole", "wet- weather"), superscripts were split ("13 th"), and figures (Drawing N°1, sticker layouts, RFID positions) had no text at all while the regulations refer to them.
- **No way to detect any of the above** other than reading the output by hand.

Investigation of the PDF showed the layout carries reliable structure that the first script ignored:

- Typeface encodes the hierarchy: Bold = chapter / appendix title, Heavy = section, Medium = article.
- Article numbers sit in a number column (x ≈ 239) while body text is indented (x ≈ 262).
- Tables are drawn with vector rules, so their cell geometry can be recovered exactly.
- The PDF contains its own table of contents (pages 86-90), usable as a reference for validation.

Two passages that looked like extraction artefacts ("from the 10 15 minute signal" in 4.2.5, "will may be imposed" in 10.2.3) are in fact printed as such in the published PDF, in both French and English: they are unresolved revision marks in the source.

### Decision

- **Read the layout, not flattened text.** Headings are classified by font and horizontal position (PyMuPDF spans) instead of regex on text. Lines on the same baseline are merged; paragraphs are split on vertical gaps and deliberate short lines.
- **Rebuild tables from their vector rules** with pdfplumber. Merged cells are resolved geometrically, so every row is complete. Each table is written in the text as one self-contained line per row with explicit headers (e.g. "HYPERCAR — Free practice: 12; Hyperpole**: 4; Qualifying + Race / 6h race: 18..."), and a Markdown copy is kept in metadata for display.
- **Resolve hyphenation against the document's own vocabulary**: "Hyper-pole" becomes "Hyperpole" because "hyperpole" exists elsewhere in the document, "wet-weather" stays hyphenated.
- **Figures become records of their own**, with a manual text transcription stored in `figures.json`, a `verified` flag, and links to the related articles. The text where a figure appears keeps a pointer to the figure record.
- **Add a quality gate (`qa_rules.py`)** that blocks indexing when it fails. It checks coverage against the PDF table of contents, numbering gaps, empty and duplicate records, cross-reference resolution, and word coverage of the English column. It also lists the items that need a human decision.
- **Flag, never guess, source ambiguities.** Records containing unresolved revision marks get a `source_ambiguity` flag; the answer LLM must report the ambiguity instead of choosing a value.
- **Extend the metadata** defined in ADR-001 with: pages per paragraph, breadcrumb, ready-made citation, categories concerned (Hypercar / LMGT3), internal and external references, related articles, flags, `is_template` (Appendix 1 is a blank model with "XX" placeholders).
- **One entry point (`run_pipeline.py`)** chains extraction → QA → chunking and stops before chunking if the QA fails.

### Consequences

**Positive**

- Measured on the 2026 PDF: 0 missing entries out of the 279 in the table of contents, 0 numbering gaps, 0 duplicate ids, 0 unresolved internal references. Only 6 of the 35,892 source words are not found as such, all of them deliberately re-joined hyphenations.
- All 13 tables were checked cell by cell against the rendered PDF.
- Numeric answers (points, tyre allocations, penalties) can now be answered from explicit text rather than guessed from column order.
- Citations can point to the exact page of the paragraph used.

**Accepted trade-offs**

- The extractor relies on this document's typography (Futura font names, column positions). A new edition with a different layout will need the constants to be adjusted; the quality gate is there to detect it.
- Figure descriptions are written by hand and must be reviewed by a human (`verified: true`) before production. They must be redone if the figures change.
- The two source ambiguities (4.2.5, 10.2.3) are not resolved by the pipeline. They need a decision based on an official FIA source; until then the affected answers will say the text is ambiguous.
- Source typos are kept verbatim ("ERSv", "is committee between", "120 (30)" whose unit is not stated) to stay faithful to the published text.
- A new dependency (pdfplumber) is added, and the pipeline is now four scripts plus a data file instead of one script.
- The validity of the answers still depends on indexing the version of the regulations in force: the PDF used is dated 16.10.2025 and must be checked against later FIA amendments.
