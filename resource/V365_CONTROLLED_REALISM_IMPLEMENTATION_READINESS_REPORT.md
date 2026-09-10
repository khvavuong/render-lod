# V365 Controlled Realism — Implementation Readiness Report

**Ngày đánh giá:** 2026-09-10  
**Kế hoạch nguồn:** `V365_CONTROLLED_REALISM_IMPLEMENTATION_PLAN.md` v1.0  
**Mục đích:** xác nhận mức sẵn sàng, chốt quyết định kỹ thuật và định nghĩa gói công việc đầu tiên

## 1. Kết luận

Hướng `PBR-first + shared-scene + mask-bounded generation + evidence-based QA` là đúng và nên tiếp
tục. Tuy nhiên hệ thống hiện tại **chưa đủ điều kiện chứng nhận output để bàn giao tự động**.

Điểm mạnh hiện có:

- canonical geometry, Design DNA, sáu camera và shared Blender scene đã hoạt động;
- đã có RGB, depth, normal, edge, semantic và instance passes;
- có immutable revision, manifest, technical artifact QA và human-review placeholder;
- Gemini style-anchor cải thiện độ đồng nhất hơn generation độc lập;
- bốn model khác nhau đã được canonicalize và dùng làm dữ liệu phát triển ban đầu.

Các blocker trước khi gọi output là `GEOMETRY_CERTIFIED`:

1. PBR hiện tại vẫn là vật liệu màu phẳng, chưa có texture/normal/roughness asset library.
2. Renderer production vẫn dùng Eevee ở 768×432; container chưa dùng GPU Cycles.
3. Chưa có control-mask contract và provider hiện tại không thực thi mask/control strength cứng.
4. Correspondence mới là object-level visibility, chưa có dense pixel reprojection.
5. QA chỉ kiểm tra artifact; mọi visual gate hiện trả `evidence_not_available`.
6. Workflow vẫn có thể hoàn thành và làm board khi consistency report là `review`.
7. UI/API chưa thể hiện certification state độc lập với job-completed state.

Quyết định triển khai: **bắt đầu Phase 0 và Phase 1; chưa xây custom diffusion hoặc texture-space
model.** Mốc đầu tiên là tạo một base PBR đủ tốt và một cơ chế chứng minh phần hình học nào đã được
bảo vệ.

## 2. Bằng chứng từ repository

### 2.1. Renderer

`scripts/blender/render_conditioning.py` hiện:

- tạo Principled BSDF chỉ từ base color, metallic và roughness;
- chưa có image texture, normal, displacement, decal, instanced vegetation hoặc HDRI library;
- luôn chọn `BLENDER_EEVEE_NEXT`/`BLENDER_EEVEE`;
- render mặc định 768×432;
- đã dùng Nishita sky và AgX, đây là nền tảng tốt để giữ;
- tự dựng mái/facade detail bằng procedural boxes, phù hợp prototype nhưng chưa đạt construction
  detail và phản ứng vật liệu cần cho final.

Docker image đang chạy Blender 4.0.2 từ Ubuntu package, không pin version/digest. Máy phát triển có
RTX 4050 Laptop 6 GB VRAM và driver đủ mới cho OptiX, nhưng Docker command chưa truyền GPU và scene
chưa cấu hình Cycles device.

### 2.2. Dữ liệu và semantic

Hiện có bốn canonical scene với quy mô khác nhau:

| Model revision | Elements | Surfaces | Nhận xét |
|---|---:|---:|---|
| `480b5e63…` | 42 | 148 | nhiều khối shed/office, surface khá đầy đủ |
| `a7d22ba3…` | 101 | 32 | nhiều road/landscape, surface còn ít |
| `5d88d24…` | 228 | 92 | site phức tạp, có entrance/parking |
| `c4ce9974…` | 42 | 20 | một shed chính, site elements tương đối rõ |

Đây là dev set hữu ích nhưng chưa đủ benchmark 10–20 model. Semantic hiện còn coarse và không đồng
đều giữa các model; gate/fence/curb/drainage chưa phải contract ổn định.

### 2.3. Generative layer

Gemini adapter nhận nhiều ảnh theo thứ tự RGB/depth/instance/semantic/edge/reference. Với profile
chất lượng, VIEW-03 được sinh trước và truyền làm style anchor cho năm view sau.

Điểm này giúp style consistency nhưng không phải hard spatial control:

- không có mask field;
- không có denoise/edit strength;
- không có control scale;
- sáu view không chia sẻ latent hoặc texture state;
- prompt yêu cầu bảo toàn geometry nhưng provider không có contract bắt buộc phải làm đúng.

