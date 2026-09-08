# V365 ArchViz

Geometry-first pipeline tạo bộ ảnh diễn họa đa góc nhìn nhất quán từ Revit LOD100.

## Trạng thái

Vertical slice đã chạy end-to-end trên model kiểm nghiệm. Runtime không gắn với tên file,
SHA, project hay visual reference cụ thể:

- domain contracts cho Canonical Scene, Design DNA và View Set;
- APS signed-S3 upload và Model Derivative RVT 2026 → IFC;
- IfcOpenShell canonicalizer tạo canonical scene và NPZ mesh buffers;
- semantic classification baseline cho shed, office, yard và utility;
- immutable Design DNA revision cùng industrial grammar có tham số;
- một Blender scene dùng chung, bốn camera cố định;
- RGB, clay, depth PNG/EXR, normal EXR, instance ID, semantic và edge passes;
- Gemini Flash refinement có `store=false`, validation ảnh và generation manifest;
- RVT 2026 envelope inspector, SHA-256 version pinning và preview extraction;
- content-addressed artifact manifest;
- view-set generation request, durable idempotent job lifecycle và trace ID;
- identity/visibility correspondence index từ instance-ID passes;
- technical QA, fail-closed consistency report và bounded repair plan;
- FastAPI control plane, CLI, containers không chạy bằng root, JSON Schema,
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

`focus_building_ids` và `context_building_ids` trong brief nhận canonical
`scene_element_id`. Khi `focus_building_ids` có giá trị, các building còn lại tự động trở
thành context massing trong suốt và không được áp facade grammar. Nếu để cả hai danh sách
rỗng, hệ thống an toàn coi mọi building là focus thay vì tự đoán sai công trình chính.
Các đối tượng IFC có tên tiếng Việt như `đường`, `vỉa hè`, `cây xanh`, `cổng chính` được
phân loại trước khi render và truyền sang image generator bằng semantic-ID pass.

```bash
make plan-design MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make render MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
```

Ảnh tham khảo là input tùy chọn và **không phải design brief**. Pipeline chỉ dùng chúng để
tham khảo độ chân thật ảnh chụp, phản ứng vật liệu và mật độ chi tiết thi công; không sao chép
palette, hình mái, facade, massing, camera, bố cục giao thông/cảnh quan hay vật thể riêng của
dự án mẫu. Canonical Scene và Design DNA luôn có quyền ưu tiên cao hơn:

```bash
make refine-view \
  MODEL=/path/to/project.rvt \
  VIEW=view-01 \
  REFERENCES="/path/to/reference-a.jpg /path/to/reference-b.png"

# Hoặc refine toàn bộ standard view-set, kiểm tra và tạo contact sheet
make refine-viewset \
  MODEL=/path/to/project.rvt \
  BRIEF=/path/to/project-brief.json \
  REFERENCES="/path/to/reference-a.jpg /path/to/reference-b.png"
make validate-viewset MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make evaluate-consistency MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make compose-board MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
```

Artifacts được content-address theo SHA của RVT:

```text
.artifacts/
├── inspections/<revision>/
├── extractions/<revision>/
├── scenes/<revision>/
│   ├── canonical_scene.json
│   ├── meshes/
│   └── designs/<design-revision>/
│       ├── design_brief.json
│       ├── design_dna.json
│       └── view_set.json
├── renders/<model-revision>/<design-revision>/
│   ├── correspondence_index.json
│   └── <view-id>/
│       ├── base_rgb.png
│       ├── depth.png
│       ├── depth.exr
│       ├── normal.exr
│       ├── instance_id.png
│       ├── semantic.png
│       ├── edges.png
│       ├── camera.json
│       └── visibility.json
└── generated/<model-revision>/<design-revision>/
    ├── viewset_generation_manifest.json
    ├── technical_qa.json
    ├── consistency_report.json
    ├── repair_plan.json
    ├── viewset_board.jpg
    └── <view-id>/
        ├── refined.jpg
        └── generation_manifest.json
```

Đổi file RVT sẽ đổi SHA và tạo revision artifact mới. Chạy lại cùng file là idempotent.
`validate-viewset` chỉ xác nhận tính toàn vẹn và provenance của artifact. Ảnh generative vẫn
phải qua human review so với base RGB, depth, edges và brief trước khi được chấp thuận về hình học.

## Phạm vi production còn lại

Foundation hiện chạy ổn trên một máy và cố ý fail-closed. Trước khi vận hành nhiều tenant cần
bổ sung worker orchestration/queue phân tán, object storage và metadata database production,
dense pixel reprojection từ metric depth, bộ đo geometry/semantic/appearance tự động, cùng
repair executor có mask. Khi các bằng chứng đó chưa tồn tại, consistency report giữ trạng thái
`review`; technical pass không được xem là geometry pass.

## API

```bash
uvicorn v365_archviz.api:app --reload
```

Các endpoint control plane hiện có:

- `GET /healthz`
- `GET /v1/system/capabilities`
- `POST /v1/projects/{project_id}/design-revisions`
- `POST /v1/design-revisions/{design_revision}/view-sets`
- `GET /v1/view-sets/{view_set_id}`
- `POST /v1/views/{view_id}/approve`
- `POST /v1/views/{view_id}/repair`
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
- [Vietnam industrial visual guide](resource/V365_VIETNAM_INDUSTRIAL_VISUAL_GUIDE.md)

## Nguyên tắc bất biến

Mọi thứ phải giống nhau giữa các góc nhìn phải tồn tại dưới dạng 3D/design entity
deterministic bên ngoài image generator. Gemini chỉ là provider refinement, không phải
geometry source of truth.
