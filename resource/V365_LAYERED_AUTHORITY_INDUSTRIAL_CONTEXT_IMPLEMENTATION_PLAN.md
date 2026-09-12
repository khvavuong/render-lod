# V365 Layered Authority & Industrial Context — Kế hoạch triển khai

**Phiên bản:** 1.0  
**Ngày:** 2026-09-11  
**Trạng thái:** Approved for implementation  
**Phạm vi:** RVT/LOD100 → sáu ảnh nhà xưởng có bối cảnh khu công nghiệp, chân thật, đồng nhất và có
thể kiểm soát

## 1. Quyết định kiến trúc

Pipeline không tiếp tục giải bài toán bằng cách tăng độ dài prompt hoặc giao toàn bộ ảnh cho một
lượt Gemini. Hướng triển khai được chốt là **Layered Authority**:

1. hình học dự án là nguồn đúng bắt buộc;
2. thiết kế facade chỉ được phát triển trên các bề mặt đã xác định là designable;
3. mặt đất, đường, cây xanh và atmosphere ngoài dự án được hoàn thiện trong vùng context;
4. nhà xưởng lân cận là geometry proxy nhất quán, được composite trong suốt bằng pipeline
   deterministic;
5. Gemini tạo độ chân thật và chất lượng nhiếp ảnh, không quyết định topology của dự án hoặc vị trí
   context building.

```text
RVT / IFC / selected 3D scope
        ↓
Canonical Scene + Semantic Evidence
        ↓
Designability Analysis + Industrial Context Plan
        ↓
Shared 3D scene
  ├── PROJECT_LOCKED
  ├── PROJECT_DESIGNABLE
  ├── CONTEXT_GROUND
  └── CONTEXT_PROXY
        ↓
6 cameras + layered control pack
        ↓
Site Master + Facade Master → explicit approval
        ↓
Gemini localized photoreal refinement
        ↓
Deterministic context-proxy composite
        ↓
Geometry + semantic + material + context + realism QA
        ↓
6-view certified set → board + branding
```

## 2. Mục tiêu và giới hạn

### 2.1. Mục tiêu

- Khối xưởng chính, mái, footprint, tỷ lệ, đường nội bộ, cổng, hàng rào và vùng xanh bám model.
- Bối cảnh đọc rõ là một khu công nghiệp Việt Nam có tổ chức, không phải rừng hoặc khoảng nền CGI.
- Nhà xưởng ngoài dự án xuất hiện dưới dạng khối quy hoạch trong suốt, thống nhất giữa sáu view và
  không cạnh tranh thị giác với dự án chính.
- Mặt đứng được phát triển đủ chi tiết để thuyết phục chủ đầu tư nhưng mọi chi tiết mới đều có
  nguồn gốc, rule và trạng thái `proposed` rõ ràng.
- Ảnh cuối có material response, ánh sáng, ground contact, vegetation và image science giống ảnh
  chụp thực tế.
- Không hardcode tên view, tọa độ, kích thước hoặc hình dạng của một model sample.
- Không phát sinh năm lượt ảnh còn lại nếu master chưa đạt.

### 2.2. Không nằm trong phạm vi

- Không khẳng định context proxy là hiện trạng thực tế nếu không có GIS/site plan/context BIM.
- Không tự thiết kế thêm tầng, thay đổi kết cấu, chiều cao hoặc công năng của nhà xưởng.
- Không cho AI tự tạo vị trí cổng, đường, hàng rào hoặc context building mà không qua planning.
- Không dùng ảnh reference để sao chép một dự án, palette, logo hoặc facade cụ thể.
- Không dùng video để che các lỗi của bộ ảnh tĩnh.

## 3. Bằng chứng và vấn đề hiện tại

Bộ gần nhất `R01-77738461962b` cho thấy:

- `reference_roles` rỗng nên sample không đi vào request;
- `surrounding_context_mode=authored_only` và `surrounding_context_count=0`, vì vậy pipeline không
  có hình học nhà xưởng lân cận;
- prompt đồng thời yêu cầu khu công nghiệp phát triển và cấm tạo context trong pixel trống;
- master là `VIEW-04`, có focus coverage cao nhưng context coverage gần bằng 0;
- master và các view dùng `gemini-3.1-flash-image`, profile 1K, không truyền
  `generation_config.thinking_level`, nên Flash dùng mức mặc định `minimal`;
