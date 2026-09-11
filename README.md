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
- provider-neutral image refinement: Gemini bằng key hiện có hoặc OpenAI Image API, kèm
  Design Master, validation ảnh và generation manifest;
- RVT 2026 envelope inspector, SHA-256 version pinning và preview extraction;
- content-addressed artifact manifest;
- view-set generation request, durable idempotent job lifecycle và trace ID;
- identity/visibility correspondence index từ instance-ID passes;
- technical QA, fail-closed consistency report và bounded repair plan;
- FastAPI control plane, CLI, containers không chạy bằng root, JSON Schema,
  unit tests và CI quality gates.

Ảnh Blender là geometry-authoritative. Ảnh generative hiện là
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

`make render` mặc định dùng `RENDER_PROFILE=standard_eevee` (1024×576). Máy cấu hình thấp có thể
dùng `RENDER_PROFILE=preview_fast` để duyệt camera; `premium_cycles` chỉ dành cho GPU worker.
Renderer đặt cây và scale-cue entourage một lần trong shared scene theo semantic geometry,
`design_revision` và `presentation.entourage_density`; không random lại theo view. Vị trí, kích thước
và asset ID được ghi tại `entourage_manifest.json`. Mật độ `low` không tự đặt xe tải
trong service yard; xe tải chỉ xuất hiện với mật độ cao hơn và phải gắn với loading dock
đã authored.
Sau khi render, pipeline chạy camera preflight từ semantic-ID pass và dừng trước image provider nếu chủ
thể quá nhỏ/crop nặng hoặc không nhìn thấy phần giao thông đã có trong model. Có thể chạy lại riêng:

```bash
make validate-conditioning MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json
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

Mọi profile có từ hai view trở lên đều chọn camera tổng thể phù hợp nhất bằng role và conditioning
QA để làm Design Master; pipeline không hardcode một view ID. `design_identity_pack.json` khóa
facade language, palette, mái, ánh sáng và thứ tự authority cho các camera còn lại.

Gemini mặc định chạy `photoreal_balanced`: request beauty chỉ gửi Base RGB, Design Master và tối đa
một quality reference. Depth, semantic, instance ID và structural edges vẫn được lưu nhưng dùng làm
QA evidence thay vì đồng thời kéo ảnh cuối về phong cách CAD/CGI. Có thể đặt
`GEMINI_CONDITIONING_MODE=full` hoặc `minimal` để chạy benchmark hồi quy.
Có thể đặt `GEMINI_MASTER_IMAGE_MODEL=gemini-3-pro-image` để chỉ dùng model chất lượng cao cho
Design Master; năm view sau vẫn dùng `GEMINI_IMAGE_MODEL`. Spike hiện tại chưa chứng minh Pro tốt
hơn Flash cho loại guide LOD100 này, nên biến trên để trống theo mặc định.

`V365_IMAGE_PROVIDER=gemini` tiếp tục dùng `GEMINI_API_KEY` hiện có. Có thể chuyển sang
`openai-image` bằng `OPENAI_API_KEY`; worker API và CLI dùng chung một provider factory nên không
có tình trạng giao diện chạy một model còn lệnh tay chạy model khác. OpenAI adapter gửi base render
làm ảnh đầu tiên (geometry authority), Design Master làm ảnh thứ hai (appearance authority), rồi
mới đến reference về độ chân thật:

```bash
# Dùng Gemini hiện có
V365_IMAGE_PROVIDER=gemini make refine-viewset \
  MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json PROFILE=marketing_hero

# Đổi sang OpenAI Image API khi đã có OPENAI_API_KEY
V365_IMAGE_PROVIDER=openai-image make refine-viewset \
  MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json PROFILE=marketing_hero
```

Pipeline không dán pixel CG trở lại ảnh photoreal của bất kỳ provider nào. Nó giữ nguyên output và
ghi edge-alignment screen ở chế độ `validation_only`; vì kiểm tra này chưa chứng minh đầy đủ
semantic/instance conformance, kết quả vẫn bắt buộc human review trước bàn giao. Chế độ compositor
legacy vẫn còn trong application layer cho kiểm nghiệm hồi quy, nhưng không nằm trên production
job path.

Controlled-realism bake-off có thể chạy trên ba góc đại diện mà không sinh video hoặc ghi đè bộ
deliverable. Gemini hỗ trợ ba chiến lược input: `full` gửi toàn bộ pass, `minimal` gửi RGB và
structural edges, còn `photoreal_balanced` chỉ gửi các ảnh có thẩm quyền sạch. Stability Control
Structure dùng `STABILITY_API_KEY`, mặc định
`control_strength=0.85` và seed có thể tái lập:

```bash
# Gemini baseline
make refine-viewset MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json \
  GENERATED_DIR=.artifacts/experiments/project/gemini-full \
  PROFILE=marketing_hero CONDITIONING_MODE=full

