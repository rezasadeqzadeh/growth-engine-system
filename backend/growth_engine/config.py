"""Settings, read once from the environment (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


DEV_SECRET = "growth-engine-local-development-secret-not-for-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///./var/growth-engine.db"
    jwt_secret: str = DEV_SECRET
    token_ttl_days: int = 30
    superadmin_phones: str = ""

    # Public base URL of this service: tracked links, handoff pages and
    # media URLs handed to Instagram are built from it.
    public_base_url: str = "http://localhost:8000"
    panel_url: str = "http://localhost:3000"
    storage_dir: Path = Path("./var/storage")

    # OpenCode is the only LLM provider.
    opencode_server_url: str = ""
    opencode_server_username: str = ""
    opencode_server_password: str = ""
    # Model routing: light work (hashtags, classification) goes to the cheap
    # model, captions and reports to the strong one, images to the vision one.
    model_light: str = ""
    model_strong: str = ""
    model_vision: str = ""
    ai_poll_budget_s: int = 600

    sms_webservice_api_key: str = ""
    sms_sender: str = ""

    zarinpal_merchant_id: str = "00000000-0000-0000-0000-000000000000"
    zarinpal_sandbox: bool = True

    ig_app_id: str = ""
    ig_app_secret: str = ""
    ig_redirect_uri: str = ""

    whisper_model: str = "large-v3"
    whisper_device: str = "auto"
    brand_fonts_dir: Path = Path("./var/fonts")

    def check_production(self) -> None:
        """Refuse to serve production with the development secret or no AI server."""
        if self.is_development:
            return
        if self.jwt_secret == DEV_SECRET or len(self.jwt_secret) < 32:
            raise RuntimeError("Set JWT_SECRET to a random value of at least 32 characters")
        if not self.opencode_server_url or not self.model_strong:
            raise RuntimeError("Set OPENCODE_SERVER_URL and MODEL_STRONG")

    @property
    def is_development(self) -> bool:
        return self.environment != "production"

    @property
    def superadmins(self) -> set[str]:
        return {p.strip() for p in self.superadmin_phones.split(",") if p.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
