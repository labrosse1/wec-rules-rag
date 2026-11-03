"""Ask questions to the FAISS index built by build_faiss_index.py.

Interactive mode (type your questions, empty line or "quit" to stop):
    python query_faiss_index.py

One question:
    python query_faiss_index.py "How many points does the winner of a 6h race score?"

Options:
    --k 5          number of results (default 5)
    --show-text    print the text of each retrieved article
    --index DIR    index folder (default output/faiss)

Requires the environment variable VOYAGE_API_KEY.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import faiss
import numpy as np
import voyageai

load_dotenv()

def load_index(index_dir):
    index_file, meta_file = index_dir / "index.faiss", index_dir / "chunks.json"
    missing = [str(f) for f in (index_file, meta_file) if not f.exists()]
    if missing:
        sys.exit(f"Index not found: {', '.join(missing)}\n"
                 f"Run build_faiss_index.py first, from the project root "
                 f"(current folder: {Path.cwd()}).")
    index = faiss.read_index(str(index_file))
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    if index.ntotal != len(meta["chunks"]) or index.d != meta["dimension"]:
        sys.exit("index.faiss and chunks.json do not match: rebuild the index.")
    return index, meta


def make_client():
    if not os.environ.get("VOYAGE_API_KEY"):
        sys.exit("VOYAGE_API_KEY is not set.\n"
                 "  macOS / Linux:       export VOYAGE_API_KEY=your_key\n"
                 "  Windows PowerShell:  $env:VOYAGE_API_KEY=\"your_key\"\n"
                 "  Windows cmd:         set VOYAGE_API_KEY=your_key")
    return voyageai.Client()


def ask(question, index, meta, client, k, show_text):
    # the query must be embedded with the same model and dimension as the index
    result = client.embed([question], model=meta["model"], input_type="query",
                          output_dimension=meta["dimension"])
    q = np.asarray(result.embeddings, dtype="float32")
    faiss.normalize_L2(q)
    scores, positions = index.search(q, k)
    print(f"\nQuestion: {question}")
    for rank, (score, pos) in enumerate(zip(scores[0], positions[0]), 1):
        c = meta["chunks"][pos]
        pages = ", ".join(map(str, c["pages"]))
        print(f"\n{rank}. [score {score:.3f}] {c['id']}  (p. {pages})")
        print(f"   {c['breadcrumb']}")
        if c["flags"]:
            print(f"   flags: {'; '.join(c['flags'])}")
        if show_text:
            print("   " + c["text"].replace("\n", "\n   "))


def main():
    p = argparse.ArgumentParser(description="Query the WEC FAISS index.")
    p.add_argument("question", nargs="?", help="question (omit for interactive mode)")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--show-text", action="store_true")
    p.add_argument("--index", default="output/faiss")
    args = p.parse_args()

    index, meta = load_index(Path(args.index))
    client = make_client()
    print(f"Index: {index.ntotal} chunks, {meta['model']} ({meta['dimension']} dims), "
          f"source published {meta['source_published']}")

    if args.question:
        ask(args.question, index, meta, client, args.k, args.show_text)
        return
    while True:
        try:
            question = input("\nYour question (empty to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("quit", "exit", "q"):
            break
        ask(question, index, meta, client, args.k, args.show_text)


if __name__ == "__main__":
    main()
