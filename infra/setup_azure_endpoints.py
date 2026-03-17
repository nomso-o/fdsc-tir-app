import logging
from azure.core.exceptions import ResourceExistsError
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    VectorSearch,
    HnswVectorSearchAlgorithmConfiguration,
    VectorSearchProfile,
)
from azure.storage.blob import ResourceExistsError as BlobResourceExistsError
from azure.cosmos import PartitionKey

from backend.app.config import get_settings
from backend.app.azure_auth import get_token_credential
from backend.app.azure_clients import blob_service_client, cosmos_client
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
        SimpleField(name="doc_id", type="Edm.String", filterable=True, facetable=True, sortable=True),
        SimpleField(name="doc_namespace", type="Edm.String", filterable=True, facetable=True),
        SimpleField(name="chunk_index", type="Edm.Int32", filterable=True, sortable=True),
        SimpleField(name="source_file", type="Edm.String"),
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


def ensure_blob_containers():
    required = ["tir-datasets", "tir-results", "fdsc-docs"]
    for name in required:
        container = blob_service_client.get_container_client(name)
        try:
            container.create_container()
            logger.info("Created blob container %s", name)
        except BlobResourceExistsError:
            logger.info("Blob container %s already exists", name)


def ensure_cosmos_artifacts():
    db = cosmos_client.create_database_if_not_exists(id=settings.AZURE_COSMOSDB_NAME)
    logger.info("Ensured Cosmos database %s", settings.AZURE_COSMOSDB_NAME)

    definitions = [
        ("chat_history", "/session_id"),
        ("tir_scores", "/session_id"),
        ("fdsc_documents", "/id"),
    ]
    for container_name, pk_path in definitions:
        try:
            db.create_container_if_not_exists(
                id=container_name,
                partition_key=PartitionKey(path=pk_path),
            )
            logger.info("Ensured Cosmos container %s (pk=%s)", container_name, pk_path)
        except ResourceExistsError:
            logger.info("Cosmos container %s already exists", container_name)


if __name__ == "__main__":
    ensure_blob_containers()
    ensure_cosmos_artifacts()
    ensure_fdsc_index()
    logger.info("Infra check complete.")