# Gemini Photoreal Balanced
make refine-viewset MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json \
  GENERATED_DIR=.artifacts/experiments/project/gemini-balanced \
  PROFILE=marketing_hero CONDITIONING_MODE=photoreal_balanced

# Structure-controlled challenger
make refine-viewset MODEL=/path/to/project.rvt BRIEF=/path/to/project-brief.json \
  GENERATED_DIR=.artifacts/experiments/project/stability-structure \
  PROFILE=marketing_hero IMAGE_PROVIDER=stability-structure
```

CLI `refine-viewset` còn nhận lặp `--view view-01 --view view-03 --view view-06` để giới hạn pilot
ở ba góc tổng thể/hero/tầm mắt người trước khi trả phí cho đủ sáu ảnh.

Khi một Design Master đã được duyệt, chỉ sinh hoặc sửa những góc cần thiết và không trả phí lại cho
master. `--approved-master-view-id` là camera nguồn, không phải một ID hardcode của dự án:

```bash
.venv/bin/python -m v365_archviz refine-viewset "$RENDER_DIR" \
  --view-set "$VIEW_SET" --design-dna "$DESIGN_DNA" --model-revision "$REVISION" \
  --output "$GENERATED_DIR" --profile marketing_hero --provider gemini \
  --approved-master "$GENERATED_DIR/view-01/provider_source.jpg" \
  --approved-master-view-id view-01 --view view-06
```

Chỉ truyền `REFERENCES` khi đó là ảnh chụp nhà xưởng thật đã được curate cho chất lượng vật liệu,
ánh sáng và ống kính. Không dùng ảnh concept/CGI làm realism reference vì nó sẽ kéo cả bộ ảnh trở
lại phong cách render.

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
- `GET /v1/design-options` (preset catalog có version do backend sở hữu)
- `GET /v1/system/capabilities`
- `GET /v1/models/latest`
- `POST /v1/models` (upload và kiểm tra file RVT)
- `GET /v1/models/{model_revision}/design-capabilities`
- `POST /v1/models/{model_revision}/design-preview`
- `GET /v1/brand/logo`
- `POST /v1/projects/{project_id}/design-revisions`
- `POST /v1/design-revisions/{design_revision}/view-sets`
- `GET /v1/view-sets/{view_set_id}`
- `GET /v1/view-sets/{view_set_id}/outputs`
- `GET /v1/view-sets/{view_set_id}/outputs/{asset_id}`
- `POST /v1/view-sets/{view_set_id}/video-jobs` (chỉ chạy khi người dùng yêu cầu)
- `GET /v1/video-jobs/{video_job_id}`
- `GET /v1/video-jobs/{video_job_id}/output`
- `POST /v1/view-sets/{view_set_id}/approve`
- `POST /v1/view-sets/{view_set_id}/retry`
- `POST /v1/views/{view_id}/approve`
- `POST /v1/views/{view_id}/repair`
- OpenAPI UI: `/docs`

## Render Studio frontend

Frontend React + Ant Design nằm trong `render-fe/`. Giao diện hai panel dùng flow ba gate:
phân tích model, kiểm tra phương án, rồi mới tạo Design Master. Sau upload, backend trả capability
có semantic evidence cho envelope, office entrance, logistics, boundary, gate, landscape,
circulation và roof; UI chỉ mở component kit mà model hỗ trợ. Form dùng design package, hệ bao che,
nhịp facade, kit văn phòng/logistics/cổng/hàng rào, giới hạn accent 3/5/8%, palette, bối cảnh vận
hành, realism và prompt tự do. Không còn dùng số tầng hoặc số dock như một control trang trí.

Frontend chỉ gửi enum/value; backend lấy định nghĩa từ preset catalog, lọc yêu cầu xung đột geometry
rồi compile thành `DesignBrief` và `DesignDNA` có revision. Bước preview trả normalized intent,
cảnh báo và token SHA-256; thay đổi form sau preview buộc kiểm tra lại trước khi sinh ảnh. File được
kiểm tra và lưu content-addressed theo SHA. Revision mới được tự động dịch
RVT sang IFC bằng APS rồi canonicalize trong luồng upload; revision đã xử lý sẽ dùng lại Canonical
Scene. Mái, đường, cổng, hàng rào, massing và ranh cây xanh không nằm trong quyền override của form.
Palette được tách thành đúng vai trò mái, thân nhà, kết cấu, kính, điểm nhấn, boundary và paving;
UI có preset công nghiệp, preview tỷ lệ màu, cảnh báo phối màu không phù hợp và nút cân bằng có chủ
đích. Màu mái/cổng không còn kế thừa màu facade hoặc accent.
Panel đầu ra poll trạng thái job, hiển thị sáu view, board và showreel trực tiếp từ artifact API.
Nếu prompt tự do cố thay đổi vùng khóa, phần đó bị bỏ qua và UI nhận notification giải thích.
View set và ảnh hiện tại được lưu trong trình duyệt để tiếp tục theo dõi sau khi reload. Nếu QA
tự động không đạt nhưng sáu ảnh hợp lệ đã tồn tại, job chuyển sang `human_review`: ảnh vẫn hiển
thị đầy đủ và board/video chỉ được mở khóa sau khi người dùng duyệt. Lỗi kỹ thuật chuyển sang
`failed` và có thể tiếp tục từ checkpoint gần nhất bằng nút retry, tránh gọi lại AI không cần thiết.
Trước giai đoạn sáu ảnh, worker chỉ sinh một Design Master bằng camera có coverage tốt nhất rồi dừng
ở `design_master_review`. Người dùng kiểm tra mái, facade, màu, cổng và hàng rào trên ảnh này; nút
**Duyệt và tạo 5 góc còn lại** mới tiếp tục gọi image provider. Nếu master sai, năm lượt sinh còn
lại chưa phát sinh.

Chạy backend và frontend ở hai terminal:

```bash
make api
make fe-install
make fe-dev
```

Vite chạy tại `http://localhost:5173` và proxy `/v1` sang FastAPI tại cổng 8000. Kiểm tra
frontend bằng:

Ở chế độ development, FastAPI tự đưa mỗi view set vào image worker đơn luồng. Worker chỉ chạy
conditioning render, image provider đã cấu hình, QA và board/branding; hoàn tất image pipeline không gọi Veo. Sau khi
bộ ảnh hoàn tất, người dùng có thể chủ động bấm **Tạo video trình diễn**. Video worker riêng vẫn
tạo đủ sáu shot, ghép thành showreel không audio và chèn logo. Có thể tắt toàn bộ local worker bằng
`V365_ENABLE_LOCAL_WORKER=0` khi chỉ cần chạy control plane.

```bash
make fe-test
make fe-e2e-install
make fe-e2e
make fe-build
```

`fe-e2e` chạy luồng trình duyệt Chromium bằng Playwright với API được cô lập, vì vậy không gọi
Gemini/Veo và không phát sinh chi phí. Khi dùng giao diện thật: upload RVT, bấm **Phân tích cấu kiện
có thể thiết kế**, nhập mã dự án và chọn các kit được mở, bấm **Kiểm tra phương án**, sau đó bấm
**Tạo Design Master**.
Frontend upload và khóa đúng revision của file được chọn, sau đó theo dõi job và cập nhật
ảnh ở panel phải; video chỉ xuất hiện sau yêu cầu riêng có xác nhận chi phí. Nếu máy chủ thiếu cấu
hình APS, giao diện dừng an toàn trước khi phát sinh tác vụ sinh ảnh.

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

Contract public của form được xuất tại `schemas/user_render_intent.schema.json`; mọi generated
view từ revision mới ghi checksum của `render_intent.json` vào identity pack và generation
manifest để truy vết chính xác style người dùng đã chọn.

## Cấu trúc

```text
src/v365_archviz/
├── application/       # use cases, không phụ thuộc transport
├── domain/            # immutable validated contracts
├── providers/         # APS/image/video/local adapter boundaries
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
deterministic bên ngoài image generator. Gemini/OpenAI chỉ là provider refinement, không phải
geometry source of truth.
