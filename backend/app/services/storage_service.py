import logging
from typing import List, Dict, Any, Set, Optional, Tuple
from datetime import datetime
import time
from azure.core.exceptions import ResourceNotFoundError
from azure.cosmos.exceptions import CosmosResourceNotFoundError, CosmosHttpResponseError
from ..azure_clients import blob_service_client, cosmos_client
from ..config import get_settings
from ..utils.backoff_utils import azure_retry

logger = logging.getLogger(__name__)
settings = get_settings()

TIR_DATASET_CONTAINER = "tir-datasets"
TIR_RESULTS_CONTAINER = "tir-results"
TIR_SCORES_CONTAINER = "tir_scores"
FDSC_DOCS_CONTAINER = "fdsc-docs"
FDSC_DOC_METADATA_CONTAINER = "fdsc_documents"
_CACHE_TTL_SECONDS = 60
_tir_prefix_cache: Dict[str, Tuple[float, List[Dict[str, str]]]] = {}
_fdsc_prefix_cache: Dict[str, Tuple[float, List[Dict[str, str]]]] = {}


def list_tir_files(prefix: str) -> List[str]:
    container = blob_service_client.get_container_client(TIR_DATASET_CONTAINER)
    return _list_tir_files_with_retry(container, prefix)


@azure_retry
def _list_tir_files_with_retry(container, prefix: str) -> List[str]:
    return [blob.name for blob in container.list_blobs(name_starts_with=prefix)]


def download_tir_file_text(blob_name: str) -> str:
    container = blob_service_client.get_container_client(TIR_DATASET_CONTAINER)
    return _download_tir_file_text_with_retry(container, blob_name)


@azure_retry
def _download_tir_file_text_with_retry(container, blob_name: str) -> str:
    blob = container.download_blob(blob_name)
    return blob.content_as_text()


def upload_result_markdown(blob_name: str, content: str) -> str:
    container = blob_service_client.get_container_client(TIR_RESULTS_CONTAINER)
    _upload_result_markdown_with_retry(container, blob_name, content)
    return blob_name


@azure_retry
def _upload_result_markdown_with_retry(container, blob_name: str, content: str) -> None:
    container.upload_blob(name=blob_name, data=content, overwrite=True)


def _get_tir_scores_container():
    db = cosmos_client.get_database_client(settings.AZURE_COSMOSDB_NAME)
    return db.get_container_client(TIR_SCORES_CONTAINER)


def _get_fdsc_docs_metadata_container():
    db = cosmos_client.get_database_client(settings.AZURE_COSMOSDB_NAME)
    return db.get_container_client(FDSC_DOC_METADATA_CONTAINER)


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
    _upsert_item_with_retry(container, doc)
    logger.info("Saved structured TIR results for session %s", session_id)


def load_structured_results(session_id: str) -> List[Dict[str, Any]]:
    """
    Load structured TIR results for a session from Cosmos DB.
    """
    container = _get_tir_scores_container()
    try:
        doc = _read_item_with_retry(container, session_id, session_id)
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


def upsert_structured_result(session_id: str, result: Dict[str, Any]) -> None:
    """
    Insert or replace a single TIR result for the current session.
    """
    results = load_structured_results(session_id)
    target_tir = result.get("tir_blob_path")
    target_filter = result.get("fdsc_doc_filter", "") or ""

    def _same_identity(item: Dict[str, Any]) -> bool:
        item_tir = item.get("tir_blob_path")
        item_filter = item.get("fdsc_doc_filter", "") or ""
        return item_tir == target_tir and item_filter == target_filter

    filtered = [r for r in results if not _same_identity(r)]
    filtered.append(result)
    save_structured_results(session_id, filtered)
    logger.debug(
        "Upserted structured result for %s (fdsc_doc_filter=%s) in session %s",
        result.get("tir_blob_path"),
        target_filter,
        session_id,
    )


def list_dataset_prefixes() -> List[str]:
    """
    Derive logical dataset prefixes by looking at blob path folders.
    """
    container = blob_service_client.get_container_client(TIR_DATASET_CONTAINER)
    prefixes: Set[str] = set()
    for blob in container.list_blobs():
        name = blob.name
        if "/" in name:
            prefixes.add(name.rsplit("/", 1)[0])
        else:
            prefixes.add(name)
    return sorted(prefixes)


