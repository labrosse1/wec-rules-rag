"""Evaluate the retrieval of the ChromaDB index on the 50-question set (ADR-003).

For each question, the index is queried (vector search only, as in
query_chroma_index.py). A question is a hit when any of its expected articles
is among the top K results (default 5). The run passes when the hit rate
reaches the threshold (default 90 %).

The report also gives, for ADR-003 Amendment 1, the failures on long
articles, which decide whether "one node per article" is kept.

Usage:
    python evaluate_retrieval.py
    python evaluate_retrieval.py --questions eval/eval_questions_en.jsonl --k 5 --threshold 0.9

Outputs:
    output/eval/retrieval_<date-time>.jsonl   one line per question (ranks, retrieved ids)
    output/eval/retrieval_<date-time>.md      readable report
Exit code 1 when the threshold is not reached.

Requires the environment variable VOYAGE_API_KEY.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

COLLECTION = "wec_2026_en"
DEPTH = 20  # results fetched per question, to know the rank of a miss
# articles above ~512 tokens, kept whole by ADR-003 Amendment 1
LONG_ARTICLES = {"1.4.1", "6.3.1", "6.3.2", "10.2.3", "12.2.2", "14.4.2", "APPENDIX 4"}


def load_questions(path):
    questions = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    unreviewed = [q["id"] for q in questions if not q.get("reviewed", False)]
    if unreviewed:
        print(f"Warning: {len(unreviewed)} question(s) not marked reviewed: {', '.join(unreviewed)}")
    return questions


def open_index(index_dir):
    load_dotenv()
    if not (index_dir / "chroma.sqlite3").exists():
        sys.exit(f"Index not found in {index_dir}: run build_chroma_index.py first "
                 f"(current folder: {Path.cwd()}).")
    if not os.getenv("VOYAGE_API_KEY"):
        sys.exit("VOYAGE_API_KEY is not set.")
    collection = chromadb.PersistentClient(path=str(index_dir)).get_collection(COLLECTION)
    meta = collection.metadata or {}
    embed_model = VoyageEmbedding(model_name=meta["embed_model"], output_dimension=meta["embed_dimension"])
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection),
                                               embed_model=embed_model)
    return index.as_retriever(similarity_top_k=DEPTH), collection.count(), meta


def evaluate(questions, retriever, k):
    results = []
    for n, q in enumerate(questions, 1):
        hits = retriever.retrieve(q["question"])
        retrieved = [h.node.metadata["rule_id"] for h in hits]
        ranks = {a: (retrieved.index(a) + 1 if a in retrieved else None) for a in q["expected_articles"]}
        found = [r for r in ranks.values() if r]
        best = min(found) if found else None
        results.append({**q, "retrieved": retrieved[:k], "ranks": ranks, "best_rank": best,
                        "hit": best is not None and best <= k,
                        "top_score": round(hits[0].score, 4) if hits else None})
        print(f"\r{n}/{len(questions)} questions", end="", flush=True)
    print()
    return results


def rate(rows):
    return sum(r["hit"] for r in rows) / len(rows) if rows else 0.0


def report(results, k, threshold, n_nodes, meta, questions_path):
    total = rate(results)
    passed = total >= threshold
    found = [r["best_rank"] for r in results if r["best_rank"]]
    mrr = sum(1 / r for r in found) / len(results)
    lines = [
        "# Retrieval evaluation",
        "",
        f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
        f"- Questions: `{questions_path}` ({len(results)})",
        f"- Index: {n_nodes} nodes, {meta.get('embed_model')} ({meta.get('embed_dimension')} dims), "
        f"pipeline `{meta.get('pipeline_version')}`, built {meta.get('built_on')}",
        "- Retrieval: vector search only",
        "",
        f"**Hit@{k}: {total:.0%} ({sum(r['hit'] for r in results)}/{len(results)}) – "
        f"threshold {threshold:.0%} – {'PASS' if passed else 'FAIL'}**",
        "",
        f"Hit@1: {sum(1 for r in results if r['best_rank'] == 1) / len(results):.0%} · "
        f"Hit@{DEPTH}: {len(found) / len(results):.0%} · MRR@{DEPTH}: {mrr:.3f}",
        "",
        "## By question type",
        "",
        "| Type | Questions | Hit@%d |" % k,
        "|---|---|---|",
    ]
    by_type = defaultdict(list)
    for r in results:
        by_type[r["type"]].append(r)
    for t, rows in sorted(by_type.items(), key=lambda kv: rate(kv[1])):
        lines.append(f"| {t} | {len(rows)} | {rate(rows):.0%} |")

    misses = [r for r in results if not r["hit"]]
    lines += ["", f"## Misses ({len(misses)})", ""]
    if not misses:
        lines.append("None.")
    for r in misses:
        where = ", ".join(f"{a}: rank {rk if rk else f'>{DEPTH}'}" for a, rk in r["ranks"].items())
        lines += [f"- **{r['id']}** ({r['type']}) {r['question']}",
                  f"  - expected: {where}",
                  f"  - top {k}: {', '.join(r['retrieved'])}"]

    long_rows = [r for r in results if set(r["expected_articles"]) & LONG_ARTICLES]
    long_misses = [r for r in long_rows if not r["hit"]]
    lines += ["", "## Long articles (ADR-003 Amendment 1)", "",
              f"- Questions expecting a long article: {len(long_rows)}; hit@{k}: {rate(long_rows):.0%}",
              f"- Share of all misses that concern a long article: "
              f"{len(long_misses)}/{len(misses) if misses else 0}"]
    lines += [f"  - {r['id']}: {r['question']}" for r in long_misses]
    return "\n".join(lines) + "\n", passed


def main():
    p = argparse.ArgumentParser(description="Evaluate retrieval on the question set.")
    p.add_argument("--questions", default="eval/eval_questions_en.jsonl")
    p.add_argument("--index", default="output/chroma")
    p.add_argument("--out", default="output/eval")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--threshold", type=float, default=0.9)
    args = p.parse_args()

    questions = load_questions(args.questions)
    retriever, n_nodes, meta = open_index(Path(args.index))
    results = evaluate(questions, retriever, args.k)
    text, passed = report(results, args.k, args.threshold, n_nodes, meta, args.questions)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    with (out / f"retrieval_{stamp}.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / f"retrieval_{stamp}.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved: {out / f'retrieval_{stamp}.md'} and .jsonl")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