- prompt dự án dài khoảng 1.500 từ, lặp nhiều phủ định và trộn constraint kỹ thuật với photographic
  direction;
- model không có semantic office block hoặc authored opening, nhưng pipeline vừa tạo articulation
  metadata vừa cấm mọi opening mới, dẫn đến facade lớn và trống;
- `technical_qa.json` fail material-role ở cả sáu view nhưng human approval vẫn có thể đưa job tới
  `completed`.

Đây là lỗi kiến trúc dữ liệu và workflow, không chỉ là vấn đề chọn từ ngữ trong prompt.

## 4. Mô hình thẩm quyền theo vùng

### 4.1. `PROJECT_LOCKED`

Bao gồm:

- footprint, silhouette, chiều cao và số lượng khối;
- roof assembly, ridge direction và tính liên tục mái;
- authored building opening;
- đường trong/ngoài ranh đã có trong model;
- yard, parking, curb, drainage có evidence;
- ranh đất, vị trí opening cổng và hàng rào;
- landscape-zone boundary;
- camera và framing.

Quyền xử lý:

- Gemini chỉ được thay material response, micro-detail và ánh sáng;
- không thêm, xóa, dịch chuyển hoặc đổi topology;
- QA phải so sánh hai chiều với geometry/semantic evidence.

### 4.2. `PROJECT_DESIGNABLE`

Đây là vùng facade được phép phát triển thiết kế có kiểm soát. Mỗi vùng phải có:

- `surface_id` ổn định;
- polygon/UV hoặc local facade frame;
- chiều dài, chiều cao, hướng và vùng loại trừ;
- quan hệ với road, gate, yard, office/logistics evidence;
- danh sách kit được phép;
- trạng thái `authored`, `inferred_proposal` hoặc `needs_review`;
- deterministic seed và design revision.

Chi tiết được phép đề xuất khi có rule phù hợp:

- panel seams, plinth, eave/top band, flashing, downpipe;
- personnel door tại bay có quan hệ circulation phù hợp;
- loading door/canopy tại bay tiếp giáp authored logistics zone;
- office entrance/glazing chỉ khi có office evidence hoặc người dùng bật chế độ conceptual proposal
  và duyệt vị trí;
- accent frame/fin/canopy theo kit và giới hạn diện tích.

Mọi chi tiết phải được dựng trong shared 3D scene trước khi sinh ảnh để xuất hiện cùng vị trí ở sáu
view. Gemini không được tự quyết định số lượng hoặc vị trí của chúng.

### 4.3. `CONTEXT_GROUND`

Bao gồm vùng ngoài ranh dự án có thể hoàn thiện thành:

- industrial collector road và service road;
- curb, sidewalk, drainage, median hoặc verge;
- lô đất công nghiệp, mặt đất thấp tầng, bãi đất và thảm cỏ;
- hàng cây theo tuyến, green buffer và atmosphere;
- background continuity và skyline thấp.

Đây là vùng Gemini được phép photorealize mạnh hơn, nhưng không được tràn vào project masks.

### 4.4. `CONTEXT_PROXY`

Bao gồm các khối xưởng lân cận mang tính quy hoạch. Các khối này:

- nằm ngoài project boundary;
- không giao cắt external/internal road;
- được tạo một lần trong world coordinates và dùng chung cho sáu view;
- có footprint, chiều cao, roof direction và setback hợp lý theo tỷ lệ dự án;
- không có facade decor, logo, cửa chi tiết hoặc palette thương hiệu;
- được render/composite bằng vật liệu trung tính, opacity 0,22–0,30;
- có ground contact, ambient shadow nhẹ và atmospheric fade;
- luôn được ghi nhãn là conceptual context trong manifest.

Gemini không trực tiếp tạo hoặc làm trong suốt các khối này. Đây là điều kiện bắt buộc để tránh
drift giữa các view và hiện tượng glass/ghost building.

## 5. Industrial Context Planner

### 5.1. Input

- project boundary và site bounding box;
- external/internal road axes;
- gate opening và approach direction;
- focus/auxiliary building footprints;
- authored context nếu có;
- camera set;
- project scale, north direction và world elevation;
- context mode từ người dùng.

