import logging
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswVectorSearchAlgorithmConfiguration,
    VectorSearchProfile,
)
from backend.app.config import get_settings
from backend.app.azure_auth import get_token_credential
from backend.app.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()


def ensure_fdsc_index(index_name: str = "fdsc-index"):
    credential = get_token_credential()
    client = SearchIndexClient(
        endpoint=f"https://{settings.AZURE_SEARCH_NAME}.search.azure.us",
        credential=credential,
    )

    existing = [i.name for i in client.list_indexes()]
    if index_name in existing:
        logger.info("Index %s already exists", index_name)
        return

    fields = [
        SimpleField(name="id", type="Edm.String", key=True),
        SearchableField(name="content", type="Edm.String", analyzer_name="en.microsoft"),
        SimpleField(name="page", type="Edm.Int32", filterable=True),
        SimpleField(name="blob_uri", type="Edm.String"),
        SimpleField(
            name="content_vector",
            type="Collection(Edm.Single)",
            searchable=True,
            vector_search_dimensions=1536,
            vector_search_profile_name="fdsc-hnsw",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[
            HnswVectorSearchAlgorithmConfiguration(
                name="fdsc-hnsw",
                kind="hnsw",
            )
        ],
        profiles=[
            VectorSearchProfile(
                name="fdsc-hnsw",
                algorithm_configuration_name="fdsc-hnsw",
            )
        ],
    )

    index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
    client.create_index(index)
    logger.info("Created index %s", index_name)


if __name__ == "__main__":
    ensure_fdsc_index()
    logger.info("Infra check complete.")
