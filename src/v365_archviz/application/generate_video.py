"""Generate Veo shots sequentially with durable resume and a hard spend ceiling."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v365_archviz.application.assemble_video import probe_video
from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.video import VideoPlan, VideoShot
from v365_archviz.errors import InvalidModelError, ProviderError
from v365_archviz.providers.contracts import (
    VideoGenerationInput,
    VideoGenerationProvider,
    VideoOperation,
)


@dataclass(frozen=True, slots=True)
class GeneratedVideoArtifacts:
    output_directory: Path
    manifest_path: Path
    completed_shot_ids: tuple[str, ...]
    cached_shot_ids: tuple[str, ...]
    estimated_new_spend_usd: float


def _cache_key(plan: VideoPlan, shot: VideoShot) -> str:
    digest = hashlib.sha256()
    digest.update(Path(shot.source_image_ref).read_bytes())
    for value in (
        plan.provider_model,
        shot.prompt,
        shot.negative_prompt,
        str(shot.duration_seconds),
        shot.aspect_ratio,
        shot.resolution,
        str(shot.seed),
    ):
        digest.update(b"\0")
        digest.update(value.encode())
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def _write_manifest(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode() + b"\n")


class GenerateVideoShots:
    def execute(
        self,
        provider: VideoGenerationProvider,
        plan_path: Path,
        output_directory: Path,
        *,
        selected_view_ids: tuple[str, ...] = (),
        poll_interval_seconds: float = 10.0,
        timeout_seconds: float = 900.0,
    ) -> GeneratedVideoArtifacts:
        plan = VideoPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        selected = set(selected_view_ids)
        unknown = selected - {shot.view_id for shot in plan.shots}
        if unknown:
            raise InvalidModelError(f"unknown selected video views: {', '.join(sorted(unknown))}")
        shots = tuple(shot for shot in plan.shots if not selected or shot.view_id in selected)
        if not shots:
            raise InvalidModelError("no video shots selected")

        cached: list[str] = []
        pending: list[tuple[VideoShot, str, Path, dict[str, Any] | None]] = []
        for shot in shots:
            key = _cache_key(plan, shot)
            shot_dir = output_directory / shot.shot_id
            manifest_path = shot_dir / "generation_manifest.json"
            manifest = _load_manifest(manifest_path)
            video_path = shot_dir / "raw.mp4"
            if (
                manifest
                and manifest.get("cache_key") == key
                and manifest.get("status") == "completed"
                and video_path.is_file()
                and video_path.stat().st_size > 0
            ):
                cached.append(shot.shot_id)
            else:
                pending.append((shot, key, manifest_path, manifest))

        estimated_spend = round(
            sum(shot.duration_seconds for shot, _, _, _ in pending) * plan.price_per_second_usd,
            4,
        )
        already_spent = round(
            sum(
                float(
                    (
                        _load_manifest(output_directory / shot.shot_id / "generation_manifest.json")
                        or {}
                    ).get("estimated_cost_usd", 0.0)
                )
                for shot in plan.shots
                if (output_directory / shot.shot_id / "raw.mp4").is_file()
            ),
            4,
        )
        if already_spent + estimated_spend > plan.budget_usd + 1e-9:
            raise InvalidModelError(
                f"new generation could reach ${already_spent + estimated_spend:.2f}, "
                f"above plan budget ${plan.budget_usd:.2f}"
            )

        completed: list[str] = []
        for shot, key, manifest_path, previous in pending:
            source = Path(shot.source_image_ref)
            operation: VideoOperation
            if (
                previous
                and previous.get("cache_key") == key
                and previous.get("status") == "running"
                and isinstance(previous.get("operation_name"), str)
            ):
                operation = provider.get(previous["operation_name"])
            else:
                operation = provider.start(
                    VideoGenerationInput(
                        shot_id=shot.shot_id,
                        source_image=source,
                        prompt=shot.prompt,
                        negative_prompt=shot.negative_prompt,
                        duration_seconds=shot.duration_seconds,
                        aspect_ratio=shot.aspect_ratio,
                        resolution=shot.resolution,
                        seed=shot.seed,
                    )
                )
                _write_manifest(
                    manifest_path,
                    {
                        "schema_version": "1.0.0",
                        "plan_id": plan.plan_id,
                        "shot_id": shot.shot_id,
                        "view_id": shot.view_id,
                        "status": "running",
                        "provider": provider.name,
                        "provider_model": plan.provider_model,
                        "operation_name": operation.name,
                        "cache_key": key,
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "duration_seconds": shot.duration_seconds,
                        "resolution": shot.resolution,
                        "seed": shot.seed,
                        "estimated_cost_usd": round(
                            shot.duration_seconds * plan.price_per_second_usd, 4
                        ),
                    },
                )

            started_at = time.monotonic()
            while not operation.done:
                if time.monotonic() - started_at >= timeout_seconds:
                    raise ProviderError(
                        f"Veo operation timed out; resume later with {operation.name}"
                    )
                time.sleep(poll_interval_seconds)
                operation = provider.get(operation.name)
            if operation.error_message:
                failed = _load_manifest(manifest_path) or {}
                failed.update({"status": "failed", "error": operation.error_message})
                _write_manifest(manifest_path, failed)
                raise ProviderError(f"Veo failed {shot.shot_id}: {operation.error_message}")

            content = provider.download(operation)
            video_path = output_directory / shot.shot_id / "raw.mp4"
            atomic_write(video_path, content)
            probe = probe_video(video_path)
            streams = probe.get("streams", [])
            video_streams = [
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "video"
            ]
            if not video_streams:
                raise ProviderError(f"Veo returned no video stream for {shot.shot_id}")
            measured_duration = float(probe.get("format", {}).get("duration", 0.0))
            if (
                not shot.duration_seconds - 0.75
                <= measured_duration
                <= shot.duration_seconds + 0.75
            ):
                raise ProviderError(
                    f"Veo returned unexpected duration {measured_duration:.2f}s for {shot.shot_id}"
                )
            qa_path = output_directory / shot.shot_id / "technical_qa.json"
            _write_manifest(
                qa_path,
                {
                    "schema_version": "1.0.0",
                    "shot_id": shot.shot_id,
                    "passed": True,
                    "expected_duration_seconds": shot.duration_seconds,
                    "measured_duration_seconds": measured_duration,
                    "video_stream": video_streams[0],
                    "audio_will_be_removed_on_assembly": any(
                        isinstance(stream, dict) and stream.get("codec_type") == "audio"
                        for stream in streams
                    ),
                },
            )
            completed_manifest = _load_manifest(manifest_path) or {}
            completed_manifest.update(
                {
                    "status": "completed",
                    "video_ref": str(video_path.resolve()),
                    "video_sha256": hashlib.sha256(content).hexdigest(),
                    "video_size_bytes": len(content),
                    "technical_qa_ref": str(qa_path.resolve()),
                }
            )
            _write_manifest(manifest_path, completed_manifest)
            completed.append(shot.shot_id)

        root_manifest_path = output_directory / "video_generation_manifest.json"
        root_manifest = {
            "schema_version": "1.0.0",
            "plan_id": plan.plan_id,
            "provider": provider.name,
            "provider_model": plan.provider_model,
            "budget_usd": plan.budget_usd,
            "estimated_plan_cost_usd": plan.estimated_cost_usd,
            "estimated_new_spend_usd": estimated_spend,
            "completed_shot_ids": sorted(set(completed + cached)),
            "shots": [
                {
                    "shot_id": shot.shot_id,
                    "view_id": shot.view_id,
                    "manifest": str(
                        (output_directory / shot.shot_id / "generation_manifest.json").resolve()
                    ),
                }
                for shot in plan.shots
                if (output_directory / shot.shot_id / "generation_manifest.json").is_file()
            ],
        }
        _write_manifest(root_manifest_path, root_manifest)
        return GeneratedVideoArtifacts(
            output_directory=output_directory,
            manifest_path=root_manifest_path,
            completed_shot_ids=tuple(completed),
            cached_shot_ids=tuple(cached),
            estimated_new_spend_usd=estimated_spend,
        )