### 5.2. Chế độ context

| Mode | Dữ liệu | Hành vi |
|---|---|---|
| `authored_only` | Context có trong RVT/IFC | Không tạo proxy ngoài dữ liệu |
| `conceptual_industrial_park` | Không đủ context | Sinh road/plot/proxy theo rule và ghi rõ conceptual |
| `site_plan_aligned` | Có CAD/GIS/site plan | Bám footprint và road của nguồn ngoài |
| `none` | Người dùng không cần context | Chỉ sky/neutral ground continuity |

Production mặc định với LOD100 thiếu context là `conceptual_industrial_park`, không còn tự động
đồng nghĩa với `authored_only`.

### 5.3. Thuật toán khái quát, không hardcode

1. Chuẩn hóa site frame theo trục dài/ngắn của boundary.
2. Khóa buffer an toàn quanh project boundary và external roads.
3. Kéo dài các external-road axis ra context ring nếu topology cho phép.
4. Chia phần đất còn lại thành các plot dựa trên road frontage và tỷ lệ công trình chính.
5. Đặt tối đa số proxy theo context density và camera visibility budget.
6. Chọn footprint aspect ratio, setback, height band và roof direction từ industrial grammar.
7. Loại proxy che cổng, silhouette chính hoặc vượt prominence budget.
8. Lưu `IndustrialContextPlan` trước khi Blender dựng geometry.

Mọi lựa chọn pseudo-random dùng seed từ `model_revision + design_revision + context_version`, nhờ
đó rerun và sáu view luôn nhất quán.

### 5.4. Context prominence budget

- Tổng projected context coverage theo view phải có ngưỡng theo role.
- `overall/context`: đủ đọc cấu trúc khu công nghiệp nhưng focus project vẫn nổi bật.
- `hero/detail/human`: context giảm contrast, detail và opacity theo depth.
- Proxy không được che gate, fence, facade design bay hoặc đường tiếp cận chính.

## 6. Layered control pack

Mỗi view bổ sung các artifact:

- `project_locked_mask.png`;
- `project_designable_mask.png`;
- `context_ground_mask.png`;
- `context_proxy_mask.png`;
- `context_proxy_rgba.png`;
- `context_depth.png`;
- `facade_design_id.png`;
- `industrial_context_plan.json` dùng chung;
- `layer_authority_manifest.json`.

`layer_authority_manifest.json` phải chứa:

- checksum của Canonical Scene, Design DNA và context plan;
- role, authority và nguồn evidence của từng layer;
- deterministic seed;
- camera/view ID;
- vùng được phép AI edit;
- composite order;
- opacity/material family của proxy;
- phiên bản planner và prompt.

Thứ tự composite:

1. Gemini photoreal output;
2. restore/protect vùng project bắt buộc nếu QA yêu cầu;
3. composite `CONTEXT_PROXY` bằng premultiplied alpha;
4. color harmonization nhẹ chỉ cho proxy;
5. watermark cuối cùng.

## 7. Thiết kế facade ở LOD100

### 7.1. Tách authored và proposed

LOD100 thường chỉ có khối và vùng chức năng, vì vậy `không có opening trong model` không luôn đồng
nghĩa `facade phải để trống`. Contract mới phân biệt:

- `authored`: hình học có trong model, bắt buộc giữ;
- `inferred_proposal`: thiết kế đề xuất từ kit và semantic adjacency;
- `unsupported`: không đủ cơ sở, không phát sinh;
- `needs_review`: có nhiều phương án hợp lý, người dùng phải duyệt.

UI và manifest phải nói rõ đây là thiết kế proposal, không giả thành BIM-authored fact.

### 7.2. Designability rules

- Mặt đứng tiếp giáp loading zone có thể cho phép logistics kit.
- Mặt đứng tiếp giáp main entrance/circulation có thể đề xuất personnel entrance; office glazing
  chỉ khi office block hoặc conceptual-office approval tồn tại.
- End wall không tự nhận pattern của long facade.
- Door/canopy không cắt cột, plinth, roof edge hoặc zone loại trừ.
- Số module dựa trên facade length và bay grammar, không lấy từ prompt tự do.
- Toàn bộ geometry proposal được lưu trong Design DNA và tái chiếu sang mọi camera.

