.PHONY: install test lint typecheck inspect extract-ifc api

install:
	python3 -m pip install -e ".[dev]"

test:
	python3 -m pytest

lint:
	python3 -m ruff check .

typecheck:
	python3 -m mypy

inspect:
	python3 -m v365_archviz inspect resource/model_lod100_sample.rvt

extract-ifc:
	python3 -m v365_archviz extract-ifc resource/model_lod100_sample.rvt

canonicalize:
	python3 -m v365_archviz canonicalize-ifc resource/model_lod100_sample.rvt \
		.artifacts/extractions/480b5e6346f2877b/model_lod100_sample.ifc

renderer-image:
	docker build -f Dockerfile.renderer -t v365-archviz-renderer:foundation .

render:
	python3 -c "from pathlib import Path; from v365_archviz.application.plan_cameras import PlanStandardCameras; PlanStandardCameras().execute(Path('.artifacts/scenes/480b5e6346f2877b/canonical_scene.json'))"
	docker run --rm -v "$(CURDIR):/workspace" v365-archviz-renderer:foundation \
		--scene /workspace/.artifacts/scenes/480b5e6346f2877b/canonical_scene.json \
		--view-set /workspace/.artifacts/scenes/480b5e6346f2877b/view_set.json \
		--output /workspace/.artifacts/renders/480b5e6346f2877b

extract-ifc:
	python3 -m v365_archviz extract-ifc resource/model_lod100_sample.rvt

api:
	python3 -m uvicorn v365_archviz.api:app --reload
