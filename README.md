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
- một Blender scene dùng chung, sáu camera thiết kế để đọc tổng thể, sân logistics,
  hai mặt bên và phía sau;
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

Mái dốc được fit **bên trong** envelope LOD100: ridge không vượt cao độ cực đại của khối.
Với `roof_grouping_mode=continuous_rows`, các proxy đồng hàng và cách nhau trong ngưỡng
`roof_group_gap_tolerance_m` được compile thành một `RoofAssembly`; renderer tạo một mái dọc
liên tục cho toàn dãy thay vì một mái riêng trên từng proxy.
`site_design.surrounding_context_mode=procedural_perimeter` cho phép tạo lớp bối cảnh mềm
ngoài site khi model không cung cấp surrounding buildings. Các khối này có semantic riêng,
chỉ hiển thị như massing trong suốt và không nhận facade grammar. Có thể đặt
`authored_only` để cấm hoàn toàn bối cảnh suy diễn.

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
  PROFILE=marketing_hero \
  REFERENCES="/path/to/reference-a.jpg /path/to/reference-b.png"
make validate-viewset MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make evaluate-consistency MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make compose-board MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
```

`PROFILE=marketing_hero` sinh `view-03` trước làm style anchor cho năm camera còn lại. Conditioning
semantic được chuyển sang grayscale trung tính trước khi gửi provider để màu annotation không rò
thành màu facade. `preview_fast` vẫn giữ chế độ từng view độc lập để thử nhanh, không dùng làm bộ
ảnh duyệt cuối.

## Video showreel bằng Veo 3.1 Lite

Video pipeline dùng từng ảnh đã duyệt làm first frame, tạo sáu shot độc lập 720p/4 giây rồi
ghép bằng FFmpeg. Prompt video chỉ điều khiển camera/chuyển động nhỏ và khóa hình học theo ảnh
nguồn. Mỗi operation được lưu ngay sau khi submit để có thể resume; kết quả được cache theo nội
dung ảnh, prompt và model. Mặc định ngân sách cứng là 1,20 USD cho sáu shot và mỗi request chỉ
sinh một sample.

```bash
make plan-video MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json

# Pilot một shot trước (~0,20 USD ở mức giá cấu hình mặc định)
make generate-video-shots MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json \
  VIDEO_VIEWS="view-06"

# Sau khi duyệt pilot, chạy các shot còn lại và ghép video không âm thanh
make generate-video-shots MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
make assemble-video MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
```

Veo hiện sinh audio mặc định; pipeline chủ động bỏ audio ở bước assembly. File QA xác nhận video
cuối không có audio, đúng 1280×720, 24 fps và chứa đủ các shot. Không chạy lại shot đã cache nếu
ảnh nguồn và cấu hình không đổi.

## Branding đầu ra

Mọi ảnh VIEW, board sáu góc và showreel được hậu xử lý qua `BrandWatermark`. Logo cố định
`resource/logo/logo_vertical.png` nằm ở góc trái trên, rộng 5,6% khung hình, có lề 2% và alpha
50%. Artifact chưa gắn logo được giữ riêng (`provider_source.*` hoặc `unbranded_*`) để chạy lại
không chồng watermark và có thể thay đổi cấu hình mà không giảm chất lượng.

```bash
make brand-deliverables MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
```

Các thông số branding là hằng số trong `application/brand_watermark.py`, không phụ thuộc biến
môi trường.

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
└── videos/<model-revision>/<design-revision>/<video-plan-id>/
    ├── video_plan.json
    ├── video_generation_manifest.json
    ├── showreel.mp4
    ├── showreel.qa.json
    └── shot-XX/
        ├── raw.mp4
        ├── technical_qa.json
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
- `GET /v1/models/latest`
- `POST /v1/models` (upload và kiểm tra file RVT)
- `GET /v1/brand/logo`
- `POST /v1/projects/{project_id}/design-revisions`
- `POST /v1/design-revisions/{design_revision}/view-sets`
- `GET /v1/view-sets/{view_set_id}`
- `GET /v1/view-sets/{view_set_id}/outputs`
- `GET /v1/view-sets/{view_set_id}/outputs/{asset_id}`
- `POST /v1/views/{view_id}/approve`
- `POST /v1/views/{view_id}/repair`
- OpenAPI UI: `/docs`

## Render Studio frontend

Frontend React + Ant Design nằm trong `render-fe/`. Giao diện hai panel nhận file RVT và
compile phong cách, palette, mức decor, tầng văn phòng, mái, loading dock, cảnh quan và prompt tự do thành
`DesignBrief` có version. File được kiểm tra, lưu content-addressed theo SHA và tự khớp với
Canonical Scene đã xử lý. Số tầng và prompt là ưu tiên thiết kế mềm; các khóa bảo toàn hình học,
đường giao thông và ranh cây xanh luôn được bật trong payload. Panel đầu ra poll trạng thái job,
hiển thị sáu view, board và showreel trực tiếp từ artifact API.

Chạy backend và frontend ở hai terminal:

```bash
make api
make fe-install
make fe-dev
```

Vite chạy tại `http://localhost:5173` và proxy `/v1` sang FastAPI tại cổng 8000. Kiểm tra
frontend bằng:

Ở chế độ development, FastAPI tự đưa mỗi view set vào local worker đơn luồng. Worker chạy
conditioning render, Gemini, QA, board/branding và Veo Lite ở nền; frontend theo dõi state qua
polling. Có thể tắt video bằng `V365_GENERATE_VIDEO=0` hoặc tắt worker bằng
`V365_ENABLE_LOCAL_WORKER=0` khi chỉ cần chạy control plane.

```bash
make fe-test
make fe-e2e-install
make fe-e2e
make fe-build
```

`fe-e2e` chạy luồng trình duyệt Chromium bằng Playwright với API được cô lập, vì vậy không gọi
Gemini/Veo và không phát sinh chi phí. Khi dùng giao diện thật, nhập mã dự án, chọn phong cách,
mức chi tiết, màu sắc và bối cảnh, thêm yêu cầu tự do nếu cần rồi bấm **Tạo phương án diễn họa**.
Frontend upload và khóa đúng revision của file được chọn, sau đó theo dõi job và cập nhật
ảnh/video ở panel phải. Nếu revision chưa có Canonical Scene, giao diện dừng an toàn và yêu cầu
chạy APS extraction/canonicalization trước khi phát sinh tác vụ sinh ảnh.

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