### 7.3. Preview và duyệt

Trước Gemini, UI hiển thị deterministic preview gồm:

- facade elevations hoặc crop 3D;
- vị trí opening proposed/authored;
- material-role overlay;
- cổng, hàng rào và context proxy;
- cảnh báo phần nào là conceptual.

Thay đổi sau preview làm mất hiệu lực preview token.

## 8. Chiến lược reference

### 8.1. Hai nhóm reference độc lập

`factory_design_reference`:

- construction detail density;
- cladding, roof, plinth, door/canopy và glazing response;
- tỷ lệ người/xe và mức vận hành;
- không truyền site layout hoặc palette.

`context_realism_reference`:

- cấu trúc khu công nghiệp;
- collector road, plot, verge, street tree và atmospheric depth;
- không truyền building footprint hoặc facade của dự án reference.

Ảnh khu công nghiệp người dùng vừa cung cấp thuộc nhóm thứ hai. `sample_image.png` phù hợp hơn cho
design/finish; `sample_image_2.png` chỉ dùng làm quality benchmark nếu đúng loại view, không dùng
làm industrial-context authority.

### 8.2. Reference registry

Tạo registry có metadata:

- `reference_id`, checksum, license/source;
- typology, climate, country/region;
- view role và camera height;
- allowed influence roles;
- prohibited influence roles;
- quality approval status.

UI hỗ trợ upload reference hoặc chọn reference đã duyệt. Chế độ `tender` phải từ chối generation
nếu không có reference phù hợp với master role.

## 9. Gemini orchestration

### 9.1. Hai master thay cho một master mơ hồ

1. **Site Master**: view tổng thể thể hiện project boundary, đường, gate, fence, landscape và
   industrial context.
2. **Facade Master**: view thể hiện nhiều designable facade, opening và material role nhất.

Master selection chấm semantic diversity, không chỉ projected focus coverage:

```text
score = geometry_pass
      + visible_project_roles
      + gate/fence/circulation_visibility
      + designable_facade_coverage
      + context_legibility
      - occlusion
      - crop_penalty
      - missing_role_penalty
```

Hai master có thể là cùng một view chỉ khi đạt cả hai rubric.

### 9.2. Model/profile

| Stage | Model mặc định | Size | Thinking |
|---|---|---:|---|
| Form preview | Không gọi AI | — | — |
| Cheap composition candidate | Gemini 3.1 Flash Image | 1K | `high` |
| Site Master tender | Gemini 3 Pro Image | 2K | model-managed |
| Facade Master tender | Gemini 3 Pro Image | 2K | model-managed |
| Remaining views | Gemini 3.1 Flash Image | 2K | `high` |
| Localized repair | Gemini 3.1 Flash Image | 1K/2K | `high` |

Không dùng profile 1K preview làm output bàn giao.

### 9.3. Prompt contract

Thay prompt khoảng 1.500 từ bằng các block ngắn, theo stage:

1. `task` — photoreal edit của view hiện tại;
2. `authority` — source nào quyết định geometry/design/context;
3. `view brief` — camera, lens, subject và ánh sáng;
4. `allowed changes` — material response và chi tiết trong mask;
5. `identity` — palette/kit đã duyệt;
6. `prohibited changes` — tối đa 5–8 lỗi quan trọng nhất;
7. `reference roles` — influence được phép của từng ảnh.

Mục tiêu 300–500 từ/request. Constraint chi tiết nằm trong geometry, mask, manifest và QA; không
lặp toàn bộ vào prompt.

### 9.4. Input theo stage

Site Master nhận:

- current-view clean Base RGB;
- project/context authority map dễ hiểu;
- một context realism reference;
- deterministic identity board.

Facade Master nhận:

- current-view Base RGB đã có proposed geometry;
- project/designable authority map;
- một factory design reference;
- identity board và approved Site Master chỉ cho exposure/atmosphere.

View còn lại nhận:

- Base RGB của chính view;
- identity board;
- approved master có overlap/role phù hợp;
- tối đa một quality reference theo view role.

## 10. API và domain contract

### 10.1. Domain models mới

