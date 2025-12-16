from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    AZURE_COMOSDB_CONNECTION_STRING: str = Field(..., env="AZURE_COMOSDB_CONNECTION_STRING")
    AZURE_COSMOSDB_ENDPOINT: str = Field(..., env="AZURE_COSMOSDB_ENDPOINT")
    AZURE_COSMOSDB_NAME: str = Field(..., env="AZURE_COSMOSDB_NAME")

    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str
    AZURE_OPENAI_EMBEDDING_MODEL: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_LLM_DEPLOYMENT: str
    AZURE_OPENAI_LLM_MODEL: str
    AZURE_OPENAI_AUTH_SCOPE: str

    AZURE_AI_SP_CLIENT_ID: str
    AZURE_AI_SP_CLIENT_PASS: str

    AZURE_SEARCH_API_VERSION: str
    AZURE_SEARCH_NAME: str
    AZURE_SEARCH_KEY: str

    BLOB_STORAGE_ACCOUNT_KEY: str
    BLOB_CONNECTION_STRING: str
    BLOB_RESOURCE_ID: str

    CMK_KEY_VAULT_URI: str
    CMK_KEY_NAME: str
    CMK_MANAGED_IDENTITY_RESOURCE_ID: str

    COG_SERVICES_ENDPOINT: str
    COG_SERVICES_KEY: str

    MANAGED_IDENTITY_RESOURCE_ID: str
    RESOURCE_GROUP_NAME: str
    SUBSCRIPTION_ID: str
    TENANT_ID: str
    WORKSPACE_NAME: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
