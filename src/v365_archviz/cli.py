"""Developer CLI for deterministic pipeline operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from v365_archviz.application.build_canonical_scene import BuildCanonicalScene
from v365_archviz.application.build_correspondence import BuildCorrespondenceIndex
from v365_archviz.application.extract_ifc import ExtractIfc
from v365_archviz.application.inspect_model import InspectModel
from v365_archviz.application.plan_cameras import PlanStandardCameras
from v365_archviz.application.plan_design import PlanDesign
from v365_archviz.application.refine_view import DEFAULT_PROMPT, RefineView
from v365_archviz.application.refine_viewset import RefineViewSet
from v365_archviz.application.validate_viewset import ValidateGeneratedViewSet
from v365_archviz.config import Settings
from v365_archviz.domain.design import DesignDNA
from v365_archviz.domain.workflow import GenerationProfile
from v365_archviz.errors import V365Error
from v365_archviz.providers.aps import ApsModelDerivativeClient
from v365_archviz.providers.gemini import GeminiImageRenderer
from v365_archviz.providers.local_rvt import LocalRvtInspector


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v365-archviz")
    subcommands = parser.add_subparsers(dest="command", required=True)

    inspect = subcommands.add_parser("inspect", help="inspect RVT envelope metadata")
    inspect.add_argument("source", type=Path)
    inspect.add_argument("--output", type=Path, help="artifact root directory")

    extract = subcommands.add_parser("extract-ifc", help="translate an RVT to IFC via APS")
    extract.add_argument("source", type=Path)
    extract.add_argument("--output", type=Path, help="artifact root directory")

    canonicalize = subcommands.add_parser(
        "canonicalize-ifc", help="build Canonical Scene and mesh buffers from IFC"
    )
    canonicalize.add_argument("source_rvt", type=Path)
    canonicalize.add_argument("ifc", type=Path)
    canonicalize.add_argument("--output", type=Path, help="artifact root directory")

    design = subcommands.add_parser(
        "plan-design", help="create the deterministic baseline Design DNA"
    )
    design.add_argument("scene", type=Path)
    design.add_argument("--brief", type=Path, required=True)

    design_revision = subcommands.add_parser(
        "design-revision", help="print the deterministic revision for a scene and brief"
    )
    design_revision.add_argument("scene", type=Path)
    design_revision.add_argument("--brief", type=Path, required=True)

    cameras = subcommands.add_parser(
        "plan-cameras", help="create a model-relative standard camera set"
    )
    cameras.add_argument("scene", type=Path)
    cameras.add_argument("--design-dna", type=Path)

    revision = subcommands.add_parser(
        "revision-key", help="print the content revision key for an RVT"
    )
    revision.add_argument("source", type=Path)
    refine = subcommands.add_parser(
        "refine-view", help="refine one complete conditioning pack with Gemini"
    )
    refine.add_argument("render_root", type=Path)
    refine.add_argument("view_id")
    refine.add_argument("--output", type=Path, help="generated artifact root")
    refine.add_argument("--prompt-file", type=Path)
    refine.add_argument("--reference-image", type=Path, action="append", default=[])
    refine.add_argument("--design-dna", type=Path)
    refine_set = subcommands.add_parser(
        "refine-viewset", help="generate one ordered immutable view-set unit"
    )
    refine_set.add_argument("render_root", type=Path)
    refine_set.add_argument("--view-set", type=Path, required=True)
    refine_set.add_argument("--design-dna", type=Path, required=True)
    refine_set.add_argument("--model-revision", required=True)
    refine_set.add_argument("--output", type=Path, required=True)
    refine_set.add_argument("--prompt-file", type=Path)
    refine_set.add_argument("--reference-image", type=Path, action="append", default=[])
    refine_set.add_argument(
        "--profile",
        choices=[profile.value for profile in GenerationProfile],
        default=GenerationProfile.PREVIEW_FAST.value,
    )
    validate = subcommands.add_parser(
        "validate-viewset", help="validate generated artifacts and provenance"
    )
    validate.add_argument("render_root", type=Path)
    validate.add_argument("generated_root", type=Path)
    validate.add_argument("--view-set", type=Path, required=True)
    validate.add_argument("--design-dna", type=Path, required=True)
    validate.add_argument("--output", type=Path)
    correspondence = subcommands.add_parser(
        "build-correspondence", help="build cross-view identity and visibility indexes"
    )
    correspondence.add_argument("scene", type=Path)
    correspondence.add_argument("render_root", type=Path)
    correspondence.add_argument("--view-set", type=Path, required=True)
    return parser


def _inspect(source: Path, output: Path | None) -> int:
    settings = Settings.from_env()
    artifacts = InspectModel().execute(source, output or settings.artifact_dir)
    response = {
        "manifest": str(artifacts.manifest_path),
        "preview": str(artifacts.preview_path) if artifacts.preview_path else None,
        "sha256": artifacts.inspection.sha256,
        "format_version": artifacts.inspection.format_version,
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


def _refinement_prompt(
    design_dna_path: Path | None, prompt_file: Path | None
) -> tuple[DesignDNA | None, str]:
    prompt = prompt_file.read_text(encoding="utf-8") if prompt_file else DEFAULT_PROMPT
    if design_dna_path is None:
        return None, prompt
    design = DesignDNA.model_validate_json(design_dna_path.read_text(encoding="utf-8"))
    language = design.design_language
    environment = design.environment
    palette = design.material_palette
    presentation = design.presentation
    roof_types = sorted({building.roof.roof_type for building in design.buildings})
    solar_policy = (
        "permitted only on buildings explicitly marked true"
        if any(building.roof.solar_panels for building in design.buildings)
        else "prohibited on every building"
    )
    prompt += (
        "\n\nApproved project Design DNA:\n"
        f"- style: {language.style}\n"
        f"- primary material: {language.primary_material}\n"
        f"- secondary material: {language.secondary_material}\n"
        f"- office material: {language.office_material}\n"
        f"- accent: {language.accent or 'none'}\n"
        "- approved color palette: "
        f"primary {palette.primary_hex}, secondary {palette.secondary_hex}, "
        f"glass {palette.glass_hex}, accent {palette.accent_hex}\n"
        f"- time/weather: {environment.time}, {environment.weather}\n"
        f"- white balance: {environment.white_balance_k} K\n"
        f"- landscape: {presentation.landscape_character}\n"
        f"- paving: {presentation.paving_character}\n"
        f"- entourage density: {presentation.entourage_density}\n"
        f"- approved roof instructions: {', '.join(roof_types)}\n"
        f"- solar-panel policy: {solar_policy}"
    )
    return design, prompt


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            return _inspect(args.source, args.output)
        if args.command == "extract-ifc":
            settings = Settings.from_env()
            with ApsModelDerivativeClient(settings) as client:
                ifc_artifacts = ExtractIfc(client).execute(
                    args.source, args.output or settings.artifact_dir
                )
            print(
                json.dumps(
                    {
                        "ifc": str(ifc_artifacts.ifc_path),
                        "manifest": str(ifc_artifacts.manifest_path),
                        "sha256": ifc_artifacts.source_sha256,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "canonicalize-ifc":
            settings = Settings.from_env()
            scene_artifacts = BuildCanonicalScene().execute(
                args.source_rvt,
                args.ifc,
                args.output or settings.artifact_dir,
            )
            print(
                json.dumps(
                    {
                        "scene": str(scene_artifacts.scene_path),
                        "diagnostics": str(scene_artifacts.diagnostics_path),
                        "meshes": str(scene_artifacts.mesh_directory),
                        "element_count": scene_artifacts.element_count,
                        "surface_count": scene_artifacts.surface_count,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "plan-design":
            design = PlanDesign().execute(args.scene, args.brief)
            print(design.model_dump_json(indent=2))
            return 0
        if args.command == "design-revision":
            print(PlanDesign().revision_from_files(args.scene, args.brief))
            return 0
        if args.command == "plan-cameras":
            view_set = PlanStandardCameras().execute(args.scene, args.design_dna)
            print(view_set.model_dump_json(indent=2))
            return 0
        if args.command == "revision-key":
            print(LocalRvtInspector().inspect(args.source).sha256[:16])
            return 0
        if args.command == "refine-view":
            settings = Settings.from_env()
            loaded_design, prompt = _refinement_prompt(
                args.design_dna, args.prompt_file
            )
            with GeminiImageRenderer(settings) as renderer:
                output_directory = args.output
                if output_directory is None:
                    model_revision = (
                        args.render_root.parent.name
                        if loaded_design is not None
                        and args.render_root.name == loaded_design.design_revision
                        else args.render_root.name
                    )
                    design_revision = (
                        loaded_design.design_revision
                        if loaded_design is not None
                        else "unbound-design"
                    )
                    output_directory = (
                        settings.artifact_dir
                        / "generated"
                        / model_revision
                        / design_revision
                    )
                artifacts = RefineView().execute(
                    renderer,
                    args.render_root,
                    args.view_id,
                    output_directory,
                    prompt,
                    tuple(args.reference_image),
                    project_id=(
                        loaded_design.project_id if loaded_design is not None else None
                    ),
                    design_revision=(
                        loaded_design.design_revision
                        if loaded_design is not None
                        else None
                    ),
                )
            print(
                json.dumps(
                    {
                        "image": str(artifacts.image_path),
                        "manifest": str(artifacts.manifest_path),
                        "provider_request_id": artifacts.provider_request_id,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "refine-viewset":
            settings = Settings.from_env()
            _, prompt = _refinement_prompt(args.design_dna, args.prompt_file)
            with GeminiImageRenderer(settings) as renderer:
                viewset_artifacts = RefineViewSet().execute(
                    renderer,
                    args.render_root,
                    args.output,
                    args.view_set,
                    args.design_dna,
                    args.model_revision,
                    prompt,
                    tuple(args.reference_image),
                    GenerationProfile(args.profile),
                )
            print(
                json.dumps(
                    {
                        "request_id": viewset_artifacts.request_id,
                        "view_count": viewset_artifacts.view_count,
                        "manifest": str(viewset_artifacts.manifest_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if args.command == "validate-viewset":
            validation = ValidateGeneratedViewSet().execute(
                args.render_root,
                args.generated_root,
                args.view_set,
                args.design_dna,
                args.output,
            )
            print(
                json.dumps(
                    {
                        "passed": validation.passed,
                        "error_count": validation.error_count,
                        "report": str(validation.report_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if validation.passed else 3
        if args.command == "build-correspondence":
            correspondence_artifacts = BuildCorrespondenceIndex().execute(
                args.scene, args.view_set, args.render_root
            )
            print(
                json.dumps(
                    {
                        "manifest": str(correspondence_artifacts.manifest_path),
                        "visibility_manifests": len(
                            correspondence_artifacts.visibility_paths
                        ),
                        "pair_count": correspondence_artifacts.pair_count,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
    except V365Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
