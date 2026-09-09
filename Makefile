PYTHON ?= .venv/bin/python
MODEL ?=
BRIEF ?=
REFERENCES ?=
VIEW ?= view-01
ARTIFACT_DIR ?= .artifacts

MODEL_NAME = $(basename $(notdir $(MODEL)))
REVISION = $(shell if test -n "$(MODEL)"; then $(PYTHON) -m v365_archviz revision-key "$(MODEL)" 2>/dev/null; fi)
IFC ?= $(ARTIFACT_DIR)/extractions/$(REVISION)/$(MODEL_NAME).ifc
SCENE_DIR ?= $(ARTIFACT_DIR)/scenes/$(REVISION)
SCENE ?= $(SCENE_DIR)/canonical_scene.json
DESIGN_REVISION ?= $(shell if test -n "$(BRIEF)" -a -f "$(SCENE)"; then \
	$(PYTHON) -m v365_archviz design-revision "$(SCENE)" --brief "$(BRIEF)" 2>/dev/null; fi)
DESIGN_DIR ?= $(SCENE_DIR)/designs/$(DESIGN_REVISION)
DESIGN_DNA ?= $(DESIGN_DIR)/design_dna.json
VIEW_SET ?= $(DESIGN_DIR)/view_set.json
RENDER_DIR ?= $(ARTIFACT_DIR)/renders/$(REVISION)/$(DESIGN_REVISION)
GENERATED_DIR ?= $(ARTIFACT_DIR)/generated/$(REVISION)/$(DESIGN_REVISION)
VIEWS ?= view-01 view-02 view-03 view-04 view-05 view-06
PROFILE ?= preview_fast
VIDEO_PLAN ?= $(shell find "$(ARTIFACT_DIR)/videos/$(REVISION)/$(DESIGN_REVISION)" \
	-mindepth 2 -maxdepth 2 -name video_plan.json -print 2>/dev/null | sort | tail -1)
VIDEO_ROOT ?= $(dir $(VIDEO_PLAN))
VIDEO_VIEWS ?=
VIDEO_VIEW_ARGS = $(foreach video_view,$(VIDEO_VIEWS),--view "$(video_view)")
REFERENCE_ARGS = $(foreach reference,$(REFERENCES),--reference-image "$(reference)")

.PHONY: install test lint typecheck require-model require-brief require-design inspect extract-ifc \
	canonicalize plan-design plan-cameras renderer-image render refine-view refine-viewset \
	build-correspondence validate-viewset evaluate-consistency plan-repairs compose-board api \
	plan-video generate-video-shots assemble-video

install:
	$(PYTHON) -m pip install -e ".[dev]"

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

require-model:
	@test -n "$(MODEL)" || { echo "MODEL is required, e.g. MODEL=path/to/model.rvt"; exit 2; }

require-brief:
	@test -n "$(BRIEF)" || { echo "BRIEF is required, e.g. BRIEF=path/to/design_brief.json"; exit 2; }

require-design:
	@test -n "$(DESIGN_REVISION)" || { \
		echo "BRIEF or DESIGN_REVISION is required to resolve an immutable design"; exit 2; \
	}

inspect: require-model
	$(PYTHON) -m v365_archviz inspect "$(MODEL)" --output "$(ARTIFACT_DIR)"

extract-ifc: require-model
	$(PYTHON) -m v365_archviz extract-ifc "$(MODEL)" --output "$(ARTIFACT_DIR)"

canonicalize: require-model
	$(PYTHON) -m v365_archviz canonicalize-ifc "$(MODEL)" "$(IFC)" \
		--output "$(ARTIFACT_DIR)"

plan-design: require-model require-brief
	$(PYTHON) -m v365_archviz plan-design "$(SCENE)" --brief "$(BRIEF)"

plan-cameras: require-model require-design
	$(PYTHON) -m v365_archviz plan-cameras "$(SCENE)" --design-dna "$(DESIGN_DNA)"

