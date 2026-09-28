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
    stability_api_key: str | None = None
    stability_control_strength: float = 0.85
    stability_seed: int = 365100
    image_provider: str = "gemini"
    gemini_conditioning_mode: str = "photoreal_balanced"
    gemini_master_image_model: str | None = None
    gemini_thinking_level: str = "high"
    openai_api_key: str | None = None
    openai_image_model: str = "gpt-image-2.5-sunburst"
    openai_image_quality: str = "high"
    openai_image_size: str = "1536x1024"
    local_worker_enabled: bool = True
    conditioning_backend: str = "docker"
    veo_model: str = "veo-3.1-lite-generate-preview"
    veo_resolution: str = "720p"
    veo_duration_seconds: int = 4
    veo_price_per_second_usd: float = 0.05
    video_budget_usd: float = 1.20
    veo_poll_interval_seconds: float = 10.0
    veo_timeout_seconds: float = 900.0
    auto_appearance_baseline: bool = False
    #: Stamp the brand logo on delivered images and videos. An embedding product
    #: that delivers under its own name turns this off.
    brand_watermark: bool = True
    #: How many generation jobs run at once. Concept batches are independent jobs.
    generation_workers: int = 1

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        return cls(
            environment=os.getenv("V365_ENV", "development"),
            artifact_dir=Path(os.getenv("V365_ARTIFACT_DIR", ".artifacts")),
            log_level=os.getenv("V365_LOG_LEVEL", "INFO"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_image_model=os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image"),
            gemini_store_interactions=_as_bool(
                os.getenv("GEMINI_STORE_INTERACTIONS"), default=False
            ),
            veo_model=os.getenv("VEO_MODEL", "veo-3.1-lite-generate-preview"),
            veo_resolution=os.getenv("VEO_RESOLUTION", "720p"),
            veo_duration_seconds=int(os.getenv("VEO_DURATION_SECONDS", "4")),
            veo_price_per_second_usd=float(os.getenv("VEO_PRICE_PER_SECOND_USD", "0.05")),
            video_budget_usd=float(os.getenv("VIDEO_BUDGET_USD", "1.20")),
            veo_poll_interval_seconds=float(os.getenv("VEO_POLL_INTERVAL_SECONDS", "10")),
            veo_timeout_seconds=float(os.getenv("VEO_TIMEOUT_SECONDS", "900")),
            aps_client_id=os.getenv("APS_CLIENT_ID"),
            aps_client_secret=os.getenv("APS_CLIENT_SECRET"),
            aps_base_url=os.getenv("APS_BASE_URL", "https://developer.api.autodesk.com").rstrip(
                "/"
            ),
            aps_region=os.getenv("APS_REGION", "US"),
            aps_bucket_key=os.getenv("APS_BUCKET_KEY"),
            stability_api_key=os.getenv("STABILITY_API_KEY"),
            stability_control_strength=float(os.getenv("STABILITY_CONTROL_STRENGTH", "0.85")),
            stability_seed=int(os.getenv("STABILITY_SEED", "365100")),
            image_provider=os.getenv("V365_IMAGE_PROVIDER", "gemini"),
            gemini_conditioning_mode=os.getenv("GEMINI_CONDITIONING_MODE", "photoreal_balanced"),
            gemini_master_image_model=os.getenv("GEMINI_MASTER_IMAGE_MODEL", "gemini-3-pro-image")
            or None,
            gemini_thinking_level=os.getenv("GEMINI_THINKING_LEVEL", "high"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_image_model=os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst"),
            openai_image_quality=os.getenv("OPENAI_IMAGE_QUALITY", "high"),
            openai_image_size=os.getenv("OPENAI_IMAGE_SIZE", "1536x1024"),
            local_worker_enabled=_as_bool(os.getenv("V365_ENABLE_LOCAL_WORKER"), default=True),
            conditioning_backend=os.getenv("V365_CONDITIONING_BACKEND", "docker"),
            auto_appearance_baseline=_as_bool(
                os.getenv("V365_AUTO_APPEARANCE_BASELINE"), default=False
            ),
            brand_watermark=_as_bool(os.getenv("V365_BRAND_WATERMARK"), default=True),
            generation_workers=max(1, int(os.getenv("V365_GENERATION_WORKERS", "1"))),
        )

    @property
    def aps_configured(self) -> bool:
        return bool(self.aps_client_id and self.aps_client_secret and self.aps_bucket_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def stability_configured(self) -> bool:
        return bool(self.stability_api_key)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)
