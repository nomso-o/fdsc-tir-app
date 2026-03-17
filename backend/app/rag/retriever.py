import logging
from typing import List
from langchain_core.documents import Document
from azure.search.documents.models import Vector
from ..azure_clients import embeddings, get_search_client

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

    def invoke(self, query: str) -> List[Document]:
        try:
            emb = embeddings.embed_query(query)
        except Exception:
            logger.exception("Failed to embed query for hybrid search")
            return []

        vector = Vector(value=emb, k=self.k, fields="content_vector")
        results = self.client.search(
            search_text=query,
            vector=vector,
            top=self.k,
            select=["id", "content", "page", "blob_uri"],
        )

        docs: List[Document] = []
        for r in results:
            docs.append(
                Document(
                    page_content=r.get("content", "") or "",
                    metadata={
                        "id": r.get("id"),
                        "page": r.get("page"),
                        "blob_uri": r.get("blob_uri"),
                    },
                )
            )
        return docs


def get_fdsc_hybrid_retriever(index_name: str):
    return FDSCHybridRetriever(index_name=index_name, k=5)