renderer-image:
	docker build -f Dockerfile.renderer -t v365-archviz-renderer:foundation .

render: require-model require-brief renderer-image
	$(PYTHON) -m v365_archviz plan-design "$(SCENE)" --brief "$(BRIEF)" >/dev/null
	$(PYTHON) -m v365_archviz plan-cameras "$(SCENE)" \
		--design-dna "$(DESIGN_DNA)" >/dev/null
	docker run --rm --user "$$(id -u):$$(id -g)" -e HOME=/tmp \
		-v "$(CURDIR):/workspace" v365-archviz-renderer:foundation \
		--scene "/workspace/$(SCENE)" \
		--design-dna "/workspace/$(DESIGN_DNA)" \
		--view-set "/workspace/$(VIEW_SET)" \
		--output "/workspace/$(RENDER_DIR)"
	$(PYTHON) -m v365_archviz build-correspondence "$(SCENE)" "$(RENDER_DIR)" \
		--view-set "$(VIEW_SET)"

refine-view: require-model require-design
	$(PYTHON) -m v365_archviz refine-view "$(RENDER_DIR)" "$(VIEW)" \
		--design-dna "$(DESIGN_DNA)" \
		$(REFERENCE_ARGS)

refine-viewset: require-model require-design
	$(PYTHON) -m v365_archviz refine-viewset "$(RENDER_DIR)" \
		--view-set "$(VIEW_SET)" \
		--design-dna "$(DESIGN_DNA)" \
		--model-revision "$(REVISION)" \
		--output "$(GENERATED_DIR)" \
		--profile "$(PROFILE)" \
		$(REFERENCE_ARGS)

build-correspondence: require-model require-design
	$(PYTHON) -m v365_archviz build-correspondence "$(SCENE)" "$(RENDER_DIR)" \
		--view-set "$(VIEW_SET)"

validate-viewset: require-model require-design
	$(PYTHON) -m v365_archviz validate-viewset "$(RENDER_DIR)" "$(GENERATED_DIR)" \
		--view-set "$(VIEW_SET)" --design-dna "$(DESIGN_DNA)"

evaluate-consistency: require-model require-design
	$(PYTHON) -m v365_archviz validate-viewset "$(RENDER_DIR)" "$(GENERATED_DIR)" \
		--view-set "$(VIEW_SET)" --design-dna "$(DESIGN_DNA)" --report-only
	$(PYTHON) -m v365_archviz evaluate-consistency \
		"$(GENERATED_DIR)/technical_qa.json" --model-revision "$(REVISION)" \
		--view-set "$(VIEW_SET)"

plan-repairs: evaluate-consistency
	$(PYTHON) -m v365_archviz plan-repairs \
		"$(GENERATED_DIR)/consistency_report.json"

compose-board: require-model require-design
	$(PYTHON) scripts/compose_viewset_board.py "$(GENERATED_DIR)" \
		"$(GENERATED_DIR)/viewset_board.jpg"

plan-video: require-model require-design
	$(PYTHON) -m v365_archviz plan-video "$(GENERATED_DIR)" \
		--view-set "$(VIEW_SET)" --output "$(ARTIFACT_DIR)/videos"

generate-video-shots: require-model require-design
	@test -n "$(VIDEO_PLAN)" || { echo "VIDEO_PLAN is required; run make plan-video first"; exit 2; }
	$(PYTHON) -m v365_archviz generate-video-shots "$(VIDEO_PLAN)" \
		--output "$(VIDEO_ROOT)" $(VIDEO_VIEW_ARGS)

assemble-video: require-model require-design
	@test -n "$(VIDEO_PLAN)" || { echo "VIDEO_PLAN is required; run make plan-video first"; exit 2; }
	$(PYTHON) -m v365_archviz assemble-video "$(VIDEO_PLAN)" \
		--generated-root "$(VIDEO_ROOT)" --output "$(VIDEO_ROOT)/showreel.mp4"

api:
	$(PYTHON) -m uvicorn v365_archviz.api:app --reload
