"""Evaluate the full retrieval pipeline of ADR-004 on a question set.

Pipeline evaluated (retrieval.py): follow-up rewriting -> vector + BM25 fusion ->
10 candidates -> rerank-3-lite -> 5 articles handed to the LLM (+ Le Mans rule).
No relevance threshold is applied during the evaluation, so that the reranker
scores can be recorded for its calibration.

Works with both question sets:
  eval/eval_questions_en.jsonl        (set 1: 50 in-scope questions; ADR-004 criterion)
  eval/eval_questions_en_set2.jsonl   (set 2: 30 regulation, 10 off-topic, 10 follow-up)

Metrics (questions that have expected articles):
  hit@5      an expected article is among the 5 articles handed to the LLM
             (the article added by the Le Mans rule is not counted)
  rank-1     an expected article is ranked first
  recall@10  an expected article is among the 10 candidates given to the reranker
  baseline   hit@5 / rank-1 of vector search alone, on the same questions
Calibration data: best reranker score of in-scope vs off-topic questions.
Follow-ups: the rewritten question is shown next to the expected one.

Usage:
    python evaluate_retrieval.py                                  # set 1
    python evaluate_retrieval.py --questions eval/eval_questions_en_set2.jsonl
Outputs: output/eval/pipeline_<set>_<date-time>.md and .jsonl
Exit code 1 when hit@5 is below the threshold (default 90 %).

Requires VOYAGE_API_KEY and GOOGLE_API_KEY.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from retrieval import TOP_N, WecRetriever

load_dotenv() 

LONG_ARTICLES = {"1.4.1", "6.3.1", "6.3.2", "10.2.3", "12.2.2", "14.4.2", "APPENDIX 4"}


def load_questions(path):
    questions = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    unreviewed = [q["id"] for q in questions if not q.get("reviewed", False)]
    if unreviewed:
        print(f"Warning: {len(unreviewed)} question(s) not marked reviewed.")
    return questions


def rank_in(ids, expected):
    ranks = [ids.index(a) + 1 for a in expected if a in ids]
    return min(ranks) if ranks else None


def run(questions, retriever):
    vector = retriever.fusion._retrievers[0]  # the vector retriever, for the baseline
    rows = []
    for n, q in enumerate(questions, 1):
        history = [(h["role"], h["content"]) for h in q.get("history", [])]
        res = retriever.retrieve(q["question"], history)
        handed = [a.rule_id for a in res.articles if not a.added_by_rule][:TOP_N]
        reranked_ids = [rid for rid, _ in res.reranked]
        expected = q["expected_articles"]
        row = {**q,
               "standalone_question": res.standalone_question, "rewritten": res.rewritten,
               "candidates": res.candidates, "reranked": res.reranked, "handed": handed,
               "le_mans_added": any(a.added_by_rule for a in res.articles),
               "best_score": res.best_score}
        if expected:
            base_ids = [h.node.metadata["rule_id"] for h in vector.retrieve(res.standalone_question)][:TOP_N]
            row.update({
                "rank_reranked": rank_in(reranked_ids, expected),   # rank among the 10 after reranking
                "hit": rank_in(handed, expected) is not None,
                "rank1": rank_in(handed, expected) == 1,
                "in_candidates": rank_in(res.candidates, expected) is not None,
                "baseline_hit": rank_in(base_ids, expected) is not None,
                "baseline_rank1": rank_in(base_ids, expected) == 1,
            })
        rows.append(row)
        print(f"\r{n}/{len(questions)} questions", end="", flush=True)
    print()
    return rows


def pct(rows, key):
    return sum(1 for r in rows if r[key]) / len(rows) if rows else 0.0


def quantiles(values):
    v = sorted(values)
    if not v:
        return "n/a"
    q = lambda p: v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))]
    return f"min {v[0]:.3f} · p10 {q(0.1):.3f} · median {q(0.5):.3f} · p90 {q(0.9):.3f} · max {v[-1]:.3f}"


def report(rows, path, threshold, meta_line):
    scored = [r for r in rows if r["expected_articles"]]
    off = [r for r in rows if r["type"] == "off_topic"]
    follow = [r for r in rows if r.get("history")]
    hit5 = pct(scored, "hit")
    passed = hit5 >= threshold
    L = [f"# Retrieval evaluation – full pipeline (ADR-004)", "",
         f"- Date: {datetime.now():%Y-%m-%d %H:%M}",
         f"- Questions: `{path}` ({len(rows)}: {len(scored)} with expected articles, {len(off)} off-topic, "
         f"{len(follow)} follow-ups)",
         f"- {meta_line}",
         "- Pipeline: rewriting of follow-ups → vector + BM25 (reciprocal rank fusion) → 10 candidates → "
         "rerank-3-lite → 5 articles; no relevance threshold", ""]
    if scored:
        L += [f"**Hit@5 (articles handed to the LLM): {hit5:.0%} ({sum(r['hit'] for r in scored)}/{len(scored)}) "
              f"– threshold {threshold:.0%} – {'PASS' if passed else 'FAIL'}**", "",
              "| Metric | Full pipeline | Vector only (baseline) |", "|---|---|---|",
              f"| Hit@5 | {hit5:.0%} | {pct(scored, 'baseline_hit'):.0%} |",
              f"| Rank 1 | {pct(scored, 'rank1'):.0%} | {pct(scored, 'baseline_rank1'):.0%} |",
              f"| Candidate recall@10 | {pct(scored, 'in_candidates'):.0%} | – |", ""]
        rec = pct(scored, "in_candidates")
        missing = sum(1 for r in scored if not r["in_candidates"])
        L.append(f"Candidate pool (ADR-004): expected article missing from the 10 candidates for {missing} "
                 f"question(s) – {'raise the pool to 20' if missing > 1 else 'pool of 10 kept'}.")
        L += ["", "## By question type", "", "| Type | Questions | Hit@5 | Rank 1 | Baseline hit@5 |",
              "|---|---|---|---|---|"]
        by = defaultdict(list)
        for r in scored:
            by[r["type"]].append(r)
        for t, rs in sorted(by.items()):
            L.append(f"| {t} | {len(rs)} | {pct(rs, 'hit'):.0%} | {pct(rs, 'rank1'):.0%} | "
                     f"{pct(rs, 'baseline_hit'):.0%} |")
        misses = [r for r in scored if not r["hit"]]
        L += ["", f"## Misses ({len(misses)})", ""] + (["None."] if not misses else [])
        for r in misses:
            rk = r["rank_reranked"]
            L += [f"- **{r['id']}** ({r['type']}) {r['question']}",
                  f"  - searched as: {r['standalone_question']}" if r["rewritten"] else None,
                  f"  - expected {', '.join(r['expected_articles'])}: "
                  f"{f'rank {rk} after reranking' if rk else 'not among the 10 candidates'}",
                  f"  - handed: {', '.join(r['handed'])}"]
        long_rows = [r for r in scored if set(r["expected_articles"]) & LONG_ARTICLES]
        if long_rows:
            L += ["", "## Long articles (ADR-003 Amendment 1)", ""]
            for r in long_rows:
                L.append(f"- {r['id']}: expected {', '.join(r['expected_articles'])} – rank after reranking "
                         f"{r['rank_reranked'] or '>10'} {'✓' if r['hit'] else '✗'}")

    L += ["", "## Calibration data for the relevance threshold (best reranker score)", "",
          f"- In-scope questions ({len(scored)}): {quantiles([r['best_score'] for r in scored if r['best_score'] is not None])}",
          f"- Off-topic questions ({len(off)}): {quantiles([r['best_score'] for r in off if r['best_score'] is not None])}"]
    if scored and off:
        cands = sorted({round(r["best_score"], 2) for r in off + scored if r["best_score"] is not None})
        L += ["", "| Threshold | In-scope refused | Off-topic still answered |", "|---|---|---|"]
        for t in cands:
            ref = sum(1 for r in scored if r["best_score"] is not None and r["best_score"] < t)
            acc = sum(1 for r in off if r["best_score"] is not None and r["best_score"] >= t)
            L.append(f"| {t:.2f} | {ref}/{len(scored)} | {acc}/{len(off)} |")
        L.append("\nADR-004: place the threshold between the two groups, on the low side "
                 "(refusing a valid question is worse than handing a weak article).")
    if off:
        L += ["", "## Off-topic questions", ""]
        for r in off:
            L.append(f"- {r['id']} [{r['best_score']:.3f}] {r['question']} → {', '.join(r['handed'])}"
                     f"{' (+1.2.4 Le Mans rule)' if r['le_mans_added'] else ''}")
    if follow:
        L += ["", "## Follow-up rewriting", ""]
        for r in follow:
            L += [f"- **{r['id']}** {r['question']} {'✓' if r.get('hit') else '✗'}",
                  f"  - rewritten: {r['standalone_question'] if r['rewritten'] else '(unchanged)'}",
                  f"  - expected:  {r.get('expected_standalone', '–')}"]
    return "\n".join(l for l in L if l is not None) + "\n", passed if scored else True


def main():
    p = argparse.ArgumentParser(description="Evaluate the ADR-004 retrieval pipeline.")
    p.add_argument("--questions", default="eval/eval_questions_en.jsonl")
    p.add_argument("--index", default="output/chroma")
    p.add_argument("--out", default="output/eval")
    p.add_argument("--threshold", type=float, default=0.9, help="required hit@5 (default 0.9)")
    args = p.parse_args()

    index_dir = Path(args.index)
    if not (index_dir / "chroma.sqlite3").exists() or not (index_dir / "docstore.json").exists():
        sys.exit(f"Index or docstore not found in {index_dir}: run build_chroma_index.py first.")
    missing = [k for k in ("VOYAGE_API_KEY", "GOOGLE_API_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing environment variable(s): {', '.join(missing)}")

    questions = load_questions(args.questions)
    retriever = WecRetriever.from_index(index_dir, threshold=None)  # scores recorded, nothing refused
    import chromadb
    meta = chromadb.PersistentClient(path=str(index_dir)).get_collection("wec_2026_en").metadata or {}
    meta_line = (f"Index: {meta.get('embed_model')} ({meta.get('embed_dimension')} dims), pipeline "
                 f"`{meta.get('pipeline_version')}`, built {meta.get('built_on')}")
    rows = run(questions, retriever)
    text, passed = report(rows, args.questions, args.threshold, meta_line)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"pipeline_{Path(args.questions).stem}_{datetime.now():%Y%m%d-%H%M}"
    with (out / f"{stem}.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / f"{stem}.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved: {out / stem}.md and .jsonl")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
