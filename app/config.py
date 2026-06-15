"""Application settings loaded from environment variables.

All secrets come from the environment (.env locally, Azure Key Vault in
production). Nothing is hard-coded here.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Salesforce — OAuth 2.0 client credentials
    sf_client_id: str = ""
    sf_client_secret: str = ""
    sf_instance_url: str = ""
    sf_api_version: str = "62.0"

    # Salesforce — auth flow selection ("username_password" | "jwt" | "auto")
    sf_auth_flow: str = "auto"
    # Username/password flow
    sf_username: str = ""
    sf_password: str = ""
    sf_security_token: str = ""
    sf_domain: str = "login"  # "login" for prod, "test" for sandboxes
    # Connected app JWT flow
    sf_jwt_key_file: str = ""  # path to the PEM private key
    sf_jwt_key: str = ""  # OR the PEM private key contents directly

    # Entra ID — token validation
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_authority: str = ""

    # API settings
    api_env: str = "development"
    allowed_origins: str = "http://localhost:3000"

    # Local-dev auth bypass — lets you run endpoints before Entra/React/SF
    # exist. IGNORED unless api_env == "development".
    auth_disabled: bool = False
    dev_user_email: str = "dev.user@example.org"
    dev_contact_id: str = "003DEV00000000000"
    dev_account_id: str = "001DEV00000000000"  # the fake district
    dev_user_name: str = "Dev User"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
