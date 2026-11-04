"""Ask questions to the ChromaDB index built by build_chroma_index.py.

Interactive mode (type your questions, empty line or "quit" to stop):
    python query_chroma_index.py

One question:
    python query_chroma_index.py "How many points does the winner of a 6h race score?"

Options:
    --k 5          number of results (default 5)
    --show-text    print the text of each retrieved article
    --index DIR    index folder (default output/chroma)

Requires the environment variable VOYAGE_API_KEY.
"""

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

COLLECTION = "wec_2026_en"


def load_collection(index_dir):
    if not (index_dir / "chroma.sqlite3").exists():
        sys.exit(f"Index not found in {index_dir}\n"
                 f"Run build_chroma_index.py first, from the project root (current folder: {Path.cwd()}).")
    client = chromadb.PersistentClient(path=str(index_dir))
    if COLLECTION not in [c.name for c in client.list_collections()]:
        sys.exit(f"Collection '{COLLECTION}' not found in {index_dir}: run build_chroma_index.py.")
    return client.get_collection(COLLECTION)


def check_key():
    load_dotenv()
    if not os.getenv("VOYAGE_API_KEY"):
        sys.exit("VOYAGE_API_KEY is not set.\n"
                 "  macOS / Linux:       export VOYAGE_API_KEY=your_key\n"
                 "  Windows PowerShell:  $env:VOYAGE_API_KEY=\"your_key\"\n"
                 "  Windows cmd:         set VOYAGE_API_KEY=your_key")


def ask(question, retriever, show_text):
    print(f"\nQuestion: {question}")
    for rank, hit in enumerate(retriever.retrieve(question), 1):
        m = hit.node.metadata
        print(f"\n{rank}. [score {hit.score:.3f}] {m['rule_id']}  (p. {m['pages']})")
        print(f"   {m['breadcrumb']}")
        if m.get("flags"):
            print(f"   flags: {m['flags']}")
        if show_text:
            print("   " + hit.node.get_content().replace("\n", "\n   "))


def main():
    p = argparse.ArgumentParser(description="Query the WEC ChromaDB index.")
    p.add_argument("question", nargs="?", help="question (omit for interactive mode)")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--show-text", action="store_true")
    p.add_argument("--index", default="output/chroma")
    args = p.parse_args()

    collection = load_collection(Path(args.index))
    check_key()
    meta = collection.metadata or {}
    # the question must be embedded with the same model and dimension as the index
    embed_model = VoyageEmbedding(model_name=meta["embed_model"], output_dimension=meta["embed_dimension"])
    index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection),
                                               embed_model=embed_model)
    retriever = index.as_retriever(similarity_top_k=args.k)
    print(f"Index: {collection.count()} nodes, {meta['embed_model']} ({meta['embed_dimension']} dims), "
          f"source published {meta.get('source_published')}, built {meta.get('built_on')}")

    if args.question:
        ask(args.question, retriever, args.show_text)
        return
    while True:
        try:
            question = input("\nYour question (empty to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in ("quit", "exit", "q"):
            break
        ask(question, retriever, args.show_text)


if __name__ == "__main__":
    main()
