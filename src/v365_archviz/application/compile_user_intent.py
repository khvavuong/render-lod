"""Compile safe user intent into an immutable, scene-bindable design brief."""

from __future__ import annotations

import re
from dataclasses import dataclass

from v365_archviz.domain.design import (
    DesignBrief,
    DesignLanguage,
    DesignPreferences,
    EnvironmentDesign,
    FacadeArticulation,
    PresentationStrategy,
    SiteDesign,
)
from v365_archviz.domain.render_intent import (
    DESIGN_OPTIONS,
    ContextPresentation,
    IntentWarning,
    LandscapePreset,
    LoadingDockPolicy,
    RealismPreset,
    UserRenderIntent,
)

STYLE_LANGUAGE = {
    "contemporary_industrial": DesignLanguage(
        style="contemporary Vietnamese industrial architecture with refined practical proportions",
        primary_material="light neutral architectural metal cladding",
        secondary_material="dark graphite metal accents",
        office_material="high-performance blue-grey architectural glazing",
        accent="restrained project accent used only at selected entrance and facade bays",
    ),
    "minimal_industrial": DesignLanguage(
        style="minimal refined industrial architecture with disciplined facade rhythm",
        primary_material="light matte profiled metal cladding",
        secondary_material="restrained charcoal metal details",
        office_material="neutral low-reflectance architectural glazing",
        accent="minimal accent restricted to the principal entrance",
    ),
    "corporate_industrial": DesignLanguage(
        style="professional corporate industrial campus with a clear arrival identity",
        primary_material="durable neutral insulated metal panels",
        secondary_material="precise dark metal framing",
        office_material="shaded corporate architectural glazing",
        accent="corporate accent restricted to selected arrival elements",
    ),
    "sustainable_industrial": DesignLanguage(
        style="climate-responsive sustainable industrial campus suitable for Vietnam",
        primary_material="high-albedo neutral metal cladding",
        secondary_material="weather-resistant deep neutral accents",
        office_material="solar-controlled architectural glazing",
        accent="natural restrained accent at climate-responsive elements",
    ),
    "refined_high_tech": DesignLanguage(
        style="restrained high-tech industrial architecture with buildable technical detailing",
        primary_material="precision light-grey metal envelope",
        secondary_material="graphite technical metalwork",
        office_material="high-performance cool-neutral glazing",
        accent="precise accent at selected technical bays only",
    ),
}

DECOR_ARTICULATION = {
    "minimal": FacadeArticulation(
        plinth_height_m=0.75,
        parapet_band_height_m=0.45,
        office_glazing_ratio=0.36,
        feature_frame_depth_m=0.25,
        entrance_canopy_projection_m=1.4,
        vertical_fin_count=0,
        accent_bay_interval=14,
    ),
    "subtle": FacadeArticulation(
        plinth_height_m=0.8,
        parapet_band_height_m=0.55,
        office_glazing_ratio=0.42,
        feature_frame_depth_m=0.4,
        entrance_canopy_projection_m=1.8,
        vertical_fin_count=2,
        accent_bay_interval=12,
    ),
    "balanced": FacadeArticulation(
        plinth_height_m=0.9,
        parapet_band_height_m=0.65,
        office_glazing_ratio=0.48,
        feature_frame_depth_m=0.75,
        entrance_canopy_projection_m=2.4,
        vertical_fin_count=3,
        accent_bay_interval=10,
    ),
    "expressive": FacadeArticulation(
        plinth_height_m=1.0,
        parapet_band_height_m=0.8,
        office_glazing_ratio=0.58,
        feature_frame_depth_m=1.1,
        entrance_canopy_projection_m=3.0,
        vertical_fin_count=6,
        accent_bay_interval=7,
    ),
}

