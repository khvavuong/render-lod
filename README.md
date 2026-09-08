# V365 ArchViz

Geometry-first pipeline tạo bộ ảnh diễn họa đa góc nhìn nhất quán từ Revit LOD100.

## Trạng thái

Vertical slice đã chạy end-to-end trên model kiểm nghiệm. Runtime không gắn với tên file,
SHA, project hay visual reference cụ thể:

- domain contracts cho Canonical Scene, Design DNA và View Set;
- APS signed-S3 upload và Model Derivative RVT 2026 → IFC;
- IfcOpenShell canonicalizer tạo canonical scene và NPZ mesh buffers;
- semantic classification baseline cho shed, office, yard và utility;
- Design DNA R01 cùng industrial grammar v1 deterministic;
- một Blender scene dùng chung, bốn camera cố định;
- RGB, clay, depth PNG/EXR, normal EXR, instance ID, semantic và edge passes;
- Gemini Flash refinement có `store=false`, validation ảnh và generation manifest;
- RVT 2026 envelope inspector, SHA-256 version pinning và preview extraction;
- content-addressed artifact manifest;
- FastAPI control-plane skeleton, CLI, containers không chạy bằng root, JSON Schema,
  unit tests và CI quality gates.

Ảnh Blender là geometry-authoritative. Ảnh Gemini hiện là
`MARKETING_GENERATIVE`: phải qua QA/human review vì provider vẫn có thể thay đổi hard geometry.

## Thiết lập

Yêu cầu Python 3.10+.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Không commit `.env`. Các API response và manifest không bao giờ chứa credentials hoặc
đường dẫn máy của tác giả RVT.

## Chạy pipeline cho một model

Mọi target nhận model và project brief từ tham số. `REVISION` và đường dẫn artifact được
tính từ SHA-256 của model, không cần sửa Makefile khi đổi dự án.

```bash
make inspect MODEL=/path/to/project.rvt
```

Sau khi cấu hình APS credentials:

```bash
make extract-ifc MODEL=/path/to/project.rvt
make canonicalize MODEL=/path/to/project.rvt
```

Tạo một brief theo [schema](schemas/design_brief.schema.json), có thể bắt đầu từ
[file ví dụ](examples/design_brief.json), rồi lập Design DNA và render:

Brief hỗ trợ facade grammar có tham số gồm palette màu, plinth/parapet band, tỷ lệ kính,
feature frame, canopy, vertical fins và presentation strategy. Các tham số này được compile
theo từng surface của model; renderer không chứa preset dành riêng cho một dự án.

```bash
make plan-design MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make render MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
```

Ảnh tham khảo là input tùy chọn, chỉ hướng dẫn visual quality/style và không được dùng làm
project geometry hoặc grammar rule:

```bash
make refine-view \
  MODEL=/path/to/project.rvt \
  VIEW=view-01 \
  REFERENCES="/path/to/reference-a.jpg /path/to/reference-b.png"

# Hoặc refine toàn bộ standard view-set, kiểm tra và tạo contact sheet
make refine-viewset \
  MODEL=/path/to/project.rvt \
  REFERENCES="/path/to/reference-a.jpg /path/to/reference-b.png"
make validate-viewset MODEL=/path/to/project.rvt
make compose-board MODEL=/path/to/project.rvt
```

Artifacts được content-address theo SHA của RVT:

```text
.artifacts/
├── inspections/<revision>/
├── extractions/<revision>/
├── scenes/<revision>/
│   ├── canonical_scene.json
│   ├── design_dna.json
│   ├── view_set.json
│   └── meshes/
├── renders/<revision>/<view-id>/
│   ├── base_rgb.png
│   ├── depth.png
│   ├── depth.exr
│   ├── normal.exr
│   ├── instance_id.png
│   ├── semantic.png
│   ├── edges.png
│   └── camera.json
└── generated/<model-revision>/<design-revision>/
    ├── technical_qa.json
    ├── viewset_board.jpg
    └── <view-id>/
        ├── refined.jpg
        └── generation_manifest.json
```

Đổi file RVT sẽ đổi SHA và tạo revision artifact mới. Chạy lại cùng file là idempotent.
`validate-viewset` chỉ xác nhận tính toàn vẹn và provenance của artifact. Ảnh generative vẫn
phải qua human review so với base RGB, depth, edges và brief trước khi được chấp thuận về hình học.

## API

```bash
uvicorn v365_archviz.api:app --reload
```

Các endpoint foundation:

- `GET /healthz`
- `GET /v1/system/capabilities`
- OpenAPI UI: `/docs`

## Quality gates

```bash
pytest
ruff check .
mypy
python scripts/export_schemas.py --check
```

JSON Schemas được sinh từ Pydantic contracts:

```bash
python scripts/export_schemas.py
```

## Cấu trúc

```text
src/v365_archviz/
├── application/       # use cases, không phụ thuộc transport
├── domain/            # immutable validated contracts
├── providers/         # APS/Gemini/local adapter boundaries
├── api.py             # HTTP control plane
├── cli.py             # developer/worker entrypoint
├── config.py          # environment-backed settings
└── errors.py          # typed boundary-safe failures
```

Tài liệu:

- [Requirements](resource/V365_LOD100_MultiView_ArchViz_REQUIREMENTS.md)
- [Feasibility report](resource/V365_LOD100_MultiView_ArchViz_FEASIBILITY_REPORT.md)

## Nguyên tắc bất biến

Mọi thứ phải giống nhau giữa các góc nhìn phải tồn tại dưới dạng 3D/design entity
deterministic bên ngoài image generator. Gemini chỉ là provider refinement, không phải
geometry source of truth.
