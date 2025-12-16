import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.storage.blob import BlobServiceClient
from azure.cosmos import CosmosClient

from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

from .config import get_settings
from .utils.backoff_utils import azure_retry

logger = logging.getLogger(__name__)
settings = get_settings()

# LLM client
llm = AzureChatOpenAI(
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    azure_deployment=settings.AZURE_OPENAI_LLM_DEPLOYMENT,
    api_key=settings.AZURE_OPENAI_API_KEY,
    api_version=settings.AZURE_OPENAI_API_VERSION,
    temperature=0.1,
)

# Embeddings client
embeddings = AzureOpenAIEmbeddings(
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    azure_deployment=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    api_key=settings.AZURE_OPENAI_API_KEY,
    api_version=settings.AZURE_OPENAI_API_VERSION,
)


@azure_retry
def get_search_client(index_name: str) -> SearchClient:
    return SearchClient(
        endpoint=f"https://{settings.AZURE_SEARCH_NAME}.search.windows.net",
        index_name=index_name,
        credential=AzureKeyCredential(settings.AZURE_SEARCH_KEY),
    )


blob_service_client = BlobServiceClient.from_connection_string(settings.BLOB_CONNECTION_STRING)
cosmos_client = CosmosClient.from_connection_string(settings.AZURE_COMOSDB_CONNECTION_STRING)
