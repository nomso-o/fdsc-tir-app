import logging
from typing import List, Optional
from langchain_core.documents import Document
from azure.search.documents.models import Vector
from ..azure_clients import embeddings, get_search_client
from ..utils.backoff_utils import azure_retry

logger = logging.getLogger(__name__)


class FDSCHybridRetriever:
    """
    Minimal retriever that performs hybrid (keyword + vector) search using Azure Cognitive Search.
    Compatible with LCEL .invoke API.
    """

    def __init__(self, index_name: str, k: int = 5):
        self.k = k
        self.index_name = index_name
        self.client = get_search_client(index_name)

    def invoke(self, query: str, doc_filter: Optional[str] = None) -> List[Document]:
        try:
            emb = _embed_query_with_retry(query)
        except Exception:
            logger.exception("Failed to embed query for hybrid search")
            return []

        vector = Vector(value=emb, k=self.k, fields="content_vector")
        filter_clause = None
        if doc_filter:
            escaped = doc_filter.replace("'", "''")
            filter_clause = f"doc_id eq '{escaped}'"

        try:
            vector_results = _search_with_retry(
                client=self.client,
                search_text="*",
                filter_clause=filter_clause,
                top=self.k,
                vector=vector,
            )
        except Exception:
            logger.exception("Vector retrieval failed for index %s", self.index_name)
            return []
        docs: List[Document] = []
        for r in vector_results:
            docs.append(
                Document(
                    page_content=r.get("content", "") or "",
                    metadata={
                        "id": r.get("id"),
                        "page": r.get("page"),
                        "blob_uri": r.get("blob_uri"),
                        "doc_id": r.get("doc_id"),
                        "doc_namespace": r.get("doc_namespace"),
                        "chunk_index": r.get("chunk_index"),
                        "source_file": r.get("source_file"),
                        "retrieval_mode": "vector",
                    },
                )
            )

        if len(docs) >= self.k:
            return docs

        logger.info(
            "Vector retrieval returned %d chunks (<%d); falling back to search text",
            len(docs),
            self.k,
        )
        try:
            lexical_results = _search_with_retry(
                client=self.client,
                search_text=query,
                filter_clause=filter_clause,
                top=self.k - len(docs),
                vector=None,
            )
        except Exception:
            logger.exception("Lexical fallback retrieval failed for index %s", self.index_name)
            return docs

        for r in lexical_results:
            docs.append(
                Document(
                    page_content=r.get("content", "") or "",
                    metadata={
                        "id": r.get("id"),
                        "page": r.get("page"),
                        "blob_uri": r.get("blob_uri"),
                        "doc_id": r.get("doc_id"),
                        "doc_namespace": r.get("doc_namespace"),
                        "chunk_index": r.get("chunk_index"),
                        "source_file": r.get("source_file"),
                        "retrieval_mode": "lexical",
                    },
                )
            )
        return docs


def get_fdsc_hybrid_retriever(index_name: str):
    return FDSCHybridRetriever(index_name=index_name, k=5)


@azure_retry
def _embed_query_with_retry(query: str) -> List[float]:
    return embeddings.embed_query(query)


@azure_retry
def _search_with_retry(client, search_text: str, filter_clause: Optional[str], top: int, vector: Optional[Vector]):
    if vector is not None:
        return list(
            client.search(
                search_text=search_text,
                vector=vector,
                filter=filter_clause,
                top=top,
                select=[
                    "id",
                    "content",
                    "page",
                    "blob_uri",
                    "doc_id",
                    "doc_namespace",
                    "chunk_index",
                    "source_file",
                ],
            )
        )
    return list(
        client.search(
            search_text=search_text,
            filter=filter_clause,
            top=top,
            select=[
                "id",
                "content",
                "page",
                "blob_uri",
                "doc_id",
                "doc_namespace",
                "chunk_index",
                "source_file",
            ],
        )
    )