LANDSCAPE_LANGUAGE = {
    LandscapePreset.TROPICAL_RESTRAINED: "restrained climate-appropriate tropical planting",
    LandscapePreset.CORPORATE_LINEAR: "ordered linear corporate landscape planting",
    LandscapePreset.LOW_MAINTENANCE: "low-maintenance climate-resilient industrial planting",
}

REALISM_LANGUAGE = {
    RealismPreset.DOCUMENTARY_ARCHITECTURAL_PHOTO: (
        "documentary architectural photography, natural exposure, plausible material wear, "
        "physical contact shadows and restrained lens character"
    ),
    RealismPreset.PREMIUM_BID_PHOTO: (
        "premium bid-quality architectural photography, controlled highlights, natural material "
        "micro-variation and polished but credible site presentation"
    ),
}

_LOCKED_OVERRIDE = re.compile(
    r"(?:x[oó]a|b[oỏ]|th[eê]m|[đd][oổ]i|thay(?:\s+[đd][oổ]i)?|di\s+chuy[eể]n|n[aâ]ng|t[aă]ng|"
    r"remove|delete|add|change|replace|move|raise|enlarge)"
    r".{0,80}(?:m[aá]i|roof|[đd]ường|road|c[oổ]ng|gate|h[aà]ng\s+r[aà]o|fence|"
    r"kh[oố]i|massing|building|camera)",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"(?:kh[oô]ng|do\s+not|don't|must\s+not|never)", re.IGNORECASE)