- `LayerAuthority`: `project_locked`, `project_designable`, `context_ground`, `context_proxy`.
- `DesignEvidenceState`: `authored`, `inferred_proposal`, `needs_review`, `unsupported`.
- `IndustrialContextMode`.
- `IndustrialContextPlan`.
- `ContextPlot`, `ContextRoad`, `ContextProxyBuilding`, `ContextLandscapeBand`.
- `FacadeDesignRegion`, `ProposedOpening`, `FacadeKitApplication`.
- `ReferenceAsset`, `ReferenceRole`, `ReferenceInfluencePolicy`.
- `MasterType`: `site`, `facade`.
- `QualityProfile`: `preview`, `tender`.

Schema phải version hóa và export tự động như các domain contract hiện tại.

### 10.2. API đề xuất

- `POST /v1/models/{revision}/industrial-context-preview`
  - lập context plan, không gọi Gemini;
  - trả preview URL, plan ID, warning và context token.
- `POST /v1/models/{revision}/facade-design-preview`
  - tạo proposed design geometry;
  - trả evidence state và preview token.
- `POST /v1/references`
  - upload/validate ảnh reference và khai báo role.
- `GET /v1/references?role=...`
  - trả registry đã duyệt.
- `POST /v1/projects/{project_id}/design-revisions`
  - nhận context/facade preview token và reference IDs.
- `POST /v1/view-sets/{id}/masters`
  - tạo Site Master và Facade Master.
- `POST /v1/view-sets/{id}/masters/{type}/approve`.
- `POST /v1/view-sets/{id}/approve`
  - chỉ được phép khi không còn hard QA failure.

Token phải khóa model revision, design revision, context plan, reference checksum, quality profile,
catalog version và prompt version.

## 11. UX đề xuất

Form giữ workflow có điều kiện và bổ sung:

1. **Model** — upload và semantic capability analysis.
2. **Thiết kế dự án** — envelope, facade, logistics, gate/fence và palette.
3. **Bối cảnh** — chọn authored/conceptual/site-plan, context density và proxy opacity preset.
4. **Reference** — factory design và industrial context là hai ô riêng.
5. **Preview** — xem project/designable/context layer và các proposal.
6. **Site Master review**.
7. **Facade Master review**.
8. **Generate remaining views**.
9. **Final QA review**.

UI phải:

- ghi rõ khối context là conceptual;
- không cho opacity tự do ngoài dải an toàn mặc định;
- không mở generation tender khi thiếu required reference;
- có `Reject & regenerate master`, không chỉ có nút approve;
- hiển thị QA fail theo view và role;
- không cho chuyển `human_review → completed` khi còn hard failure;
- chỉ hiện nút tạo video sau khi bộ ảnh được approved final.

## 12. QA và certification

### 12.1. Hard gates

- Project geometry alignment.
- Roof topology/orientation/continuity.
- Authored road/gate/fence/landscape retention.
- Proposed facade geometry consistency giữa các view.
- Context proxy world-coordinate consistency.
- Proxy không giao cắt project/road và không che protected role.
- Context opacity/material nằm trong contract.
- Material-role compliance.
- Reference checksum/role consistency.
- Output resolution/profile đúng delivery mode.

Hard gate fail không thể được bỏ qua bằng approve thông thường. Override phải là endpoint riêng, có
reviewer, reason và audit trail; output vẫn không được gắn `approved_final` nếu geometry hard gate
fail.

### 12.2. Scored gates

- Photorealism: vật liệu, contact shadow, ground texture, atmosphere, vegetation và image science.
- Industrial-context credibility.
- Subject prominence.
- Facade design quality và constructibility.
- Cross-view appearance consistency.
- Composition và camera usefulness.

Điểm tự động chỉ hỗ trợ xếp hạng candidate. Human review vẫn là điều kiện bàn giao.

### 12.3. Context QA

Cho mỗi view lưu:

- projected proxy count và coverage;
- context-ground coverage;
- opacity statistics;
- overlap với project/gate/road masks;
- visibility correspondence sang các view khác;
- prominence score;
- cảnh báo proxy floating/ghost/glass-like.

## 13. Workflow state mới

