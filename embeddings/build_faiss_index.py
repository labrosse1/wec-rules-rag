"""Test branch: chunk the extracted WEC rules and build a FAISS index with
Voyage embeddings, then run a test query.

Simplified chunking: one chunk per article, no splitting.
Kept from ADR-003: Appendix 1 (blank template) is excluded, and the
breadcrumb is embedded together with the article text.

Requires the environment variable VOYAGE_API_KEY.

Usage:
    python build_faiss_index.py                         # build + default test query
    python build_faiss_index.py --query "How many points does the winner of a 6h race score?"
    python build_faiss_index.py --query "..." --no-build  # query an existing index
"""

import argparse
import json
from datetime import date
from pathlib import Path
import os
from dotenv import load_dotenv

import faiss
import numpy as np
import voyageai

load_dotenv()

MODEL = "voyage-4-lite"
DIMENSION = 1024
BATCH = 128  # Voyage accepts up to 1,000 texts per request
DEFAULT_QUERY = "How many dry-weather tyres can a Hypercar use in qualifying and race for a 6 hour race?"


# --------------------------------------------------------------------------- chunking

def make_chunks(rules_path):
    """One chunk per article; Appendix 1 excluded."""
    data = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    chunks = []
    for rule in data["rules"]:
        if rule["appendix"] == "APPENDIX 1":
            continue
        chunks.append({
            "id": rule["id"],
            "embed_text": f"{rule['breadcrumb']}\n\n{rule['text']}",  # what Voyage sees
            "text": rule["text"],                                     # what the LLM will see
            "breadcrumb": rule["breadcrumb"],
            "title": rule["title"],
            "article": rule["article"],
            "appendix": rule["appendix"],
            "chapter": rule["chapter"],
            "section": rule["section"],
            "part": rule["part"],
            "pages": rule["pages"],
            "level": rule["level"],
            "has_table": bool(rule["tables"]),
            "flags": [f for f in rule["flags"] if f != "contains_table"],
        })
    return chunks, data["published"]


# --------------------------------------------------------------------------- embeddings

def embed(client, texts, input_type):
    vectors = []
    for i in range(0, len(texts), BATCH):
        result = client.embed(texts[i:i + BATCH], model=MODEL, input_type=input_type,
                              output_dimension=DIMENSION)
        vectors.extend(result.embeddings)
    matrix = np.asarray(vectors, dtype="float32")
    faiss.normalize_L2(matrix)  # unit vectors: inner product == cosine similarity
    return matrix


# --------------------------------------------------------------------------- build / query

def build(rules_path, out_dir, client):
    chunks, published = make_chunks(rules_path)
    vectors = embed(client, [c["embed_text"] for c in chunks], input_type="document")
    if vectors.shape != (len(chunks), DIMENSION):
        raise SystemExit(f"Unexpected embedding shape {vectors.shape}")

    index = faiss.IndexFlatIP(DIMENSION)
    index.add(vectors)

    out_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(out_dir / "index.faiss"))
    # position i in the index <-> chunks[i]
    (out_dir / "chunks.json").write_text(json.dumps({
        "model": MODEL,
        "dimension": DIMENSION,
        "metric": "cosine (IndexFlatIP on L2-normalised vectors)",
        "source_published": published,
        "built_on": date.today().isoformat(),
        "chunks": chunks,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    sizes = sorted(len(c["embed_text"].split()) for c in chunks)
    print(f"{len(chunks)} chunks embedded and indexed -> {out_dir}")
    print(f"words per chunk: min {sizes[0]}, median {sizes[len(sizes) // 2]}, max {sizes[-1]}")


def search(query, out_dir, client, k=5):
    index = faiss.read_index(str(out_dir / "index.faiss"))
    meta = json.loads((out_dir / "chunks.json").read_text(encoding="utf-8"))
    if meta["model"] != MODEL or meta["dimension"] != DIMENSION:
        raise SystemExit(f"Index built with {meta['model']}/{meta['dimension']}, "
                         f"query uses {MODEL}/{DIMENSION}: rebuild the index.")
    q = embed(client, [query], input_type="query")
    scores, positions = index.search(q, k)
    print(f"\nQuery: {query}")
    for rank, (score, pos) in enumerate(zip(scores[0], positions[0]), 1):
        c = meta["chunks"][pos]
        print(f"{rank}. [{score:.3f}] {c['id']} – {c['breadcrumb']} (p. {', '.join(map(str, c['pages']))})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rules", default="output/2026_WEC_rules_en.v2.json")
    p.add_argument("--out", default="output/faiss")
    p.add_argument("--query", default=DEFAULT_QUERY)
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--no-build", action="store_true", help="only query an existing index")
    args = p.parse_args()

    client = voyageai.Client() 
    out_dir = Path(args.out)
    if not args.no_build:
        build(args.rules, out_dir, client)
    search(args.query, out_dir, client, args.k)


if __name__ == "__main__":
    main()
