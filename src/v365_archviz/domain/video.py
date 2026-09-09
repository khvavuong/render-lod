"""Immutable contracts for revision-bound architectural showreels."""

from __future__ import annotations

from pydantic import Field, computed_field, model_validator

from v365_archviz.domain.common import DomainModel


class VideoShot(DomainModel):
    shot_id: str = Field(pattern=r"^shot-\d{2}$")
    view_id: str = Field(pattern=r"^view-\d{2}$")
    source_image_ref: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    negative_prompt: str = Field(min_length=1)
    duration_seconds: int
    aspect_ratio: str = Field(pattern=r"^(16:9|9:16)$")
    resolution: str = Field(pattern=r"^(720p|1080p)$")
    seed: int = Field(ge=0, le=4_294_967_295)

    @model_validator(mode="after")
    def validate_veo_constraints(self) -> VideoShot:
        if self.duration_seconds not in {4, 6, 8}:
            raise ValueError("Veo shot duration must be 4, 6 or 8 seconds")
        if self.resolution == "1080p" and self.duration_seconds != 8:
            raise ValueError("Veo 1080p output requires an 8-second duration")
        return self


class VideoPlan(DomainModel):
    schema_version: str = "1.0.0"
    plan_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    model_revision: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    view_set_id: str = Field(min_length=1)
    provider: str = "gemini-api"
    provider_model: str = Field(min_length=1)
    price_per_second_usd: float = Field(gt=0)
    budget_usd: float = Field(gt=0)
    shots: tuple[VideoShot, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def estimated_cost_usd(self) -> float:
        return round(
            sum(shot.duration_seconds for shot in self.shots) * self.price_per_second_usd,
            4,
        )

    @model_validator(mode="after")
    def validate_plan(self) -> VideoPlan:
        if not self.shots:
            raise ValueError("a video plan must contain at least one shot")
        if len({shot.shot_id for shot in self.shots}) != len(self.shots):
            raise ValueError("shot IDs must be unique")
        if len({shot.view_id for shot in self.shots}) != len(self.shots):
            raise ValueError("view IDs must be unique")
        if self.estimated_cost_usd > self.budget_usd:
            raise ValueError(
                f"estimated cost ${self.estimated_cost_usd:.2f} exceeds "
                f"budget ${self.budget_usd:.2f}"
            )
        return self
