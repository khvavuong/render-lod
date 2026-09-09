"""Validate, normalize and merge generated shots into one silent showreel."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v365_archviz.artifacts import atomic_write
from v365_archviz.domain.video import VideoPlan
from v365_archviz.errors import ConfigurationError, InvalidModelError, ProviderError


@dataclass(frozen=True, slots=True)
class AssembledVideoArtifacts:
    video_path: Path
    report_path: Path
    duration_seconds: float


def probe_video(path: Path) -> dict[str, Any]:
    executable = shutil.which("ffprobe")
    if executable is None:
        raise ConfigurationError("ffprobe is required to validate generated video")
    result = subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise InvalidModelError(f"ffprobe rejected video {path.name}")
    body = json.loads(result.stdout)
    if not isinstance(body, dict):
        raise InvalidModelError(f"invalid ffprobe response for {path.name}")
    return body


class AssembleVideo:
    def execute(
        self,
        plan_path: Path,
        generated_root: Path,
        output_path: Path,
        *,
        transition_seconds: float = 0.35,
    ) -> AssembledVideoArtifacts:
        plan = VideoPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
        if not 0 <= transition_seconds < min(shot.duration_seconds for shot in plan.shots):
            raise InvalidModelError("transition duration must be shorter than every shot")
        input_paths = tuple(generated_root / shot.shot_id / "raw.mp4" for shot in plan.shots)
        missing = [str(path) for path in input_paths if not path.is_file()]
        if missing:
            raise InvalidModelError(f"missing generated video shots: {', '.join(missing)}")

        probes = [probe_video(path) for path in input_paths]
        for path, probe in zip(input_paths, probes, strict=True):
            streams = probe.get("streams")
            if not isinstance(streams, list) or not any(
                isinstance(stream, dict) and stream.get("codec_type") == "video"
                for stream in streams
            ):
                raise InvalidModelError(f"shot has no video stream: {path}")

        executable = shutil.which("ffmpeg")
        if executable is None:
            raise ConfigurationError("ffmpeg is required to assemble the showreel")
        command = [executable, "-y", "-hide_banner", "-loglevel", "error"]
        for path in input_paths:
            command.extend(["-i", str(path)])

        filters: list[str] = []
        for index in range(len(input_paths)):
            filters.append(
                f"[{index}:v]scale=1280:720:force_original_aspect_ratio=increase,"
                f"crop=1280:720,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
            )
        current = "v0"
        offset = float(plan.shots[0].duration_seconds) - transition_seconds
        for index in range(1, len(input_paths)):
            output = f"x{index}"
            filters.append(
                f"[{current}][v{index}]xfade=transition=fade:duration={transition_seconds:.3f}:"
                f"offset={offset:.3f}[{output}]"
            )
            current = output
            offset += plan.shots[index].duration_seconds - transition_seconds

        output_path.parent.mkdir(parents=True, exist_ok=True)
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                f"[{current}]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "slow",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise ProviderError(f"ffmpeg assembly failed: {result.stderr.strip()}")

        final_probe = probe_video(output_path)
        final_streams = final_probe.get("streams", [])
        audio_count = sum(
            1
            for stream in final_streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        )
        duration = float(final_probe.get("format", {}).get("duration", 0.0))
        if audio_count:
            raise ProviderError("assembled showreel unexpectedly contains audio")
        report_path = output_path.with_suffix(".qa.json")
        report = {
            "schema_version": "1.0.0",
            "plan_id": plan.plan_id,
            "passed": True,
            "shot_count": len(input_paths),
            "transition_seconds": transition_seconds,
            "duration_seconds": duration,
            "width": 1280,
            "height": 720,
            "frame_rate": 24,
            "audio_stream_count": audio_count,
            "source_probes": probes,
            "output_probe": final_probe,
        }
        atomic_write(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2).encode() + b"\n",
        )
        return AssembledVideoArtifacts(
            video_path=output_path,
            report_path=report_path,
            duration_seconds=duration,
        )
