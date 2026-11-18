"""Retrieval pipeline of the WEC RAG (ADR-004).

    user message (+ chat history)
      -> follow-up rewritten into a standalone question (Gemini), first message kept as is
      -> vector search (Chroma, Voyage) + BM25 (docstore), merged by reciprocal rank fusion
      -> top 20 candidates reranked with Voyage rerank-3-lite
      -> top 5 articles (+ Article 1.2.4 when the question is about Le Mans)
      -> relevance threshold: if the best reranker score is below 0.60, no article is returned

Environment variables: VOYAGE_API_KEY (embeddings, reranker), GOOGLE_API_KEY (Gemini).

Usage from code:
    from retrieval import WecRetriever
    retriever = WecRetriever.from_index("output/chroma")
    result = retriever.retrieve("And for LMGT3?", history=[("user", "..."), ("assistant", "...")])
    for article in result.articles: ...
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import chromadb
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.chroma import ChromaVectorStore

COLLECTION = "wec_2026_en"
REWRITE_MODEL = "gemini-3.5-flash"   # check the exact model id in your Google AI account
RERANK_MODEL = "rerank-3-lite"
CANDIDATES = 20                       # fused candidates passed to the reranker (ADR-004, evaluation result)
TOP_N = 5                             # articles handed to the answer LLM (ADR-004)
THRESHOLD = 0.60                      # min. best reranker score, calibrated on set 2 (ADR-004)
HISTORY_EXCHANGES = 3                 # exchanges (user + assistant) seen by the rewriting, as for the answer
LE_MANS_ARTICLE = "1.2.4"
RE_LE_MANS = re.compile(r"le\s*mans|24\s*hours|\b24\s*h\b", re.I)

REWRITE_PROMPT = """You rewrite the last message of a conversation about the FIA World Endurance \
Championship Sporting Regulations into a standalone question for a search engine.

Rules:
- If the last message is already understandable on its own, return it unchanged.
- Otherwise, add only what the conversation says it refers to (category, race length, session, topic...).
- Do not answer the question. Do not add facts that are not in the conversation.
- Keep it in English and return only the question, with no quotes and no explanation.

Conversation:
{history}

Last message: {message}

Standalone question:"""

History = Sequence[Tuple[str, str]]  # (role, text), role = "user" or "assistant"


@dataclass
class RetrievedArticle:
    rule_id: str
    citation: str
    breadcrumb: str
    text: str                      # what the answer LLM sees (citation, flags, breadcrumb + text)
    score: Optional[float]         # reranker relevance score; None when added by the Le Mans rule
    added_by_rule: bool = False


@dataclass
class RetrievalResult:
    message: str
    standalone_question: str
    rewritten: bool
    candidates: List[str]          # the fused candidates (20), in fusion order, before reranking
    reranked: List[Tuple[str, float]] = field(default_factory=list)  # all candidates after reranking
    articles: List[RetrievedArticle] = field(default_factory=list)
    best_score: Optional[float] = None
    below_threshold: bool = False  # True: no article is handed to the LLM


class WecRetriever:
    def __init__(self, vector_index, docstore, llm, reranker, candidates=CANDIDATES, top_n=TOP_N,
                 threshold=THRESHOLD):
        self.docstore = docstore
        self.llm = llm
        self.reranker = reranker
        self.top_n = top_n
        self.threshold = threshold  # None disables it (used by evaluate_retrieval.py to record scores)
        vector = vector_index.as_retriever(similarity_top_k=candidates)
        bm25 = BM25Retriever.from_defaults(nodes=list(docstore.docs.values()), similarity_top_k=candidates,
                                           language="en")
        self.fusion = QueryFusionRetriever(
            [vector, bm25],
            llm=llm,               # required by the class, not called: num_queries=1
            mode="reciprocal_rerank",
            similarity_top_k=candidates,
            num_queries=1,         # no generated query variants (ADR-004: no other transformation)
            use_async=False,
        )

    @classmethod
    def from_index(cls, index_dir="output/chroma", llm=None, embed_model=None, reranker=None, **kw):
        index_dir = Path(index_dir)
        collection = chromadb.PersistentClient(path=str(index_dir)).get_collection(COLLECTION)
        meta = collection.metadata or {}
        if embed_model is None:
            from llama_index.embeddings.voyageai import VoyageEmbedding
            embed_model = VoyageEmbedding(model_name=meta["embed_model"], output_dimension=meta["embed_dimension"])
        if llm is None:
            from llama_index.llms.google_genai import GoogleGenAI
            llm = GoogleGenAI(model=REWRITE_MODEL, temperature=0)
        if reranker is None:
            from llama_index.postprocessor.voyageai_rerank import VoyageAIRerank
            reranker = VoyageAIRerank(model=RERANK_MODEL, top_n=CANDIDATES)  # scores all, cut below
        vector_index = VectorStoreIndex.from_vector_store(ChromaVectorStore(chroma_collection=collection),
                                                          embed_model=embed_model)
        docstore = SimpleDocumentStore.from_persist_path(str(index_dir / "docstore.json"))
        return cls(vector_index, docstore, llm, reranker, **kw)

    # ------------------------------------------------------------------ steps
    def rewrite(self, message: str, history: History) -> str:
        if not history:
            return message  # first message: searched as it is
        recent = list(history)[-2 * HISTORY_EXCHANGES:]  # last 3 exchanges = last 6 messages
        convo = "\n".join(f"{role.capitalize()}: {text}" for role, text in recent)
        out = self.llm.complete(REWRITE_PROMPT.format(history=convo, message=message)).text.strip()
        return out.strip('"').strip() or message

    def _article(self, nws: NodeWithScore, added_by_rule=False) -> RetrievedArticle:
        from llama_index.core.schema import MetadataMode
        m = nws.node.metadata
        return RetrievedArticle(rule_id=m["rule_id"], citation=m["citation"], breadcrumb=m["breadcrumb"],
                                text=nws.node.get_content(metadata_mode=MetadataMode.LLM),
                                score=None if added_by_rule else nws.score, added_by_rule=added_by_rule)

    def retrieve(self, message: str, history: History = ()) -> RetrievalResult:
        question = self.rewrite(message, history)
        candidates = self.fusion.retrieve(question)
        reranked = self.reranker.postprocess_nodes(candidates, query_bundle=QueryBundle(question))
        result = RetrievalResult(message=message, standalone_question=question,
                                 rewritten=question != message,
                                 candidates=[c.node.metadata["rule_id"] for c in candidates])
        result.reranked = [(n.node.metadata["rule_id"], n.score) for n in reranked]
        result.best_score = reranked[0].score if reranked else None
        if self.threshold is not None and (result.best_score is None or result.best_score < self.threshold):
            result.below_threshold = True
            return result
        result.articles = [self._article(n) for n in reranked[: self.top_n]]
        if RE_LE_MANS.search(question) and LE_MANS_ARTICLE not in [a.rule_id for a in result.articles]:
            node = self.docstore.get_node(LE_MANS_ARTICLE)
            result.articles.append(self._article(NodeWithScore(node=node, score=None), added_by_rule=True))
        return result
