import logging
from functools import lru_cache
from typing import Optional

from azure.identity import (
    DefaultAzureCredential,
    ManagedIdentityCredential,
    get_bearer_token_provider,
)
from azure.keyvault.secrets import SecretClient
from azure.core.credentials import TokenCredential

from .config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_token_credential() -> TokenCredential:
    """
    Returns a TokenCredential backed by Managed Identity whenever possible.
    Falls back to DefaultAzureCredential for local development environments.
    """
    settings = get_settings()
    if settings.USE_MANAGED_IDENTITY:
        if not settings.MANAGED_IDENTITY_RESOURCE_ID:
            raise ValueError("Managed identity resource id is required when USE_MANAGED_IDENTITY=true")
        logger.info("Using managed identity %s for Azure authentication", settings.MANAGED_IDENTITY_RESOURCE_ID)
        return ManagedIdentityCredential(resource_id=settings.MANAGED_IDENTITY_RESOURCE_ID)

    logger.warning("Falling back to DefaultAzureCredential (USE_MANAGED_IDENTITY disabled)")
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


@lru_cache
def get_secret_client() -> SecretClient:
    settings = get_settings()
    credential = get_token_credential()
    return SecretClient(vault_url=str(settings.KEY_VAULT_URI), credential=credential)


def get_secret_value(secret_name: Optional[str]) -> Optional[str]:
    """
    Fetch a secret from Azure Key Vault using managed identity.
    """
    if not secret_name:
        return None
    secret = get_secret_client().get_secret(secret_name)
    return secret.value


def get_openai_token_provider():
    """
    Helper to build a callable that LangChain can use to retrieve Azure AD tokens
    for Azure OpenAI requests.
    """
    settings = get_settings()
    credential = get_token_credential()
    return get_bearer_token_provider(credential, settings.AZURE_OPENAI_AUTH_SCOPE)