Gemini vẫn phù hợp với candidate generation và global photographic finishing có review. Không được
dùng riêng output full-frame của Gemini để tuyên bố hard geometry guarantee.

### 2.4. QA

Tất cả consistency report hiện có đều ở trạng thái `review` với bốn finding
`evidence_not_available`: geometry, semantic, cross-view appearance và aesthetic.

`BuildCorrespondenceIndex` chứng minh object identity và object visibility giữa view nhưng tự khai
báo `pixel_reprojection_maps_available: false`. Đây là provenance tốt, chưa phải multi-view pixel
consistency.

Kết luận quan trọng: trạng thái workflow `completed` hiện chỉ có nghĩa pipeline đã chạy xong, không
có nghĩa output được chứng nhận để bàn giao.

## 3. Kết quả nghiên cứu và lựa chọn công nghệ

### 3.1. Giữ Blender, nâng lên bản LTS được pin

Không chuyển sang Unreal ở giai đoạn này. Blender đã tích hợp sâu với canonical scene, headless
worker và conditioning passes; đổi renderer sẽ tăng rủi ro mà chưa giải quyết control/QA.

Chọn Blender **4.5 LTS**, pin exact version và image digest. Blender 4.5 LTS được hỗ trợ đến tháng
7/2027 và phù hợp hơn image Ubuntu hiện tại dùng Blender 4.0.2 không pin:
[Blender 4.5 LTS](https://www.blender.org/releases/4-5/).

Final profile dùng Cycles + OptiX. Blender xác nhận OptiX hỗ trợ RTX trên Linux và GPU rendering có
thể nhanh hơn, nhưng bị giới hạn bởi VRAM:
[Cycles GPU rendering](https://docs.blender.org/manual/en/4.5/render/cycles/gpu_rendering.html).

Khởi điểm benchmark, chưa phải ngưỡng cố định:

| Profile | Engine | Resolution | Sampling | Denoising | Mục đích |
|---|---|---:|---|---|---|
| `preview_fast` | Eevee | 768×432 | N/A | N/A | camera/layout preview |
| `qa_pbr` | Cycles GPU | 1024×576 | adaptive, max 64 | OIDN, albedo+normal | QA và tuning |
| `final_pbr` | Cycles GPU | 2048×1152 | adaptive, max 128 | OIDN, albedo+normal | base bàn giao/AI |

Adaptive sampling và denoising bằng albedo+normal phù hợp cho việc giảm thời gian nhưng giữ chi
tiết; thông số cuối phải lấy từ benchmark scene thật:
[Cycles sampling and denoising](https://docs.blender.org/manual/en/4.5/render/cycles/render_settings/sampling.html).

AgX và scene-linear tiếp tục được dùng. AgX xử lý dải sáng lớn và highlight tự nhiên hơn Standard;
texture data như normal/roughness phải được đánh dấu Non-Color:
[Blender color management](https://docs.blender.org/manual/en/4.1/render/color_management.html).

### 3.2. PBR asset library là nguồn tăng chất lượng chính

Principled BSDF của Blender dựa trên OpenPBR và nhận trực tiếp các texture channel tương ứng, vì vậy
không cần một shader framework riêng ở v1:
[Blender Principled BSDF](https://docs.blender.org/manual/en/4.0/render/shader_nodes/shader/principled.html).

Mỗi material asset phải có:

- `asset_id`, semantic compatibility và semantic version;
- kích thước vật lý/texel density;
- base color, roughness, normal; displacement chỉ khi thực sự cần;
- IOR/metallic hợp lý và giới hạn albedo;
- hash từng file, license, author/source và quyền dùng thương mại;
- renderer compatibility và memory class (`1K`, `2K`, `4K`);
- preview thumbnail và validation status.

Với GPU 6 GB, mặc định dùng texture 2K, 1K cho asset xa và chỉ 4K cho hero material thật sự cần.
Geometry Nodes/collection instances phải dùng cho cây, người, xe; không duplicate mesh/material theo
từng view.

Library không được hardcode vào một dự án. Design DNA chọn `asset_id` hoặc semantic collection;
renderer resolve theo versioned manifest.

### 3.3. Chỉnh nghĩa `LOCKED`, `BOUNDED`, `FREE`

Ba mức là policy ở object/surface level. Khi chiếu thành pixel mask:

- `LOCKED` là silhouette band, roof ridge, structural/opening edges, road/gate/fence/curb boundary và
  các critical object regions không được đổi;
- `BOUNDED` là interior của roof/facade/road/landscape surfaces, được đổi response vật liệu hoặc thêm
  chi tiết thuộc grammar nhưng không được vượt boundary;
- `FREE` là sky, atmosphere và context không authoritative.

Không khóa toàn bộ facade hay road pixel, vì như vậy không thể nâng vật liệu. Ngược lại, không chỉ
khóa đường biên silhouette: cửa, ridge, gate và các internal structural edges cũng phải có protected
edge bands.

Mask nên được sinh trực tiếp trong renderer từ semantic/object/material IDs. Cryptomatte/AOV hoặc
ID pass không qua color transform phù hợp hơn việc suy lại mask từ ảnh RGB. Blender Cryptomatte
được thiết kế để tạo matte theo object/material từ render pass:
[Blender Cryptomatte](https://docs.blender.org/manual/en/3.0/compositing/types/matte/cryptomatte.html).

### 3.4. Provider strategy

Tạo capability contract thay vì viết logic theo tên provider:

```text
supports_masked_edit
supports_control_image
supports_control_scale
supports_edit_strength
supports_seed
supports_multi_reference
supports_multi_turn_state
```

Phân vai đề xuất:

- **Gemini hiện tại:** candidate/global finish, style/material interpretation, human review;
- **Imagen masked editing:** local repair theo mask;
- **Imagen controlled/Canny hoặc ControlNet cloud worker:** benchmark spatial control;
- **PBR protected compositing:** fallback bắt buộc để bảo toàn hard regions.

Gemini documentation hỗ trợ image editing qua ảnh + natural-language instruction và multiple-image
composition, nhưng không cung cấp hard mask/control scale trong flow đang dùng:
[Gemini image generation/editing](https://ai.google.dev/gemini-api/docs/generate-content/image-generation).

Imagen hỗ trợ mask-based editing; controlled customization hỗ trợ Canny/scribble. Tuy nhiên chính
tài liệu Imagen cảnh báo một số kết hợp style-reference + composition-control nằm ngoài use case
được train và có thể cho chất lượng thấp. Vì vậy Imagen/ControlNet là **benchmark candidate**, không
được mặc định là lời giải production trước spike:
[Imagen mask editing](https://cloud.google.com/vertex-ai/generative-ai/docs/image/edit-images-overview),
[Imagen controlled customization](https://cloud.google.com/vertex-ai/generative-ai/docs/image/edit-controlled).

ControlNet là bằng chứng tốt rằng edge/depth/segmentation có thể trở thành model-level spatial
conditions, nhưng một ControlNet từng view vẫn chưa tự giải quyết multi-view consistency:
[ControlNet](https://arxiv.org/abs/2302.05543).

### 3.5. Shared appearance

Style anchor chỉ là giải pháp chuyển tiếp. Production cần giữ material state trong scene/texture
space rồi render mọi camera từ cùng state.

GenesisTex cho thấy texture-space sampling và dynamic alignment được thiết kế để giảm lỗi do sinh
tuần tự từng view. Tuy nhiên đây là hướng R&D/model pipeline, chưa nên nằm trong critical path v1:
[GenesisTex](https://arxiv.org/abs/2403.17782).

Thứ tự ưu tiên:

1. shared deterministic PBR materials;
2. hero material selection được ánh xạ lại thành material IDs/parameters;
3. dense reprojection QA;
4. chỉ nghiên cứu generative texture-space nếu ba bước trên chưa đủ.

## 4. Domain contract cần bổ sung

### 4.1. `AssetLibraryManifest`

```text
schema_version
library_version
assets[]
  asset_id, kind, semantic_roles, physical_dimensions
  files[], sha256[], license, source
  renderer_compatibility, memory_class
```

### 4.2. `MaterialAssignment`

```text
surface_id
material_asset_id
mapping_mode: uv | triplanar | world
real_world_scale_m
palette_tint
variation_seed
```

### 4.3. `ControlPolicy`

```text
preset: conservative | balanced | expressive
rules[]
  semantic_role
  topology_policy
  appearance_policy
  permitted_asset_collections
  max_variation
```

### 4.4. `ControlPackManifest`

```text
view_id, camera_hash, scene_hash, design_revision
locked_mask_ref, bounded_mask_ref, free_mask_ref
critical_edge_ref, silhouette_ref
semantic_id_ref, instance_id_ref, material_id_ref
metric_depth_ref, normal_ref, surface_id_ref
coverage + overlap validation
```

Ba top-level masks phải cùng resolution, không overlap và phủ toàn frame. Critical-edge mask là lớp
độc lập, có thể nằm trên vùng surface `BOUNDED` để khóa topology bên trong.

### 4.5. `RefinementRequest`

```text
source_image_ref
control_pack_ref
operation: global_finish | local_repair
editable_mask_ref
provider_capabilities_required[]
edit_strength/control_scale/seed nếu provider hỗ trợ
design_revision + prompt_version + candidate_index
```

Request phải fail trước khi gọi provider nếu capability không đáp ứng operation.

### 4.6. `CertificationReport`

Tách khỏi technical QA và chứa:

- state: `BASE_PBR`, `MARKETING_GENERATIVE_REVIEW`, `GEOMETRY_CERTIFIED`, `APPROVED_FINAL`;
- evidence cho từng gate;
- source/base/generated hashes;
- mask coverage và protected-composite evidence;
- reviewer, timestamp và decision reason khi human-approved.

## 5. QA khả thi và giới hạn

### 5.1. Hard evidence

Hard certification không nên phụ thuộc vào việc một vision model “nhìn” ảnh rồi đoán rằng geometry
đúng. Bằng chứng mạnh nhất là provenance của compositing:

1. locked pixel/edge bands lấy trực tiếp từ PBR source;
2. AI chỉ được ghi vào editable mask;
3. output compositor hash và mask hash được lưu;
4. post-composite kiểm tra pixel equality/edge preservation trong protected regions.

Đây là cách có thể cam kết mái, silhouette, road boundary, gate và opening không bị AI thay đổi.

### 5.2. Metric giai đoạn đầu

- protected-region pixel/edge preservation: bắt buộc tuyệt đối, trừ feather band định nghĩa trước;
- mask completeness/overlap: deterministic;
- palette compliance theo material/semantic region trong Lab/HSV;
- saturated forbidden-color leakage;
- camera coverage/occlusion từ instance/depth pass;
- object/semantic presence từ source scene và visibility manifest;
- duplicate/repetition heuristic cho entourage;
- highlight clipping, shadow/contact và noise statistics cho PBR.

### 5.3. Metric không được dùng một mình làm hard gate

- SSIM/LPIPS giữa PBR và AI output: ảnh tốt phải thay đổi texture/lighting nên similarity cao chưa
  chắc tốt;
- DINO/CLIP similarity: phù hợp ranking/identity aid, không chứng minh topology;
- VLM verdict: phù hợp gợi ý lỗi/human triage, không phải certification authority;
- raw cross-view RGB: góc chiếu, reflection và shadow khác nhau làm so sánh sai.

Dense cross-view metric phải reprojection theo camera + metric depth + surface ID, sau đó chuẩn hóa
lighting hoặc so material features thay vì pixel RGB thô.

### 5.4. Workflow rule bắt buộc

- `technical_qa=pass` nhưng `consistency=review` → `MARKETING_GENERATIVE_REVIEW`, không phải final.
- thiếu evidence ở hard gate → không được `GEOMETRY_CERTIFIED`.
- AI candidate fail → local repair tối đa hai lần; sau đó PBR fallback hoặc human review.
- chỉ `GEOMETRY_CERTIFIED` mới được đưa sang bước approval.
- chỉ `APPROVED_FINAL` mới được mặc định chọn làm video input hoặc deliverable package.

## 6. Benchmark protocol

### 6.1. Dataset

Giai đoạn readiness dùng bốn model hiện có làm **development set**, không dùng để công bố quality.
Bổ sung tối thiểu sáu model validation chưa dùng để tuning, đưa tổng pilot lên ít nhất 10.

Mỗi model cần ground-truth annotation tối thiểu:

- focus/context building IDs;
- roof assembly và ridge direction;
- road, gate, fence, parking, yard và landscape regions;
- facade/opening critical edges;
- camera role accept/reject;
- reviewer notes về các điểm không được thay đổi.

### 6.2. Thí nghiệm

Chạy cùng camera, Design DNA và seed policy:

| Variant | Nội dung |
|---|---|
| A | Eevee hiện tại + Gemini full-frame |
| B | Cycles PBR v1, không AI |
| C | Cycles PBR + Gemini global candidate + protected composite |
| D | C + local masked repair |
| E | Cycles PBR + controlled provider |

Không sinh ba candidate cho cả sáu view. Chỉ sinh tối đa ba candidate cho hero/material decision,
chọn một design state rồi truyền về shared scene. View còn lại mỗi view một candidate và chỉ repair
vùng fail.

### 6.3. Success criteria cho pilot

Các ngưỡng đầu tiên là hypothesis, hiệu chỉnh sau dev set:

- 0 critical topology change trong protected regions;
- 100% road/gate/fence/roof evidence đối với semantic đã được xác nhận;
- 6/6 camera role pass và không có major occlusion;
- không có material/palette identity conflict giữa các view;
- variant mới thắng A trong blind review về realism và bid appeal;
- không tăng tỷ lệ lỗi model/scene;
- chi phí/retry và thời gian/view-set được ghi đầy đủ.

Chấp nhận production chỉ dựa trên validation set, không dựa trên các model đã dùng tuning.

## 7. Kế hoạch triển khai đã làm rõ

### Milestone 0 — Certification foundation

**Ước lượng lập kế hoạch:** 5–8 engineering days.

- tạo schema cho asset manifest, control policy/pack và certification report;
- đổi workflow để `review` không được coi là final;
- render metric depth/surface/material IDs ổn định;
- sinh mask + critical edge bands;
- tạo benchmark CLI/report và frozen dev set;
- thêm certification state vào API/UI.

**Exit:** output hiện tại được gắn đúng `MARKETING_GENERATIVE_REVIEW`; không còn false-positive
“đã hoàn tất để bàn giao”.

### Milestone 1 — PBR v1

**Ước lượng lập kế hoạch:** 10–15 engineering/technical-art days.

- pin Blender 4.5 LTS image;
- thêm renderer profiles và GPU/CPU fallback;
- xây material resolver và asset manifest;
- tạo bộ material v1: roof/facade/glass/concrete/asphalt/curb/landscape;
- deterministic instancing cho vegetation, vehicle và people;
- benchmark VRAM/time/quality ở 1K và 2K.

**Exit:** B thắng base Eevee hiện tại trong blind review và mọi view dùng cùng material/asset IDs.

### Milestone 2 — Protected generative refinement

**Ước lượng lập kế hoạch:** 7–12 engineering days, chưa gồm thời gian xin Vertex access nếu cần.

- capability-aware provider interface;
- global candidate + protected compositor;
- masked local repair adapter;
- repair budget, caching và provenance;
- benchmark C/D/E.

**Exit:** D hoặc E tăng realism/bid appeal mà không gây critical topology change.

### Milestone 3 — Dense multi-view QA

**Ước lượng lập kế hoạch:** 10–20 engineering/R&D days.

- metric-depth unprojection/reprojection;
- visibility/occlusion handling;
- surface/material feature comparison;
- hero material state propagation;
- calibration trên validation set.

**Exit:** có evidence cross-view đủ ổn định để cấp `GEOMETRY_CERTIFIED` và hỗ trợ human approval.

Ước lượng trên là phạm vi để lập backlog, không phải deadline cam kết; thời gian asset authoring và
annotation phụ thuộc chất lượng nguồn dữ liệu.

## 8. Thứ tự công việc đề xuất ngay lập tức

1. Chốt schema `ControlPolicy`, `ControlPackManifest`, `AssetLibraryManifest` và
   `CertificationReport`.
2. Sửa workflow/UI để phân biệt `completed` với `certified/approved`.
3. Pin Blender 4.5 LTS và thêm profile renderer, nhưng giữ Eevee preview.
4. Tạo 5 material chuẩn đầu tiên: roof metal, facade metal, glass, concrete yard, asphalt.
5. Sinh material/surface IDs và protected masks từ renderer.
6. Xây compositor bảo vệ hard regions trước khi thay đổi Gemini flow.
7. Chạy benchmark A/B trên bốn dev model.
8. Chỉ sau khi B chứng minh tốt hơn mới triển khai provider D/E.

## 9. Quyết định Go/No-Go

**GO** cho Milestone 0 và 1 ngay.

**CONDITIONAL GO** cho Milestone 2 sau khi:

- control masks có coverage đúng;
- PBR v1 đủ tốt để làm fallback;
- có provider access phù hợp hoặc protected compositor đã pass.

**HOLD** Milestone 3 custom/texture-space R&D và fine-tuning cho đến khi benchmark D/E chứng minh
shared deterministic PBR vẫn chưa đạt yêu cầu.

## 10. Definition of Ready cho sprint triển khai đầu tiên

Sprint có thể bắt đầu khi:

- chấp nhận Blender 4.5 LTS + Cycles là renderer final v1;
- chỉ định người duyệt kiến trúc/thẩm mỹ cho blind review;
- xác nhận chính sách license của asset/material;
- chọn bốn model hiện có làm dev set và không dùng chúng làm validation set;
- chấp nhận nguyên tắc: thiếu hard evidence thì output chỉ là review, không phải certified;
- thống nhất rằng Gemini full-frame không được là nguồn geometry-authoritative.

