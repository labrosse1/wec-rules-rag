"""Build the ChromaDB index of the WEC Sporting Regulations with LlamaIndex
and Voyage embeddings (ADR-003, with one node per article: no splitting).

* one TextNode per article of the extracted JSON, id = article id;
* Appendix 1 (blank template) is excluded;
* the embedding sees the breadcrumb + the text; the answer LLM will see the
  citation, the flags and the breadcrumb + the text;
* full rebuild: the collection is deleted and recreated, with cosine distance;
* the nodes are also saved in a LlamaIndex docstore (for a later BM25 search).

Requires the environment variable VOYAGE_API_KEY.

Usage: python build_chroma_index.py [--rules output/2026_WEC_rules_en.v2.json] [--out output/chroma]
"""

import argparse
import json
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

import chromadb
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore

MODEL = "voyage-4-lite"
DIMENSION = 1024
COLLECTION = "wec_2026_en"
PIPELINE_VERSION = "adr-003-one-node-per-article"

EMBED_KEYS = {"breadcrumb"}                         # embedded with the text
LLM_KEYS = {"citation", "flags", "breadcrumb"}      # shown to the answer LLM

load_dotenv()

def citation(rule):
    pages = ", ".join(map(str, rule["pages"]))
    if rule["article"]:
        where = f"{rule['appendix'].title()}, Article {rule['article']}" if rule["appendix"] \
            else f"Article {rule['article']}"
    else:
        where = rule["title"] or rule["breadcrumb"]
    return f"FIA WEC Sporting Regulations 2026, {where}, p. {pages}"


def make_nodes(rules_path):
    data = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    nodes = []
    for rule in data["rules"]:
        if rule["appendix"] == "APPENDIX 1":
            continue
        # ChromaDB metadata values must be str / int / float / bool
        metadata = {
            "rule_id": rule["id"],
            "breadcrumb": rule["breadcrumb"],
            "citation": citation(rule),
            "flags": "; ".join(f for f in rule["flags"] if f != "contains_table"),
            "appendix": rule["appendix"] or "",
            "chapter": rule["chapter"] or "",
            "part": rule["part"] or "",
            "section": rule["section"] or "",
            "article": rule["article"] or "",
            "title": rule["title"] or "",
            "level": rule["level"],
            "pages": ", ".join(map(str, rule["pages"])),
            "page_start": rule["pages"][0],
            "has_table": bool(rule["tables"]),
            "is_figure": rule["level"] == "figure",
            "references": ", ".join(rule["references"] + rule.get("related_articles", [])),
            "source_published": data["published"],
            "pipeline_version": PIPELINE_VERSION,
            "embed_model": MODEL,
            "embed_dimension": DIMENSION,
        }
        nodes.append(TextNode(
            id_=rule["id"],
            text=rule["text"],
            metadata=metadata,
            excluded_embed_metadata_keys=[k for k in metadata if k not in EMBED_KEYS],
            # an empty "flags:" line would only add noise for the LLM
            excluded_llm_metadata_keys=[k for k in metadata
                                        if k not in LLM_KEYS or (k == "flags" and not metadata[k])],
            metadata_template="{key}: {value}",
            text_template="{metadata_str}\n\n{content}",
        ))
    return nodes, data["published"]


def build(rules_path, out_dir, embed_model):
    nodes, published = make_nodes(rules_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(out_dir))
    if COLLECTION in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION)  # full rebuild (ADR-003)
    collection = client.create_collection(
        COLLECTION,
        configuration={"hnsw": {"space": "cosine"}},  # Chroma's default is L2
        metadata={"embed_model": MODEL, "embed_dimension": DIMENSION,
                  "source_published": published, "pipeline_version": PIPELINE_VERSION,
                  "built_on": date.today().isoformat()},
    )

    docstore = SimpleDocumentStore()
    docstore.add_documents(nodes)
    storage = StorageContext.from_defaults(vector_store=ChromaVectorStore(chroma_collection=collection),
                                           docstore=docstore)
    VectorStoreIndex(nodes, storage_context=storage, embed_model=embed_model, show_progress=True)
    docstore.persist(persist_path=str(out_dir / "docstore.json"))

    print(f"{collection.count()} nodes embedded with {MODEL} ({DIMENSION} dims) "
          f"-> collection '{COLLECTION}' in {out_dir}")
    print(f"docstore: {out_dir / 'docstore.json'} ({len(docstore.docs)} nodes)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--rules", default="output/2026_WEC_rules_en.v2.json")
    p.add_argument("--out", default="output/chroma")
    args = p.parse_args()
    embed_model = VoyageEmbedding(model_name=MODEL, output_dimension=DIMENSION)  # reads VOYAGE_API_KEY
    build(args.rules, Path(args.out), embed_model)


if __name__ == "__main__":
    main()
