"""HTTP control-plane entrypoint."""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from v365_archviz import __version__
from v365_archviz.config import Settings

app = FastAPI(
    title="V365 ArchViz Control Plane",
    version=__version__,
    description="Geometry-first multi-view architectural visualization API",
)


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"] = "ok"
    version: str


class CapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_rvt_inspection: bool
    aps_geometry_extraction: bool
    gemini_image_generation: bool


@app.get("/healthz", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(version=__version__)


@app.get("/v1/system/capabilities", response_model=CapabilityResponse, tags=["system"])
def capabilities() -> CapabilityResponse:
    settings = Settings.from_env()
    return CapabilityResponse(
        local_rvt_inspection=True,
        aps_geometry_extraction=settings.aps_configured,
        gemini_image_generation=settings.gemini_configured,
    )

