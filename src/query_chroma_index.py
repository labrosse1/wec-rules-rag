"""Ask questions to the WEC index through the full retrieval pipeline (ADR-004):
follow-up rewriting, hybrid search (vector + BM25), Voyage reranker, top 5 articles,
Le Mans rule, relevance threshold (0.60). No answer is generated: the script shows the articles that would be
handed to the answer LLM.

Chat mode (default): the conversation history is kept, so follow-up messages
such as "And for LMGT3?" are rewritten into standalone questions.
    python query_chroma_index.py
    commands in chat mode: empty line or "quit" to stop, "/new" to start a new conversation

One question (no history):
    python query_chroma_index.py "How many points does the winner of a 6h race score?"

Options:
    --show-text        print the text of each article (as the answer LLM will see it)
    --show-candidates  print the 20 fused candidates before reranking
    --index DIR        index folder (default output/chroma)

Requires VOYAGE_API_KEY and GOOGLE_API_KEY.
"""

import argparse
import os
import sys
from pathlib import Path

from retrieval import WecRetriever


def check_setup(index_dir):
    if not (index_dir / "chroma.sqlite3").exists() or not (index_dir / "docstore.json").exists():
        sys.exit(f"Index or docstore not found in {index_dir}\n"
                 f"Run build_chroma_index.py first, from the project root (current folder: {Path.cwd()}).")
    missing = [k for k in ("VOYAGE_API_KEY", "GOOGLE_API_KEY") if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing environment variable(s): {', '.join(missing)}\n"
                 "  macOS / Linux:       export NAME=value\n"
                 "  Windows PowerShell:  $env:NAME=\"value\"\n"
                 "  Windows cmd:         set NAME=value")


def show(result, show_text, show_candidates):
    if result.rewritten:
        print(f"\nRewritten as: {result.standalone_question}")
    if show_candidates:
        print(f"Candidates (fusion order): {', '.join(result.candidates)}")
    if result.below_threshold:
        print(f"No article above the relevance threshold (best score {result.best_score:.3f}).")
        return
    for rank, a in enumerate(result.articles, 1):
        score = "added: Le Mans rule" if a.added_by_rule else f"score {a.score:.3f}"
        print(f"\n{rank}. [{score}] {a.rule_id}")
        print(f"   {a.citation}")
        if show_text:
            print("   " + a.text.replace("\n", "\n   "))


def summary(result):
    """Short assistant turn kept in the history, so later follow-ups can be rewritten."""
    if not result.articles:
        return "No relevant article found."
    return "Relevant articles: " + "; ".join(f"{a.rule_id} ({a.breadcrumb})" for a in result.articles)


def main():
    p = argparse.ArgumentParser(description="Query the WEC index (ADR-004 retrieval).")
    p.add_argument("question", nargs="?", help="one question (omit for chat mode)")
    p.add_argument("--show-text", action="store_true")
    p.add_argument("--show-candidates", action="store_true")
    p.add_argument("--index", default="output/chroma")
    args = p.parse_args()

    index_dir = Path(args.index)
    check_setup(index_dir)
    retriever = WecRetriever.from_index(index_dir)

    if args.question:
        show(retriever.retrieve(args.question), args.show_text, args.show_candidates)
        return

    history = []
    print("Chat mode: empty line or 'quit' to stop, '/new' to start a new conversation.")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not message or message.lower() in ("quit", "exit", "q"):
            break
        if message == "/new":
            history = []
            print("New conversation.")
            continue
        result = retriever.retrieve(message, history)
        show(result, args.show_text, args.show_candidates)
        # The answer LLM is not part of this step: the assistant turn stored in the
        # history is a summary of the retrieved articles.
        history += [("user", message), ("assistant", summary(result))]


if __name__ == "__main__":
    main()
