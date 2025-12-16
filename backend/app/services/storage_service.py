import logging
from typing import List, Dict, Any
from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos.exceptions import CosmosResourceNotFoundError, CosmosHttpResponseError
from ..azure_clients import blob_service_client, cosmos_client
from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

TIR_DATASET_CONTAINER = "tir-datasets"
TIR_RESULTS_CONTAINER = "tir-results"
TIR_SCORES_CONTAINER = "tir_scores"


def list_tir_files(prefix: str) -> List[str]:
    container = blob_service_client.get_container_client(TIR_DATASET_CONTAINER)
    return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]


def download_tir_file_text(blob_name: str) -> str:
    container = blob_service_client.get_container_client(TIR_DATASET_CONTAINER)
    blob = container.download_blob(blob_name)
    return blob.content_as_text()


def upload_result_markdown(blob_name: str, content: str) -> str:
    container = blob_service_client.get_container_client(TIR_RESULTS_CONTAINER)
    container.upload_blob(name=blob_name, data=content, overwrite=True)
    return blob_name


def _get_tir_scores_container():
    db = cosmos_client.get_database_client(settings.AZURE_COSMOSDB_NAME)
    return db.get_container_client(TIR_SCORES_CONTAINER)


def save_structured_results(session_id: str, results: List[Dict[str, Any]]) -> None:
    """
    Persist structured TIR results for a session into Cosmos DB.
    """
    container = _get_tir_scores_container()
    doc = {
        "id": session_id,
        "session_id": session_id,
        "results": results,
    }
    container.upsert_item(doc)
    logger.info("Saved structured TIR results for session %s", session_id)


def load_structured_results(session_id: str) -> List[Dict[str, Any]]:
    """
    Load structured TIR results for a session from Cosmos DB.
    """
    container = _get_tir_scores_container()
    try:
        doc = container.read_item(item=session_id, partition_key=session_id)
        return doc.get("results", [])
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        logger.warning("Structured results not found for session %s", session_id)
    except CosmosHttpResponseError as ex:
        logger.error("Error reading structured results for session %s: %s", session_id, ex)
    return []


def update_markdown_in_results(session_id: str, tir_blob_path: str, markdown: str) -> bool:
    results = load_structured_results(session_id)
    updated = False
    for r in results:
        if r.get("tir_blob_path") == tir_blob_path:
            r["markdown_table"] = markdown
            updated = True
            break

    if updated:
        save_structured_results(session_id, results)
    else:
        logger.warning(
            "Could not find TIR %s in stored results for session %s to update markdown",
            tir_blob_path,
            session_id,
        )
    return updated