```text
DESIGN_VALIDATION
  → CONTEXT_PLANNING
  → CONTEXT_REVIEW
  → BUILDING_SCENE
  → RENDERING_PASSES
  → GENERATING_SITE_MASTER
  → SITE_MASTER_REVIEW
  → GENERATING_FACADE_MASTER
  → FACADE_MASTER_REVIEW
  → GENERATING_VIEWSET
  → VALIDATING
      ├── hard fail → REPAIRING / HUMAN_REVIEW
      └── pass → FINAL_REVIEW
  → COMPOSING_BOARD
  → COMPLETED
```

Mỗi checkpoint phải resumable và idempotent. Regenerate master không được chạy lại extraction,
context planning hoặc Blender nếu upstream checksum không đổi.

## 14. Kế hoạch triển khai

### Phase 0 — Khóa lỗi chất lượng hiện tại

- Truyền `generation_config.thinking_level=high` cho Gemini 3.1 Flash Image.
- Dùng 2K cho `tender`; 1K chỉ là preview.
- Không cho `master_model=None` trong tender; cấu hình rõ model và ghi manifest.
- Rút prompt theo stage và loại contradiction `authored_only`/developed context.
- Bắt buộc truyền reference roles vào request và manifest.
- Chặn approve final khi `technical_qa.passed=false`.
- Thêm nút reject/regenerate master.

**Exit criteria:** test chứng minh payload đúng model/size/thinking/reference; QA fail không thể đi tới
completed.

### Phase 1 — Context contracts và planner

- Thêm domain/schema của Industrial Context Plan.
- Phân tích site frame, road topology và protected buffer.
- Sinh context plots, roads, landscape band và proxy massing bằng rule tổng quát.
- Lưu seed/provenance và preview artifact.
- Thêm context preview API và UI.

**Exit criteria:** cùng model/design revision tạo context plan byte-identical; không proxy nào xâm
phạm project hoặc road; sáu camera dùng cùng world geometry.

### Phase 2 — Layered renderer và composite

- Blender tạo bốn layer authority và mask riêng.
- Render `context_proxy_rgba` có alpha/material contract.
- Tạo compositing service deterministic.
- Bổ sung authority manifest/checksum.
- Cập nhật output protection để không phục hồi pixel sai layer.

**Exit criteria:** opacity, vị trí và hình dáng context proxy nhất quán; Gemini output không thể đổi
proxy; không có floating/ghost proxy.

### Phase 3 — Facade designability

- Xây facade local frame và exclusion zones.
- Tách authored/inferred/unsupported evidence.
- Dựng proposed doors, loading frontage, panel system và canopy theo kit.
- Thêm deterministic facade preview và explicit approval.
- Cập nhật Design DNA để proposed geometry trở thành shared design authority.

**Exit criteria:** chi tiết proposed xuất hiện đúng tọa độ trong sáu view; không cắt roof/road/
structure; model thiếu office không còn âm thầm tạo sảnh giả.

### Phase 4 — Dual Master và reference registry

- Xây semantic-diversity master scoring.
- Thêm Site Master/Facade Master workflow.
- Xây reference registry, upload UI và influence policy.
- Dùng Pro 2K cho tender masters, Flash 2K/high cho remaining views.
- Chỉ phát sinh remaining-view cost sau khi cả hai master được duyệt.

**Exit criteria:** master bao phủ site/context và facade identity; reference được truyền thật trong
request; style drift giảm so với baseline.

### Phase 5 — QA, repair và certification

- Thêm cross-view proposed-geometry/context correspondence.
- Thêm context/material/realism rubrics.
- Localized repair theo layer/mask.
- Khóa state transition và audit override.
- Chỉ gắn `approved_final` khi hard gates pass và human review approve.

**Exit criteria:** lỗi material/context ở một view không bắt regenerate toàn bộ; không có output
fail được báo completed/approved final.

## 15. Chiến lược kiểm thử

### 15.1. Unit

- context planning, seed stability, road/project collision;
- facade designability và evidence state;
- master scoring;
- prompt composition và reference influence policy;
- transition guard;
- alpha composite và checksum.

### 15.2. Integration

- RVT thiếu context → conceptual context plan;
- RVT có authored context → không duplicate proxy;
- thiếu office nhưng có loading zone;
- nhiều cổng và nhiều mặt tiền;
- regeneration sau khi đổi palette/reference/context density;
- resume sau master approval;
- QA fail → không completed.