_INSTRUCTION_OVERRIDE = re.compile(
    r"(?:ignore|disregard|override|b[oỏ]\s+qua).{0,60}"
    r"(?:instruction|prompt|constraint|rule|ch[iỉ]\s+d[aẫ]n|y[eê]u\s+c[aầ]u|quy\s+t[aắ]c)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class CompiledUserIntent:
    brief: DesignBrief
    normalized_intent: UserRenderIntent
    warnings: tuple[IntentWarning, ...]
    catalog_version: str


class CompileUserRenderIntent:
    """Resolve public enums server-side and strip attempts to override locked geometry."""

    def execute(self, project_id: str, intent: UserRenderIntent) -> CompiledUserIntent:
        normalized_text, warnings = self._normalize_free_text(intent.free_text)
        normalized = intent.model_copy(update={"free_text": normalized_text})
        hour, minute = (int(value) for value in normalized.time.split(":"))
        daylight_hour = hour + minute / 60
        environment = self._environment(normalized.time, daylight_hour)
        dock_count = (
            0
            if normalized.loading_dock_policy is LoadingDockPolicy.PRESERVE_EXISTING
            else normalized.loading_dock_count
        )
        if normalized.loading_dock_policy is LoadingDockPolicy.SUGGEST_IF_MISSING and dock_count:
            warnings += (
                IntentWarning(
                    code="loading_dock_requires_design_review",
                    field="loading_dock_count",
                    message=(
                        "Cửa xuất nhập hàng chỉ được đề xuất trên một facade nhà xưởng đủ điều "
                        "kiện và phải qua geometry review."
                    ),
                ),
            )
        context_opacity = (
            0.22
            if normalized.context_presentation is ContextPresentation.NEUTRAL_INDUSTRIAL_MASSING
            else 0.28
        )
        creative_direction = " | ".join(
            part
            for part in (
                f"creative budget={normalized.creative_budget.value}",
                f"realism={REALISM_LANGUAGE[normalized.realism_preset]}",
                f"loading dock policy={normalized.loading_dock_policy.value}",
                f"context presentation={normalized.context_presentation.value}",
                normalized_text,
            )
            if part
        )
        brief = DesignBrief(
            project_id=project_id,
            design_language=STYLE_LANGUAGE[normalized.style_preset.value],
            environment=environment,
            material_palette=normalized.material_palette,
            facade_articulation=DECOR_ARTICULATION[normalized.decor_level.value],
            presentation=PresentationStrategy(
                landscape_character=LANDSCAPE_LANGUAGE[normalized.landscape_preset],
                paving_character=(
                    "credible light-grey industrial concrete with drainage, joints and subtle wear"
                ),
                entourage_density=normalized.entourage_density.value,
            ),
            site_design=SiteDesign(
                preserve_transport_geometry=True,
                preserve_landscape_boundaries=True,
                context_render_mode="translucent_massing",
                context_opacity=context_opacity,
                surrounding_context_mode="authored_only",
                surrounding_context_count=0,
                surrounding_landscape_buffer=False,
            ),
            design_preferences=DesignPreferences(
                style_preset=normalized.style_preset,
                decor_level=normalized.decor_level,
                requested_office_storeys=normalized.office_facade_rhythm,
                creative_prompt=creative_direction,
            ),
            focus_building_ids=(),
            context_building_ids=(),
            panel_module_m=1.2,
            loading_docks_per_main_facade=dock_count,
            add_office_entrances=True,
            roof_type="model-derived continuous profiled-metal industrial roof",
            roof_slope_deg=7.0,
            roof_eave_overhang_m=0.75,
            roof_ridge_orientation="long_axis",
            roof_grouping_mode="continuous_rows",
            roof_group_gap_tolerance_m=10.0,
            solar_panels=False,
            grammar_version=f"industrial-grammar-v4-intent-{DESIGN_OPTIONS.catalog_version}",
            asset_library_version="baseline-assets-v2",
        )
        return CompiledUserIntent(
            brief=brief,
            normalized_intent=normalized,
            warnings=warnings,
            catalog_version=DESIGN_OPTIONS.catalog_version,
        )

    @staticmethod
    def _environment(time: str, daylight_hour: float) -> EnvironmentDesign:
        if daylight_hour < 7.5:
            weather, azimuth, elevation, white_balance = "soft early morning", 95.0, 18.0, 5000
        elif daylight_hour < 11.0:
            weather, azimuth, elevation, white_balance = "clear bright morning", 132.0, 48.0, 5600
        elif daylight_hour < 14.0:
            weather, azimuth, elevation, white_balance = "bright tropical midday", 180.0, 68.0, 5800
        elif daylight_hour < 17.5:
            weather, azimuth, elevation, white_balance = "clear late afternoon", 235.0, 38.0, 5400
        else:
            weather, azimuth, elevation, white_balance = "soft warm dusk", 265.0, 12.0, 4300
        return EnvironmentDesign(
            time=time,
            weather=weather,
            sun_azimuth_deg=azimuth,
            sun_elevation_deg=elevation,
            white_balance_k=white_balance,
        )

    @staticmethod
    def _normalize_free_text(
        value: str | None,
    ) -> tuple[str | None, tuple[IntentWarning, ...]]:
        if not value or not value.strip():
            return None, ()
        clean = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
        clean = re.sub(r"\s+", " ", clean).strip()
        accepted: list[str] = []
        warnings: list[IntentWarning] = []
        for sentence in filter(None, re.split(r"(?<=[.!?;])\s+", clean)):
            if _INSTRUCTION_OVERRIDE.search(sentence):
                warnings.append(
                    IntentWarning(
                        code="instruction_override_ignored",
                        field="free_text",
                        message="Một chỉ dẫn cố ghi đè luật hệ thống đã bị bỏ qua.",
                        ignored_text=sentence,
                    )
                )
                continue
            match = _LOCKED_OVERRIDE.search(sentence)
            if match and not _NEGATION.search(sentence[: match.end()]):
                warnings.append(
                    IntentWarning(
                        code="locked_geometry_override_ignored",
                        field="free_text",
                        message=(
                            "Một yêu cầu thay đổi hình học khóa từ model đã bị bỏ qua; các ưu tiên "
                            "thẩm mỹ hợp lệ vẫn được giữ."
                        ),
                        ignored_text=sentence,
                    )
                )
            else:
                accepted.append(sentence)
        return " ".join(accepted) or None, tuple(warnings)
