import logging
from functools import lru_cache
from urllib.parse import urlparse

from azure.core.credentials import AzureKeyCredential, AzureNamedKeyCredential
from azure.core.pipeline.transport import RequestsTransport
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient
from azure.ai.documentintelligence import DocumentIntelligenceClient
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

from .azure_auth import get_openai_token_provider, get_secret_value, get_token_credential
from .config import get_settings
from .utils.backoff_utils import azure_retry

logger = logging.getLogger(__name__)
settings = get_settings()
_token_credential = get_token_credential()
_openai_token_provider = get_openai_token_provider()
_transport = RequestsTransport(
    connection_pool_maxsize=settings.AZURE_HTTP_POOL_MAX,
    connection_timeout=settings.AZURE_HTTP_TIMEOUT_SECONDS,
    read_timeout=settings.AZURE_HTTP_TIMEOUT_SECONDS,
)


llm = AzureChatOpenAI(
    azure_endpoint=str(settings.AZURE_OPENAI_ENDPOINT),
    azure_deployment=settings.AZURE_OPENAI_LLM_DEPLOYMENT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    temperature=0.1,
    azure_ad_token_provider=_openai_token_provider,
)

embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=str(settings.AZURE_OPENAI_ENDPOINT),
    azure_deployment=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    azure_ad_token_provider=_openai_token_provider,
)

doc_intel_client = DocumentIntelligenceClient(
    endpoint=str(settings.AZURE_DOC_INTEL_ENDPOINT),
    credential=_token_credential,
)


@lru_cache
def _get_search_credential():
    if settings.USE_MANAGED_IDENTITY:
        return _token_credential
    key = get_secret_value(settings.AZURE_SEARCH_KEY_SECRET_NAME)
    if not key:
        raise ValueError("AZURE_SEARCH_KEY secret is not configured.")
    return AzureKeyCredential(key)


@azure_retry
@lru_cache
def get_search_client(index_name: str) -> SearchClient:
    return SearchClient(
        endpoint=f"https://{settings.AZURE_SEARCH_NAME}.search.azure.us",
        index_name=index_name,
        credential=_get_search_credential(),
        transport=_transport,
    )


def _build_blob_client() -> BlobServiceClient:
    if settings.USE_MANAGED_IDENTITY:
        return BlobServiceClient(
            account_url=str(settings.BLOB_ACCOUNT_URL),
            credential=_token_credential,
            transport=_transport,
        )

    if settings.BLOB_CONNECTION_STRING:
        return BlobServiceClient.from_connection_string(
            settings.BLOB_CONNECTION_STRING,
            transport=_transport,
        )

    key = get_secret_value(settings.BLOB_STORAGE_KEY_SECRET_NAME)
    if not key:
        raise ValueError("Blob storage key secret is not configured.")

    account_name = urlparse(str(settings.BLOB_ACCOUNT_URL)).netloc.split(".")[0]
    credential = AzureNamedKeyCredential(name=account_name, key=key)
    return BlobServiceClient(
        account_url=str(settings.BLOB_ACCOUNT_URL),
        credential=credential,
        transport=_transport,
    )


def _build_cosmos_client() -> CosmosClient:
    if settings.USE_MANAGED_IDENTITY:
        return CosmosClient(
            url=str(settings.AZURE_COSMOSDB_ENDPOINT),
            credential=_token_credential,
        )
    if settings.AZURE_COMOSDB_CONNECTION_STRING:
        return CosmosClient.from_connection_string(settings.AZURE_COMOSDB_CONNECTION_STRING)

    raise ValueError("Cosmos DB authentication is not configured.")


blob_service_client = _build_blob_client()
cosmos_client = _build_cosmos_client()