def save_fdsc_source_document(doc_id: str, filename: str, data: bytes) -> str:
    """
    Persist the raw uploaded FDSC document for traceability.
    """
    container = blob_service_client.get_container_client(FDSC_DOCS_CONTAINER)
    blob_name = f"{doc_id}/{filename}"
    _upload_blob_with_retry(container, blob_name, data)
    blob_client = container.get_blob_client(blob_name)
    return blob_client.url


def upsert_fdsc_document_metadata(metadata: Dict[str, Any]) -> None:
    """
    Store metadata about ingested FDSC documents in Cosmos DB.
    """
    container = _get_fdsc_docs_metadata_container()
    doc = {
        "id": f"{metadata['index_name']}::{metadata['doc_id']}",
        **metadata,
        "updated_at": metadata.get("updated_at") or datetime.utcnow().isoformat(),
    }
    _upsert_item_with_retry(container, doc)
    logger.info("Upserted FDSC doc %s for index %s", metadata["doc_id"], metadata["index_name"])


def list_fdsc_document_metadata(index_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Retrieve known FDSC documents that have been ingested.
    """
    container = _get_fdsc_docs_metadata_container()
    query = "SELECT * FROM c"
    params = None
    if index_name:
        query += " WHERE c.index_name = @index"
        params = [{"name": "@index", "value": index_name}]
    items = _query_items_with_retry(
        container=container,
        query=query,
        params=params or [],
    )
    return items


def get_fdsc_document_metadata(index_name: str, doc_id: str) -> Optional[Dict[str, Any]]:
    container = _get_fdsc_docs_metadata_container()
    item_id = f"{index_name}::{doc_id}"
    try:
        return _read_item_with_retry(container, item_id, item_id)
    except (CosmosResourceNotFoundError, ResourceNotFoundError):
        return None
    except CosmosHttpResponseError:
        logger.exception("Error reading FDSC metadata for %s", item_id)
        return None


def _get_cached(cache: Dict[str, Tuple[float, List[Dict[str, str]]]], key: str):
    entry = cache.get(key)
    if entry:
        ts, data = entry
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return data
    return None


def _set_cached(cache: Dict[str, Tuple[float, List[Dict[str, str]]]], key: str, data: List[Dict[str, str]]):
    cache[key] = (time.time(), data)


def invalidate_fdsc_prefix_cache():
    _fdsc_prefix_cache.clear()


def invalidate_tir_prefix_cache():
    _tir_prefix_cache.clear()


def list_tir_prefixes() -> List[Dict[str, str]]:
    cached = _get_cached(_tir_prefix_cache, "all")
    if cached is not None:
        return cached

    prefixes = list_dataset_prefixes()
    entries: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for prefix in prefixes:
        if prefix in seen:
            continue
        seen.add(prefix)
        label = prefix.split("/")[-1] or prefix
        entries.append({"value": prefix, "label": label})
    entries.sort(key=lambda x: x["value"])
    _set_cached(_tir_prefix_cache, "all", entries)
    return entries


def list_fdsc_prefixes(index_name: Optional[str] = None) -> List[Dict[str, str]]:
    cache_key = index_name or "__all__"
    cached = _get_cached(_fdsc_prefix_cache, cache_key)
    if cached is not None:
        return cached

    documents = list_fdsc_document_metadata(index_name=index_name)
    entries: List[Dict[str, str]] = []
    seen: Set[str] = set()
    for doc in documents:
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        namespace = doc.get("doc_namespace") or "default"
        key = (doc_id, namespace)
        if key in seen:
            continue
        seen.add(key)
        label = f"{doc_id} ({namespace})" if namespace else doc_id
        entries.append({"value": doc_id, "label": label})
    entries.sort(key=lambda x: x["value"])
    _set_cached(_fdsc_prefix_cache, cache_key, entries)
    return entries


@azure_retry
def _upsert_item_with_retry(container, doc: Dict[str, Any]) -> None:
    container.upsert_item(doc)


@azure_retry
def _read_item_with_retry(container, item: str, partition_key: str) -> Dict[str, Any]:
    return container.read_item(item=item, partition_key=partition_key)


@azure_retry
def _query_items_with_retry(container, query: str, params: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return list(
        container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True,
        )
    )


@azure_retry
def _upload_blob_with_retry(container, blob_name: str, data: bytes) -> None:
    container.upload_blob(name=blob_name, data=data, overwrite=True)
