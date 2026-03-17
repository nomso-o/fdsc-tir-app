from functools import lru_cache
from typing import Optional

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Centralised application configuration pulled from environment variables (.env) and
    validated aggressively so that we fail fast when required Azure configuration is missing.
    """

    # Cosmos DB / chat history
    AZURE_COMOSDB_CONNECTION_STRING: Optional[str] = Field(
        default=None, env="AZURE_COMOSDB_CONNECTION_STRING"
    )
    AZURE_COSMOSDB_ENDPOINT: AnyHttpUrl = Field(..., env="AZURE_COSMOSDB_ENDPOINT")
    AZURE_COSMOSDB_NAME: str = Field(..., env="AZURE_COSMOSDB_NAME")

    # Azure OpenAI
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str
    AZURE_OPENAI_EMBEDDING_MODEL: str
    AZURE_OPENAI_ENDPOINT: AnyHttpUrl
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_LLM_DEPLOYMENT: str
    AZURE_OPENAI_LLM_MODEL: str
    AZURE_OPENAI_AUTH_SCOPE: str = Field(
        default="https://cognitiveservices.azure.com/.default",
        description="OAuth scope used for Azure AD token requests",
    )

    # Legacy SP (still required by some pipelines)
    AZURE_AI_SP_CLIENT_ID: Optional[str] = None
    AZURE_AI_SP_CLIENT_PASS: Optional[str] = None

    # Azure Cognitive Search
    AZURE_SEARCH_API_VERSION: str
    AZURE_SEARCH_NAME: str
    AZURE_SEARCH_KEY_SECRET_NAME: Optional[str] = Field(
        default=None, env="AZURE_SEARCH_KEY_SECRET_NAME"
    )

    # Blob storage (datasets + exports)
    BLOB_ACCOUNT_URL: AnyHttpUrl
    BLOB_CONNECTION_STRING: Optional[str] = None
    BLOB_STORAGE_KEY_SECRET_NAME: Optional[str] = Field(
        default=None, env="BLOB_STORAGE_KEY_SECRET_NAME"
    )
    BLOB_RESOURCE_ID: Optional[str] = None

    # Key Vault / CMK / Managed identity metadata
    KEY_VAULT_URI: AnyHttpUrl
    CMK_KEY_VAULT_URI: Optional[AnyHttpUrl] = None
    CMK_KEY_NAME: Optional[str] = None
    CMK_MANAGED_IDENTITY_RESOURCE_ID: Optional[str] = None

    # Other service endpoints
    COG_SERVICES_ENDPOINT: Optional[AnyHttpUrl] = None
    COG_SERVICES_KEY_SECRET_NAME: Optional[str] = Field(
        default=None, env="COG_SERVICES_KEY_SECRET_NAME"
    )

    MANAGED_IDENTITY_RESOURCE_ID: Optional[str] = None
    USE_MANAGED_IDENTITY: bool = Field(default=True, env="USE_MANAGED_IDENTITY")

    RESOURCE_GROUP_NAME: str
    SUBSCRIPTION_ID: str
    TENANT_ID: str
    WORKSPACE_NAME: str

    # HTTP client configuration
    AZURE_HTTP_POOL_MAX: int = Field(default=32, ge=1, le=1024)

    # API rate limiting defaults
    RATE_LIMIT_REQUESTS: int = Field(default=60, ge=1)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @field_validator("AZURE_OPENAI_AUTH_SCOPE")
    @classmethod
    def _ensure_scope_suffix(cls, value: str) -> str:
        if value and not value.endswith("/.default"):
            raise ValueError("Azure OpenAI auth scope must end with '/.default'")
        return value

    @field_validator("AZURE_COMOSDB_CONNECTION_STRING")
    @classmethod
    def _validate_cosmos_connection_string(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if "AccountEndpoint=" not in value or "AccountKey=" not in value:
            raise ValueError("Invalid Cosmos DB connection string.")
        return value

    @field_validator("BLOB_CONNECTION_STRING")
    @classmethod
    def _validate_blob_connection_string(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if "AccountName=" not in value or "AccountKey=" not in value:
            raise ValueError("Invalid Blob Storage connection string.")
        return value

    @model_validator(mode="after")
    def _ensure_identity_or_secret_paths(self) -> "Settings":
        """
        Validate that every Azure client has at least one supported auth path.
        """
        missing: list[str] = []
        if self.USE_MANAGED_IDENTITY and not self.MANAGED_IDENTITY_RESOURCE_ID:
            missing.append("MANAGED_IDENTITY_RESOURCE_ID when USE_MANAGED_IDENTITY=true")

        if not self.USE_MANAGED_IDENTITY:
            # Fallback path requires either connection strings or Key Vault secrets.
            if not (self.AZURE_COMOSDB_CONNECTION_STRING and self.BLOB_CONNECTION_STRING):
                missing.append("Connection strings for Cosmos + Blob when not using managed identity")
        if missing:
            raise ValueError("; ".join(missing))
        return self

    def validate_critical(self) -> None:
        """
        Fail loudly when a required high-signal config is missing.
        """
        critical_fields = [
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_LLM_DEPLOYMENT",
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            "AZURE_COSMOSDB_NAME",
            "AZURE_SEARCH_NAME",
            "RESOURCE_GROUP_NAME",
            "SUBSCRIPTION_ID",
            "WORKSPACE_NAME",
            "KEY_VAULT_URI",
            "BLOB_ACCOUNT_URL",
        ]
        missing = [name for name in critical_fields if not getattr(self, name, None)]
        if missing:
            raise ValueError(f"Missing critical configuration values: {', '.join(missing)}")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_critical()
    return settings