### 15.3. Visual regression

Giữ bộ golden artifacts ở resolution thấp cho:

- authority masks;
- proxy placement;
- facade proposal;
- six-view projected consistency;
- context prominence.

Không dùng pixel-perfect cho output Gemini; dùng manifest, masks, geometry metrics và human-scored
benchmark.

### 15.4. Playwright

- upload/analysis;
- context mode và reference upload;
- preview invalidation;
- Site Master reject/approve;
- Facade Master reject/approve;
- hard QA fail không có nút approve final;
- completed images mới cho phép video.

## 16. Benchmark bắt buộc

Chạy trên ít nhất ba model không cùng topology và sáu role camera:

- **A — baseline hiện tại:** Flash 1K, single master, không layered context.
- **B — layered context:** Flash 2K/high, dual master logic, deterministic proxy.
- **C — tender:** Pro 2K masters + Flash 2K/high remaining views.

Mỗi candidate chấm mù theo thang 1–5:

- geometry/site fidelity;
- industrial-context credibility;
- facade constructibility;
- material realism;
- vegetation/road realism;
- cross-view consistency;
- composition;
- bid-presentation readiness.

Chỉ chọn production profile khi:

- không giảm hard fidelity so với baseline;
- realism và bid-readiness tăng có ý nghĩa trên đa số model;
- không phụ thuộc một sample/reference cụ thể;
- retry rate và chi phí nằm trong budget.

## 17. Chi phí và retry policy

Theo bảng giá Gemini công bố tại thời điểm viết kế hoạch:

- Gemini 3.1 Flash Image: khoảng USD 0,101/ảnh 2K;
- Gemini 3 Pro Image: khoảng USD 0,134/ảnh 1K/2K.

Một bộ tender gồm hai master Pro và bốn view Flash có chi phí output ảnh khoảng USD 0,67, chưa tính
input/thinking nhỏ và retry. Đây là baseline để đo, không hardcode vào nghiệp vụ; giá phải đến từ
configuration/telemetry.

Retry policy:

- tối đa hai candidate/master trước khi yêu cầu người dùng đổi input;
- localized repair trước full-view retry;
- không retry năm view nếu master fail;
- cache theo checksum của every authority input;
- Batch API chỉ dùng cho workload không cần phản hồi tức thời sau khi benchmark.

Tài liệu tham chiếu chính thức:

- https://ai.google.dev/gemini-api/docs/image-generation
- https://ai.google.dev/gemini-api/docs/models/gemini-3-pro-image
- https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image
- https://ai.google.dev/gemini-api/docs/pricing

## 18. Definition of Done

Kế hoạch được coi là triển khai hoàn tất khi:

1. context industrial park có road/green/ground photoreal và không tràn vào project;
2. context buildings là proxy trong suốt, đồng nhất world geometry ở sáu view;
3. vị trí cổng, hàng rào, đường và vùng xanh bám model;
4. facade không còn trống kiểu LOD100 nhưng mọi chi tiết mới có proposed evidence và được duyệt;
5. Site Master và Facade Master đều được duyệt trước remaining views;
6. tender dùng đúng model/profile/reference/thinking policy;
7. hard QA fail không thể trở thành completed/approved final;
8. ảnh bàn giao đạt điểm trung bình tối thiểu 4/5 ở realism, consistency và bid-readiness trên bộ
   benchmark ba model;
9. không có rule theo model/sample cụ thể;
10. toàn bộ unit, integration, schema, frontend, Playwright và visual-regression tests pass.

## 19. Thứ tự ưu tiên thực hiện

Ưu tiên triển khai theo chuỗi:

1. Phase 0 để dừng việc tạo output fail nhưng báo hoàn tất;
2. Phase 1–2 để giải quyết đúng bối cảnh khu công nghiệp và proxy trong suốt;
3. Phase 3 để nâng chất lượng thiết kế facade mà vẫn nhất quán;
4. Phase 4 để khai thác đúng khả năng Gemini/reference;
5. Phase 5 và benchmark để xác nhận đủ điều kiện bàn giao.

Không nên mở rộng thêm form decor trước khi Layered Authority, context plan và state guard hoàn tất.
