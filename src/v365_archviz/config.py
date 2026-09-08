"""Environment-backed runtime settings.

Secrets are read on demand and are deliberately excluded from repr and API output.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    artifact_dir: Path
    log_level: str
    gemini_api_key: str | None
    gemini_image_model: str
    gemini_store_interactions: bool
    aps_client_id: str | None
    aps_client_secret: str | None
    aps_base_url: str
    aps_region: str
    aps_bucket_key: str | None

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            environment=os.getenv("V365_ENV", "development"),
            artifact_dir=Path(os.getenv("V365_ARTIFACT_DIR", ".artifacts")),
            log_level=os.getenv("V365_LOG_LEVEL", "INFO"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_image_model=os.getenv(
                "GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"
            ),
            gemini_store_interactions=_as_bool(
                os.getenv("GEMINI_STORE_INTERACTIONS"), default=False
            ),
            aps_client_id=os.getenv("APS_CLIENT_ID"),
            aps_client_secret=os.getenv("APS_CLIENT_SECRET"),
            aps_base_url=os.getenv(
                "APS_BASE_URL", "https://developer.api.autodesk.com"
            ).rstrip("/"),
            aps_region=os.getenv("APS_REGION", "US"),
            aps_bucket_key=os.getenv("APS_BUCKET_KEY"),
        )

    @property
    def aps_configured(self) -> bool:
        return bool(self.aps_client_id and self.aps_client_secret and self.aps_bucket_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)
