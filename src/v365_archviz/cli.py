"""Developer CLI for deterministic pipeline operations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from v365_archviz.application.build_canonical_scene import BuildCanonicalScene
from v365_archviz.application.extract_ifc import ExtractIfc
from v365_archviz.application.inspect_model import InspectModel
from v365_archviz.config import Settings
from v365_archviz.errors import V365Error
from v365_archviz.providers.aps import ApsModelDerivativeClient


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
    except V365Error as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
