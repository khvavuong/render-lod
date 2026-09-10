# V365 Controlled Realism — Implementation Readiness Report

**Ngày đánh giá:** 2026-09-10  
**Kế hoạch nguồn:** `V365_CONTROLLED_REALISM_IMPLEMENTATION_PLAN.md` v1.1
**Mục đích:** xác nhận mức sẵn sàng, chốt quyết định kỹ thuật và định nghĩa gói công việc đầu tiên

## 1. Kết luận

Hướng `shared-scene + mask-bounded generation + evidence-based QA` vẫn đúng, nhưng spike đã bác bỏ
giả định rằng team nên tự nâng Blender/PBR thành nguồn beauty chính. Hướng mới là
`geometry-control-first + cloud beauty`; hệ thống hiện tại **chưa đủ điều kiện chứng nhận output để
bàn giao tự động**.

Điểm mạnh hiện có:

- canonical geometry, Design DNA, sáu camera và shared Blender scene đã hoạt động;
- đã có RGB, depth, normal, edge, semantic và instance passes;
- có immutable revision, manifest, technical artifact QA và human-review placeholder;
- Gemini style-anchor cải thiện độ đồng nhất hơn generation độc lập;
- bốn model khác nhau đã được canonicalize và dùng làm dữ liệu phát triển ban đầu.

Các blocker hiện tại trước khi gọi output là `APPROVED_FINAL`:

1. PBR hiện tại mới có foundation cho HDRI và một số surface map; phần lớn mái/facade, vegetation,
   vehicle/person và context vẫn là procedural proxy, chưa phải delivery asset library.
2. Control-mask contract đã có nhưng Gemini adapter hiện tại không thực thi mask/control strength
   cứng; chưa tích hợp structure-controlled provider.
3. Correspondence mới là object-level visibility, chưa có dense pixel reprojection.
4. Geometry/material/camera đã có evidence từng phần; realism và aesthetic vẫn cần calibrated blind
   review thay vì tự động pass.
5. Chưa có A/B/C bake-off trên cùng ba view để chứng minh provider nào đạt cân bằng
   realism–accuracy–cost tốt nhất.

Quyết định triển khai sửa đổi: **dừng mở rộng production asset library đại trà, giữ Blender làm
control renderer, chạy provider bake-off trên ba view trước.** Không xây custom diffusion hoặc
texture-space model. Mốc tiếp theo là chứng minh một cloud provider có thể nâng photographic realism
nhưng vẫn vượt geometry/semantic gates.

## 2. Bằng chứng từ repository

### 2.1. Renderer

`scripts/blender/render_conditioning.py` hiện:

- đã đọc asset manifest, kiểm tra checksum và hỗ trợ albedo/roughness/normal map cho các bề mặt site;
- đã có HDRI CC0 1K và material-scale metadata; mái/facade chủ yếu vẫn là procedural material;
- chưa có delivery-grade decal, instanced vegetation, vehicle/person hoặc facade asset library;
- luôn chọn `BLENDER_EEVEE_NEXT`/`BLENDER_EEVEE`;
- render mặc định 768×432;
- đã dùng HDRI/Nishita fallback và AgX, đủ làm control renderer;
- tự dựng mái/facade detail bằng procedural boxes, phù hợp prototype nhưng chưa đạt construction
  detail và phản ứng vật liệu cần cho final beauty.

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

Cycles + OptiX là profile `premium_cycles` tùy chọn, không phải điều kiện bắt buộc của máy chủ chính.
Blender xác nhận OptiX hỗ trợ RTX trên Linux và GPU rendering có thể nhanh hơn, nhưng bị giới hạn
bởi VRAM:
[Cycles GPU rendering](https://docs.blender.org/manual/en/4.5/render/cycles/gpu_rendering.html).

Khởi điểm benchmark, chưa phải ngưỡng cố định:

| Profile | Engine | Resolution | Sampling | Denoising | Mục đích |
|---|---|---:|---|---|---|
| `preview_fast` | Eevee | 768×432 | N/A | N/A | camera/layout preview |
| `standard_eevee` | Eevee | 1024×576 | calibrated TAA | N/A | mặc định: control render + cloud beauty |
| `premium_cycles` | Cycles GPU | 2048×1152 | adaptive, max 128 | OIDN, albedo+normal | hero view/QA fallback theo yêu cầu |

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
- AI candidate fail → local repair tối đa hai lần; sau đó technical fallback hoặc human review.
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
| A | Control render + Gemini với RGB/depth/instance/semantic/edge như hiện tại |
| B | Control render + Gemini minimal-input: RGB guide + edge + prompt |
| C | Control render + Stability Structure với `control_strength` đã định |
| D | Control render + FLUX.2 Pro với hero/material reference |
| E | Canny control + Imagen 3 khi có Vertex access |

Không sinh ba candidate cho cả sáu view. Chỉ sinh candidate thứ hai cho hero khi candidate đầu bị
từ chối; sau khi khóa Design DNA, năm view còn lại mỗi view một candidate và chỉ repair vùng fail.

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

### Milestone 1 — Control renderer v1

**Ước lượng lập kế hoạch:** 3–5 engineering days.

- pin Blender 4.5 LTS image;
- dùng `standard_eevee` để sinh RGB guide, depth, normal, edge, semantic và ID; Cycles không nằm
  trên critical path;
- fit camera theo projected bounds thay cho hệ số khoảng cách cố định;
- deterministic proxy cho semantic/control pass nhưng không cho phép proxy vào final beauty;
- benchmark CPU time, camera coverage và control fidelity ở 1K.

**Exit:** 6/6 view không crop critical site/building, control pack tái lập được và không phụ thuộc
model mẫu.

### Milestone 2 — Cloud beauty bake-off và protected refinement

**Ước lượng lập kế hoạch:** 5–8 engineering days, chưa gồm thời gian cấp credential provider.

- capability-aware provider interface;
- benchmark cùng ba view đại diện: Gemini minimal-input, Stability Structure và FLUX.2 Pro;
- một hoặc hai hero candidate trước, chỉ gọi năm view còn lại khi hero được duyệt;
- structure-controlled candidate + protected compositor;
- masked local repair adapter;
- repair budget, caching và provenance;
- ghi chi phí ở cấp request và view-set.

**Exit:** provider thắng tăng realism/bid appeal, không gây critical topology change và typical
cost không vượt 0,60 USD/view-set trước upscale.

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
- control renderer đủ rõ để làm technical fallback và sinh control pass ổn định;
- có provider access phù hợp hoặc protected compositor đã pass.

**HOLD** Milestone 3 custom/texture-space R&D và fine-tuning cho đến khi benchmark D/E chứng minh
shared deterministic PBR vẫn chưa đạt yêu cầu.

## 10. Definition of Ready cho sprint triển khai đầu tiên

Sprint có thể bắt đầu khi:

- chấp nhận Blender 4.5 LTS + Eevee bounded pipeline là standard v1; Cycles là premium tùy chọn;
- chỉ định người duyệt kiến trúc/thẩm mỹ cho blind review;
- xác nhận chính sách license của asset/material;
- chọn bốn model hiện có làm dev set và không dùng chúng làm validation set;
- chấp nhận nguyên tắc: thiếu hard evidence thì output chỉ là review, không phải certified;
- thống nhất rằng Gemini full-frame không được là nguồn geometry-authoritative.

## 11. Trạng thái triển khai hiện tại

Các hạng mục foundation đã được triển khai sau lần đánh giá readiness:

- có domain contract và JSON Schema cho `ControlPolicy`, `ControlPackManifest`,
  `AssetLibraryManifest` và `CertificationReport`;
- Blender sinh `control_policy.png`; application layer tạo ba mask `locked/bounded/free` thành một
  partition phủ kín, không overlap;
- structural-edge band được đưa vào `locked_mask`; ngưỡng Sobel đã được spike bằng render thật để
  tránh khóa cả bề mặt cần nâng vật liệu. Trên sáu view dev đã kiểm tra, locked coverage nằm trong
  khoảng 0,9–9,5% tùy góc nhìn sau hiệu chỉnh; đây vẫn là hypothesis cần validation thêm;
- mọi ảnh AI trong API worker đi qua protected compositor trước QA; manifest lưu hash của base RGB,
  mask, provider source và protected output;
- provider capability contract được ghi vào generation manifest; Gemini hiện khai báo rõ chỉ hỗ
  trợ multi-reference trong integration này, không khai báo masked edit/control scale/edit strength
  hay seed nên không thể tự cấp hard-geometry evidence;
- API/UI trả certification state độc lập với workflow state;
- có `preview_fast`, `standard_eevee` mặc định và `premium_cycles` tùy chọn; premium yêu cầu GPU
  worker riêng, máy chủ điều phối không phải có RTX;
- có asset-library manifest/resolver cho 18 nhóm vật liệu procedural nền (roof, facade,
  office, glass, coated metal, loading door, panel seam, concrete, asphalt, authored landscape và
  muted context ground, vegetation và entourage) cùng material-ID pass; cùng asset ID được
  dùng qua mọi camera, không phát sinh texture-memory;
- pass instance/semantic/material/control đã được tách khỏi look tương phản và dùng
  `Standard/None`, tránh làm biến đổi byte ID trước khi QA giải mã; mỗi semantic pass có manifest
  màu đi kèm;
- có camera preflight trước bước gọi provider trả phí: đo focus/circulation/context coverage theo
  từng camera role từ semantic-ID pass và fail sớm nếu chủ thể bị quá nhỏ, crop nặng hoặc mất phần
  giao thông đã authored. Spike thật trên sáu view của sample 4 đạt focus coverage 9,8–58,4% và
  circulation coverage 2,9–23,2%; các threshold hiện vẫn là benchmark hypothesis;
- `standard_eevee` 1024×576 đã render headless thành công trên một dev view không truyền GPU. Lần
  đo này chỉ xác nhận khả năng chạy, chưa phải benchmark chất lượng toàn dataset.

Cập nhật theo spike vật liệu và `sample_image_2.png`:

- manifest hiện có 24 asset: 19 material, một HDRI environment và bốn geometry proxy cho cây,
  xe con, xe dịch vụ và người; asphalt/concrete/sidewalk đã có map 1K, các material còn lại vẫn
  procedural; schema hỗ trợ real-world dimensions, transmission, IOR và clear coat;
- renderer đã có deterministic entourage: cây chỉ sample bên trong triangle của
  `landscape_zone`, xe con bám `parking`, xe dịch vụ chỉ bám loading dock đã authored, người
  chỉ bám office entrance. Manifest lưu vị trí/kích thước/asset ID và seed theo design revision,
  nên sáu camera không sinh entourage khác nhau;
- Blender 4.0.2 headless đã render thành công view có office entrance, xác nhận material resolver
  tương thích socket shader hiện tại. Artifact:
  `.artifacts/spikes/pbr-materials-480-v2/view-03/base_rgb.png`;
- kết quả spike cũng cho thấy **chưa đạt mức bàn giao**: facade còn quá trắng/phẳng,
  cụm kính/nhấn màu còn mang cảm giác CGI, thiếu phản xạ context, tiếp xúc với nền và
  scale cue. Đây là bằng chứng để ưu tiên asset/lighting/entourage, không phải lý do
  nới AI;
- `sample_image_2.png` được phân loại `quality_only`: dùng để calibrate surface response,
  contact shadow, atmospheric depth, scale cue và project/context hierarchy. Không sao chép hồ,
  công viên, hình khối, palette hoặc bố cục sang project khác.

Các blocker còn lại trước `GEOMETRY_CERTIFIED`:

1. camera coverage và protected geometry/palette đã có evidence ban đầu; semantic fidelity của ảnh
   refined, dense silhouette reprojection và cross-view material identity vẫn chưa đủ evidence để
   chuyển toàn bộ visual gate từ `review` sang `pass`;
2. material library và entourage geometry đã có foundation nhưng chưa đạt photographic
   calibration; HDRI reflection và ba ground material chỉ mới là spike, còn thiếu roof/facade map,
   vegetation/vehicle/person variant chất lượng final, site furniture, asset LOD và provenance
   production cho toàn bộ beauty layer;
3. Gemini vẫn là full-frame candidate provider; Stability Control Structure adapter đã có nhưng
   chưa thể chạy thật khi chưa cấu hình `STABILITY_API_KEY`;
4. chưa có dense surface reprojection và benchmark/blind review trên validation set độc lập;
5. Blender container production vẫn cần pin 4.5 LTS exact digest thay cho package 4.0.2 hiện tại.

## 12. Kết quả spike photographic baseline — 2026-09-10

Đã chạy ba bước tách biệt trên cùng model/camera để tránh đánh giá cảm tính:

1. sửa HEX sRGB sang scene-linear;
2. thêm HDRI sân công nghiệp làm image-based lighting nhưng không dùng ảnh nền của HDRI làm context;
3. thêm CC0 1K albedo/roughness/OpenGL-normal cho asphalt, concrete yard và sidewalk, sau đó
   điều chỉnh camera overall theo site envelope.

Artifact so sánh:

- baseline sau sửa màu: `.artifacts/spikes/linear-color-c4ce-v1/view-01/base_rgb.png`;
- PBR map/HDRI với overall framing mới:
  `.artifacts/spikes/pbr-texture-hdri-c4ce-v3/view-01/base_rgb.png`.

Kết luận: framing mới giúp đọc khối chính và site tốt hơn, ground map/HDRI tăng phản ứng bề mặt ở
cự ly gần, nhưng **visual exit của Milestone 1 vẫn fail**. Khoảng cách lớn nhất còn nằm ở bốn lớp:

- mái/facade procedural chiếm phần lớn pixel nên vẫn phẳng và quá sạch;
- cây, xe và người là low-poly conditioning proxy nhưng đang xuất hiện trong beauty RGB;
- context chỉ có ground plane và translucent massing, thiếu road network, tree belt và atmospheric
  depth có provenance;
- camera được tạo bằng hệ số envelope, chưa có projected-bounds fitting và composition score.

Quyết định sau spike:

- không tăng render samples/Cycles để che các blocker asset;
- giữ Eevee làm standard profile nhẹ phần cứng;
- giữ asset ingestion ở mức đủ tạo control render rõ semantic, không mở rộng thành full beauty farm;
- chỉ chạy AI sau camera/conditioning preflight; cloud beauty không được dùng để thay đổi geometry;
- thêm gate `realism`; `APPROVED_FINAL` bắt buộc cả realism và aesthetic có evidence pass cùng reviewer.

Nguồn asset spike: Poly Haven CC0 — `overcast_industrial_courtyard`, `asphalt_floor`,
`hangar_concrete_floor`, `concrete_pavement_02`. Manifest lưu source, license, file path và SHA-256;
tổng dung lượng 1K foundation khoảng 10 MB, phù hợp server không có GPU mạnh.

## 13. Kết quả bake-off Gemini trên sample 4 — 2026-09-10

Đã chạy cùng camera v12, Design DNA và reference policy trên `view-01`, `view-03`, `view-06`:

| Variant | Thời gian | Edge gate | Nhận xét visual |
|---|---:|---:|---|
| Gemini full pass | ~42 giây/3 ảnh | 0/3 pass | decor/entourage tốt hơn nhưng lệch structural edges |
| Gemini minimal RGB + edge | ~58 giây/3 ảnh | 2/3 pass | bám hình tốt hơn, vẫn mang cảm giác CGI; hero fail |
| Gemini full + industrial reference | ~20 giây/1 hero | 0/1 pass | đổi facade/decor nhưng không nâng photographic realism đủ mức |

Artifact đánh giá:

- `.artifacts/experiments/controlled-realism-c4ce-v1/gemini-full-board.jpg`;
- `.artifacts/experiments/controlled-realism-c4ce-v1/gemini-minimal-board.jpg`;
- `.artifacts/experiments/controlled-realism-c4ce-v1/gemini-industrial-reference/view-03/provider_source.jpg`.

Kết luận tạm thời: reference selection không phải nút thắt chính. Gemini hiện phù hợp candidate/hero
exploration nhưng chưa đủ để vừa đạt photo realism vừa vượt geometry gate. Dừng retry Gemini trên
sample này; bước kế tiếp là chạy đúng ba view qua Stability Control Structure tại các mức control
strength được version hóa, rồi blind review cùng output trên.

## 14. Spike industrial-park context và view-scope — 2026-09-10

Đối chiếu ảnh khu công nghiệp mới cho thấy context đúng phải được đọc bằng mạng đường trục–nhánh,
lô công nghiệp, hạ tầng tuyến và mật độ xưởng có tổ chức; cây xanh là lớp phụ, không phải continuous
canopy. Đã thay ground xanh phẳng bằng ground trung tính, thêm mạng đường context sinh theo site
envelope và giữ các xưởng lân cận là frosted-translucent proxy có ground contact. Đây là thuật toán
theo tỷ lệ scene, không chứa tọa độ hoặc tên project mẫu.

Semantic extraction trên sample 4 phát hiện hai lỗi cụ thể đã được sửa bằng rule dùng metadata:

- `SITEOPT - Cổng ra vào` trước đây là `unknown`, nay là `main_entrance`;
- `Sân xe lấy hàng` trước đây là `unknown`, nay là `loading_zone`.

Control renderer tạo cột/header cổng ngay trong bounding box của entrance authored và khóa semantic
cổng. Bộ six-view mới pass conditioning QA. Artifact:

- `.artifacts/experiments/controlled-realism-c4ce-v2/control-board-industrial-context.jpg`;
- `.artifacts/experiments/controlled-realism-c4ce-v2/structure-guide-industrial-context.jpg`.

Hai prototype cloud-beauty chứng minh context industrial park và photographic material có thể tăng
rõ rệt. Prototype mới nhất:
`.artifacts/experiments/controlled-realism-c4ce-v2/view-01-industrial-context-v2.png`.
Tuy vậy edge-alignment recall chỉ đạt `0.4784`, thấp hơn gate `0.75`, nên **không được chứng nhận
bàn giao**. AI vẫn tự mở rộng một số đường/context; prompt-only không đủ để bảo toàn hình học.

Một blocker extraction cũng được xác nhận: APS Model Derivative xuất IFC toàn model, không xuất theo
specific Revit view. Sample 4 vì vậy chứa 228 phần tử, 5 main shed và 8 entrance thuộc các option
chồng lấn. Provider nay fail closed khi main-shed footprint overlap từ 60%; production cần
view-scoped IFC qua Revit Automation. Bản scene 42 phần tử dùng trong spike được phục hồi từ six-view
visibility evidence đã duyệt và có provenance riêng; đây là cầu nối thử nghiệm, không phải chiến
lược chọn option production.
