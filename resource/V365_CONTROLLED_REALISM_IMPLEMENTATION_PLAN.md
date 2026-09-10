# V365 Controlled Realism — Kế hoạch cải thiện chất lượng diễn họa

**Phiên bản:** 1.1
**Ngày:** 2026-09-10  
**Trạng thái:** Revised direction — geometry-control-first / cloud beauty pilot
**Phạm vi:** Revit LOD100 → 6 ảnh diễn họa nhà xưởng công nghiệp đồng nhất, chân thực và có kiểm soát

## 1. Mục tiêu và quyết định kiến trúc

Mục tiêu của giai đoạn tiếp theo là làm cho bộ ảnh giống ảnh chụp công trình thực tế hơn, đồng thời
không đánh đổi độ đúng của model, giao thông nội bộ, mái, cổng, hàng rào, cảnh quan hoặc sự đồng
nhất giữa sáu góc nhìn.

Sau spike PBR ngày 2026-09-10, kiến trúc mục tiêu được sửa theo nguyên tắc:

> **Geometry-control-first, cloud beauty generation, protected compositing, evidence-based QA.**

Blender không còn phải dựng đủ asset để đạt 70–85% chất lượng ảnh cuối. Scene 3D dùng chung chịu
trách nhiệm cho camera, silhouette, mái, footprint, đường, cổng, hàng rào, landscape region và các
control pass. Cloud image model chịu trách nhiệm cho material appearance, vegetation/entourage
beauty, ánh sáng, atmosphere và photographic finish. AI vẫn không được là nguồn quyết định hình học
hoặc tự thiết kế lại công trình.

```text
RVT / IFC / Canonical Scene
        ↓
Semantic Scene + Design DNA
        ↓
Lightweight Control Scene + semantic placement
        ↓
Cheap Eevee guide render
        ↓
6 cameras + RGB/depth/normal/ID/semantic/control masks
        ↓
Cloud beauty: structure-controlled generation → local masked repair
        ↓
Geometry + semantic + cross-view + realism QA
        ↓
Human approval
        ↓
Certified Beauty View Set + Board + optional Video input
```

### 1.1. Vì sao thay đổi

Spike trên sample 4 chứng minh scene-linear, HDRI và PBR ground maps chỉ cải thiện cục bộ; phần lớn
pixel vẫn là roof/facade procedural, low-poly entourage và context massing nên ảnh vẫn có cảm giác
CGI. Tăng Cycles/sample không giải quyết chất lượng asset và có chi phí phần cứng lớn. Hướng mới giữ
phần 3D mà dự án đã làm tốt — đúng tỷ lệ, hình khối, camera và semantic — rồi thuê cloud model làm
phần beauty vốn đắt nhất nếu tự dựng.

### 1.2. Provider shortlist và chi phí tham chiếu

Giá tại thời điểm 2026-09-10, chưa gồm retry và input token rất nhỏ:

| Provider/path | Control phù hợp | Giá 1 ảnh | 6 ảnh | Vai trò đề xuất |
|---|---|---:|---:|---|
| Gemini 3.1 Flash Lite Image | edit/multi-reference, không có hard mask/control strength | $0.0336 | $0.2016 | preview/candidate giá thấp |
| Gemini 3.1 Flash Image | edit/multi-reference, không có hard structure control | $0.067 | $0.402 | hero/candidate với credential hiện có |
| Stability Control Structure | structure image + `control_strength` + seed | $0.05 | $0.30 | ứng viên mặc định cho six-view pilot |
| FLUX.2 Pro edit | multi-reference, photoreal edit | từ $0.045 | từ $0.27 | ứng viên style/realism challenger |
| Imagen 3 controlled customization | Canny/scribble control | $0.04 | $0.24 | benchmark khi có Vertex access |

Nguồn: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Stability API/pricing](https://platform.stability.ai/pricing),
[FLUX pricing](https://docs.bfl.ai/quick_start/pricing),
[Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing).

Imagen không được chọn mặc định chỉ vì rẻ: tài liệu của Google liệt kê việc kết hợp style reference
với composition control là use case không được tối ưu. FLUX hỗ trợ multi-reference tốt nhưng không
công bố structure-strength contract. Mọi provider vẫn phải qua protected compositor và QA; tên
`control` không đồng nghĩa geometry guarantee.

### 1.3. Routing tối ưu chi phí

1. Render control pack cho cả sáu view trên CPU/Eevee, chưa gọi AI.
2. Sinh một hero preview; chỉ sinh candidate thứ hai nếu người dùng từ chối candidate đầu.
3. Sau khi duyệt hero, khóa palette/material/lighting description vào Design DNA.
4. Sinh năm view còn lại bằng structure-controlled provider; không tạo ba candidate cho mỗi view.
5. Chỉ repair vùng fail, tối đa hai lần; không regenerate toàn bộ six-view set.
6. Upscale chỉ ảnh đã pass; video vẫn là thao tác riêng sau approval.

Ngân sách pilot điển hình: một hero Gemini Flash ($0.067) + năm view Structure ($0.25) + dự phòng
hai cloud repair ($0.10) = khoảng **$0.42/view-set**. Hai hero candidate đưa mức dự kiến lên khoảng
$0.49. Mask/composite local không phát sinh phí API; các con số chưa gồm upscale và retry ngoài
ngân sách dự phòng.

## 2. Kết quả đầu ra cần đạt

Mỗi design revision phải tạo được:

1. Sáu ảnh có vai trò camera khác nhau và cùng một ngôn ngữ thiết kế.
2. Một ảnh gộp sáu view đã qua cùng bộ color management và branding.
3. Conditioning pack đầy đủ cho từng view: RGB, depth, normal, edge, instance ID, semantic mask và
   các control mask.
4. Báo cáo QA có bằng chứng đo được, không chỉ kiểm tra file tồn tại.
5. Manifest ghi lại model hash, design revision, asset-library version, material IDs, camera specs,
   provider/model, prompt version, seed và lịch sử repair.
6. Control render fallback để review kỹ thuật khi AI không đạt gate; fallback này không được gọi là
   ảnh bàn giao.

Video tiếp tục sử dụng các ảnh đã được chứng nhận; giai đoạn này không thay đổi nguyên tắc tạo
video, nhưng không được đưa view lỗi hình học vào video pipeline.

Hai flow vận hành và tính chi phí độc lập:

- `ImageGenerationJob` kết thúc sau 6 ảnh, QA, board và branding; không bao giờ tự gọi Veo.
- `VideoGenerationJob` chỉ được tạo bởi thao tác xác nhận riêng của người dùng trên một image
  view-set đã hoàn tất. Flow này vẫn tạo đủ 6 shot, merge thành showreel không audio và chèn logo.
- Hai job có state, retry, idempotency key, artifact manifest và lỗi riêng. Retry ảnh không sinh lại
  video; retry video không sinh lại ảnh.

## 3. Các nguồn sự thật của hệ thống

Thứ tự ưu tiên bắt buộc:

1. **Canonical 3D Scene** — hình khối, vị trí, tỷ lệ và quan hệ không gian.
2. **Semantic Scene** — vai trò của building, roof, road, gate, fence, landscape, context và các
   vùng vận hành.
3. **Design DNA** — ngôn ngữ kiến trúc, palette, vật liệu, mức decor và các giới hạn thiết kế.
4. **Asset/Material Library** — tài sản thi công được, đúng tỷ lệ và có version.
5. **Generative provider** — hoàn thiện độ chân thực trong phạm vi control policy.

Ảnh tham khảo chỉ truyền đạt mức độ chân thực, image science và chất lượng hoàn thiện. Nó không phải
nguồn đúng cho footprint, camera, facade motif, bố cục hay một phong cách cố định áp dụng cho mọi dự
án.

`resource/sample_image_2.png` được đăng ký là **quality reference**, không phải
geometry/style reference. Các đặc tính được chuyển giao sang rubric gồm: phản ứng vật liệu không
phẳng, bóng tiếp xúc, chiều sâu khí quyển, dấu hiệu tỷ lệ thuyết phục và thứ bậc rõ giữa
công trình chính với context. Hồ nước, công viên, mật độ cây, hình khối xung quanh và
palette trong ảnh không được chuyển thành prompt/rule cứng cho nhà xưởng.

## 4. Creative Budget — sáng tạo có giới hạn

### 4.1. Ba lớp kiểm soát

| Lớp | Thành phần điển hình | Quyền của AI |
|---|---|---|
| `LOCKED` | Footprint, silhouette, số khối, trục/hướng mái, ridge, đường, cổng, hàng rào, curb, vị trí landscape, opening chính | Không được thêm, xóa, dịch chuyển hoặc đổi topology |
| `BOUNDED` | Vật liệu facade, panel rhythm, canopy, chi tiết sảnh, loại và mật độ cây, loading accessories | Chỉ chọn trong Design DNA, grammar và asset library đã duyệt |
| `FREE` | Trời, mây, atmospheric haze, color grade nhẹ, distant neutral context, người/xe nhỏ | Được sáng tạo nhưng không che công trình hoặc tạo thông tin địa điểm giả |

Policy phải tồn tại dưới dạng dữ liệu/mask, không chỉ là câu chữ trong prompt.

Khi chiếu policy thành pixel mask, `LOCKED` ưu tiên silhouette, boundary, ridge và các structural
edge bands; interior của facade/roof/road có thể là `BOUNDED` để vẫn cải thiện vật liệu. Không khóa
toàn bộ pixel bề mặt, nhưng cũng không được bỏ khóa cửa, cổng hoặc internal topology. Chi tiết triển
khai và đánh giá mức sẵn sàng được chốt trong
[`V365_CONTROLLED_REALISM_IMPLEMENTATION_READINESS_REPORT.md`](V365_CONTROLLED_REALISM_IMPLEMENTATION_READINESS_REPORT.md).

### 4.2. Preset cho người dùng

- `conservative`: giữ tối đa hình ảnh PBR; AI chủ yếu chỉnh ánh sáng và vi sai bề mặt.
- `balanced`: cho phép phát triển facade/cảnh quan trong Design DNA. Đây là preset mặc định.
- `expressive`: tăng lựa chọn thẩm mỹ trong vùng `BOUNDED`, nhưng không nới vùng `LOCKED`.

Tên preset không được làm thay đổi các nguyên tắc bắt buộc về hình học và công năng.

## 5. Thiết kế kỹ thuật mục tiêu

### 5.1. Semantic enrichment

Extraction phải chọn đúng một 3D view/site option trước khi canonicalize. Nếu IFC toàn model chứa
các `main_shed` chồng lấn trên 60% footprint, pipeline phải fail closed với trạng thái
`ambiguous_view_scope`; không được tự chọn khối lớn nhất hoặc dựa vào tên/tọa độ của project mẫu.
APS Model Derivative IFC chỉ là fallback cho model không có option chồng lấn. Luồng production cần
Revit Automation với `VisibleElementsOfCurrentView`/`ActiveViewId`, sau đó mới chạy semantic rules.

Canonical scene cần chuẩn hóa tối thiểu các semantic role:

- `primary_building`, `secondary_building`, `office`, `utility`;
- `roof`, `facade`, `glazing`, `loading_door`, `personnel_door`, `canopy`;
- `internal_road`, `external_road`, `yard`, `parking`, `curb`, `drainage`;
- `gate`, `fence`, `guardhouse`;
- `landscape`, `tree`, `shrub`;
- `context_building`, `context_ground`.

Không nhận diện chắc chắn thì đánh dấu `unknown`/`needs_review`; không tự gán chi tiết có thể làm sai
thiết kế. Rule nhận diện dựa trên geometry, metadata và quan hệ không gian, không dựa vào tọa độ của
một model mẫu.

### 5.2. Versioned PBR asset library

Library v1 tập trung vào nhà xưởng công nghiệp Việt Nam nhưng phải tái sử dụng theo rule:

- tôn mái/tường, ridge cap, flashing, gutter, downpipe và plinth;
- kính, khung nhôm, rolling/loading door và personnel door;
- asphalt, concrete yard, curb, drainage, marking và decal hao mòn nhẹ;
- 3–5 nhóm vegetation phù hợp khí hậu, nhiều biến thể hình học;
- xe tải, xe con và người đúng tỷ lệ;
- gate, fence, guardhouse và hạ tầng phụ trợ.

Mọi asset có real-world dimensions, material-space scale, LOD, license/provenance, version và semantic
compatibility. Scatter sử dụng seed theo `model_hash + design_revision`, nhờ đó cùng một cây hoặc xe
cố định xuất hiện tại cùng tọa độ trong mọi view.

Asset phải tách rõ hai mục đích:

- `conditioning_proxy`: geometry nhẹ để sinh depth/normal/semantic/ID và kiểm tra vị trí; không được
  xuất hiện nguyên trạng trong ảnh bàn giao;
- `delivery_beauty`: mesh/material đã qua visual QA, có texture/normal/roughness, LOD và provenance;
  chỉ lớp này được render vào beauty RGB final.

Không được gọi một asset low-poly/procedural là “PBR production” chỉ vì nó sử dụng Principled BSDF.
PBR shader đúng không bù được silhouette đơn giản, texture phẳng hoặc thiếu biến thiên tự nhiên.

### 5.3. Control renderer

- `preview_fast` dùng Eevee ở độ phân giải thấp để duyệt camera/layout.
- `standard_eevee` là đường control mặc định: guide RGB và các control pass. Nó không phải ảnh bàn
  giao và không yêu cầu GPU mạnh trên máy chủ điều phối.
- `premium_cycles` chỉ còn là công cụ chẩn đoán/benchmark tùy chọn, không nằm trong luồng mặc định.
- Scene-linear workflow và AgX/filmic color management.
- Một sun/sky rig, exposure family và white balance cho cả view-set để guide dễ hiểu.
- Material palette phải phân biệt rõ roof/facade/road/landscape và không tạo màu giả; không cần author
  toàn bộ photoreal texture library trước cloud pilot.
- Context xác thực phải lấy từ model hoặc `ContextPack` có provenance. Nếu không có dữ liệu địa điểm,
  dùng lớp procedural industrial-park theo tỷ lệ của site: mạng đường trục–nhánh nằm ngoài authored
  envelope, lô công nghiệp/low grass và các khối xưởng frosted-translucent trung tính. Cây chỉ nằm
  theo verge/hàng cây/setback; không tạo rừng. Toàn bộ lớp này là `FREE/non-authoritative`, trong khi
  vị trí/silhouette proxy xưởng là `BOUNDED`; không được gọi là context địa điểm thật.

### 5.4. Control pack

Ngoài conditioning pack hiện có, mỗi view cần thêm:

- `locked_mask`;
- `bounded_mask`;
- `free_mask`;
- mask riêng cho roof, road, gate/fence, landscape, facade và context;
- projected material/asset IDs;
- visible surface ID và correspondence map giữa các camera;
- base silhouette và protected edge map.
- `structure_guide` trung tính, bỏ màu xanh/CAD giả nhưng giữ shading và critical edges.

Ba control mask phải không chồng lấn ngoài policy cho phép và phủ toàn ảnh. Contract này độc lập với
Gemini, Imagen hay ControlNet để có thể benchmark/thay provider.

### 5.5. Hai lượt generative refinement

**Lượt 1 — structure-controlled photographic generation**

- Input là RGB guide hoặc edge control đã được chọn theo capability của provider.
- Control strength được version hóa và hiệu chỉnh theo camera role.
- Model tạo material response, vegetation/entourage beauty, bóng/khí quyển và độ tự nhiên.
- Không được thay đổi vùng `LOCKED`.

**Lượt 2 — local semantic repair**

- Chỉ chạy với vùng QA không đạt.
- Inpaint theo mask nhỏ nhất có thể.
- Mỗi lỗi tối đa hai lần repair.
- Sau mỗi lần phải chạy lại gate liên quan và cross-view gate.
- Không đạt sau giới hạn thì reject candidate và trả control render để review kỹ thuật; không giả
  vờ đó là ảnh bàn giao.

Không regenerate toàn frame chỉ vì một chi tiết cục bộ lỗi.

### 5.6. Multi-view appearance

Hero view được dùng để duyệt quyết định, không dùng như nguồn hình học. Sau khi duyệt, hệ thống ghi
palette, material family, lighting và decor thành dữ liệu Design DNA có version; không chỉ truyền
một ảnh style anchor mơ hồ.

Giải pháp production:

1. Sinh và duyệt một hero candidate.
2. Khóa material/lighting/decor description vào Design DNA.
3. Sinh năm view còn lại bằng cùng provider version, prompt template, control strength và seed
   family; từng view vẫn dùng structure guide riêng từ shared scene.
4. Chỉ sửa vùng occluded/unseen bằng local masked repair.
5. So sánh các surface ID cùng nhìn thấy bằng reprojection và human review.

## 6. QA và trạng thái chứng nhận

### 6.1. Các gate bắt buộc

| Gate | Kiểm tra | Hành động khi lỗi |
|---|---|---|
| Artifact | File, kích thước, checksum, provenance | Fail job |
| Geometry | Silhouette, protected edge, roof/ridge, footprint | Local repair hoặc technical fallback |
| Semantic | Building/road/landscape/context IoU, gate/fence recall | Reject/local repair |
| Material | Palette, material ID, color drift, semantic-color leakage | Local repair |
| Cross-view | Reprojection cùng surface, facade/material identity | Reject candidate/view-set |
| Camera | Coverage, occupancy, occlusion, vai trò camera | Re-plan camera trước generation |
| Realism | Contact shadow, material response, scale, repetition, atmosphere, CGI artifact | Rank/repair/human review |

Ngưỡng ban đầu là **hypothesis threshold**, phải hiệu chỉnh bằng benchmark. Không biến một con số chưa
được kiểm nghiệm thành cam kết sản phẩm.

### 6.2. Trạng thái output

- `BASE_PBR`: render an toàn, chưa qua generative refinement.
- `MARKETING_GENERATIVE_REVIEW`: ảnh AI đã sinh nhưng còn gate `review` hoặc thiếu evidence.
- `GEOMETRY_CERTIFIED`: toàn bộ hard gate có evidence và pass.
- `APPROVED_FINAL`: `GEOMETRY_CERTIFIED` và đã được người có thẩm quyền duyệt thẩm mỹ.

UI và API không được hiển thị “hoàn tất” như final nếu trạng thái chỉ là
`MARKETING_GENERATIVE_REVIEW`.

### 6.3. Human review rubric

Blind review chấm riêng theo thang 1–5:

1. Đúng model và tổ chức giao thông.
2. Đồng nhất thiết kế giữa sáu view.
3. Giống ảnh chụp thực tế.
4. Hợp lý/thi công được đối với nhà xưởng công nghiệp.
5. Sức thuyết phục trong hồ sơ đấu thầu.

VLM hoặc aesthetic model chỉ hỗ trợ xếp hạng candidate; không có quyền phê duyệt cuối.

## 7. Benchmark để chọn phương án

### 7.1. Ma trận thí nghiệm

| Mã | Pipeline | Mục đích |
|---|---|---|
| A | Control render + Gemini với toàn bộ pass như hiện tại | Baseline |
| B | Control render + Gemini minimal-input | Đo ảnh hưởng của việc bỏ reference gây nhiễu |
| C | Control render + Stability Structure | Ứng viên structure-control mặc định |
| D | Control render + FLUX.2 Pro + hero reference | Ứng viên realism/style consistency |
| E | Canny control + Imagen 3 | Benchmark khi có Vertex access |

Không chỉ thử trên một sample. Dataset pilot cần 10–20 RVT đại diện cho:

- một/nhiều khối;
- nhà xưởng dài, campus, office-attached;
- một, hai hoặc ba mặt tiền;
- bố cục mái và site access khác nhau;
- mức độ đầy đủ semantic khác nhau.

### 7.2. Chỉ số thu thập

- critical geometry failure rate;
- road/gate/fence/landscape recall;
- cross-view surface/material consistency;
- realism mean opinion score;
- bid-appeal score;
- tỷ lệ candidate pass ngay lần đầu;
- số lần local repair;
- thời gian và chi phí/view-set;
- tỷ lệ cần human correction.

### 7.3. Protocol dùng ảnh tham chiếu chất lượng

- Khóa file tham chiếu bằng path, checksum và vai trò `quality_only`; file
  `sample_image_2.png` hiện có SHA-256
  `43797e5fd2d452faf93e542d311d1557d34c8e9b8d6b1250236ea64ec1f30d0f`.
- Không đưa ảnh này vào conditioning như geometry/composition reference. Nếu provider nhận ảnh,
  block phải được gắn nhãn rõ `photographic finish only` và output vẫn qua protected
  compositor.
- Blind review hiển thị ảnh tham chiếu như mốc finish, nhưng chấm đúng model và khả năng
  thi công tách biệt với chân thực.
- Không chấm bằng pixel/CLIP similarity với ảnh tham khảo; các project khác nhau không được
  bị kéo về cùng bố cục hay palette.
- Control guide được review trước AI về camera, silhouette, mái, đường, cổng, hàng rào và semantic
  coverage. Guide không cần photorealistic, nhưng thiếu geometry/context có thẩm quyền thì không
  được dùng prompt để bịa phần còn thiếu.

Chỉ chọn provider production sau blind review cùng input/camera. Stability Structure là ứng viên
đầu tiên cần spike; Gemini minimal-input và FLUX.2 Pro là hai challenger.

## 8. Lộ trình triển khai theo cổng

### Phase 0 — Baseline và bộ đo

**Mục tiêu:** có baseline tái lập được trước khi thay chất lượng ảnh.

Deliverables:

- đóng băng một tập model/camera/reference output;
- script benchmark và manifest thống nhất;
- geometry/semantic/palette/camera gate có evidence;
- rubric và form blind review;
- dashboard/báo cáo so sánh A–E.

Exit criteria:

- một lần chạy có thể tái tạo đầy đủ artifact và metric;
- trạng thái thiếu evidence không được coi là pass;
- baseline A có số liệu thời gian, chi phí và lỗi.

### Phase 1 — Control-render foundation

**Mục tiêu:** guide render tự nó khóa đúng thiết kế, semantic và camera; không cần giả làm ảnh final.

Deliverables:

- material-ID/control palette library nhẹ;
- tách `conditioning_proxy` khỏi `delivery_beauty`; proxy không được lọt vào final RGB;
- HDRI/image-based lighting chỉ dùng cho ánh sáng và phản xạ khi không có ContextPack địa điểm;
- procedural detail cho mái, facade, road/site và landscape;
- deterministic scattering;
- standard Eevee control render; premium Cycles không nằm trên critical path;
- projected-bounds camera fitting và preflight trước mọi API call;
- render guide baseline trên dataset pilot.

Exit criteria:

- sáu view dùng đúng cùng asset/material IDs;
- road, gate, fence và landscape không phụ thuộc AI;
- control render đạt geometry/semantic/camera gate; không chấm nó như ảnh bàn giao;
- không còn low-poly tree/vehicle/person trong candidate được phép bàn giao;
- không có logic theo tên hoặc tọa độ model mẫu.

### Phase 2 — Cloud beauty pilot và bounded repair

**Mục tiêu:** AI tăng độ chân thực mà không được redesign.

Deliverables:

- control-mask contract;
- provider interface cho structure strength, mask, seed và reference role;
- benchmark Gemini minimal-input, Stability Structure và FLUX.2 Pro trên ba view đại diện;
- hero approval rồi mới tạo năm view còn lại;
- structure-controlled full-frame beauty pass và local masked repair;
- local repair và fail-closed fallback;
- benchmark C, D và E.

Exit criteria:

- vùng `LOCKED` vượt toàn bộ geometry gate;
- lỗi cục bộ không kích hoạt regenerate toàn frame;
- provider thắng phải đạt realism/bid appeal và không tăng critical geometry failure;
- chi phí median không vượt $0.70/view-set trước upscale.

### Phase 3 — Shared appearance và dense multi-view QA

**Mục tiêu:** cùng một surface có cùng material/appearance ở mọi camera.

Deliverables:

- surface correspondence map;
- shared UV/triplanar material state;
- reprojection validator;
- candidate propagation từ hero design về scene;
- view-set certification.

Exit criteria:

- các surface overlap đạt ngưỡng cross-view đã hiệu chỉnh;
- không còn phụ thuộc duy nhất vào VIEW-03 style anchor;
- rerender camera mới vẫn giữ design/material identity.

### Phase 4 — Production hardening

**Mục tiêu:** vận hành ổn định qua API/UI/worker.

Deliverables:

- queue, retry idempotent và provider fallback;
- asset/model/prompt version pinning;
- observability cho latency, cost, rejection và repair;
- UI hiển thị tiến độ từng gate và đúng certification state;
- retention/security policy cho model và ảnh dự án.

Exit criteria:

- job retry không tạo revision hoặc charge trùng ngoài policy;
- lỗi provider không làm mất artifact đã đạt;
- người dùng luôn phân biệt được preview, review và approved final.

## 9. Backlog ưu tiên

### P0

- Định nghĩa `ControlPolicy` và schema ba mask.
- Biến QA thiếu evidence thành fail/review rõ ràng.
- Xây baseline benchmark runner.
- Chuẩn hóa control-render color/edge/depth profile.
- Version hóa material và asset manifest.
- Thêm provider adapter có structure strength và benchmark ba view trước khi chạy đủ sáu.

### P1

- Giữ roof/facade/site geometry đủ tạo control pass; không author beauty asset tràn lan.
- Dùng deterministic proxy cho control pass và cấm proxy lọt vào final beauty RGB.
- Thêm geometry, semantic, palette và camera metrics.
- Mở rộng provider interface cho mask/edit strength.
- Thực hiện pipeline D trên ít nhất ba model khác hình dạng trước khi chạy toàn dataset.

### P2

- Surface correspondence và reprojection QA.
- Shared texture/material state.
- Controlled-provider benchmark.
- Candidate ranking và local repair policy.

### Không làm ngay

- Fine-tune/LoRA khi chưa có dataset ảnh đã duyệt.
- Custom multi-view diffusion trước khi chứng minh PBR + masked editing không đủ.
- Cho AI tự sinh context được gọi là “đúng địa điểm” khi không có ContextPack.
- Tối ưu theo riêng `model_lod100_sample*.rvt`.
- Dùng prompt dài hơn như giải pháp chính cho lỗi hình học.

## 10. Rủi ro và biện pháp kiểm soát

| Rủi ro | Biện pháp |
|---|---|
| LOD100 thiếu semantic | Confidence + `needs_review`, không đoán im lặng |
| AI thay mái/đường/cổng | Locked mask, geometry gate, technical fallback |
| Sáu view khác vật liệu | Shared material state + reprojection QA |
| Ảnh quá sạch kiểu CGI | PBR micro-detail, physical lighting, variation đúng tỷ lệ |
| Context đẹp nhưng sai địa điểm | ContextPack có provenance hoặc neutral context |
| Asset lặp và sai tỷ lệ | Versioned variants, real-world scale, deterministic scatter |
| QA tự động đánh giá sai thẩm mỹ | Tách hard gate khỏi ranking và giữ human approval |
| Chi phí tăng do regenerate | Hero candidate selection, local repair, giới hạn retry |

## 11. Definition of Done của chương trình cải thiện

Chương trình chỉ được coi là hoàn thành khi:

1. Pipeline chạy trên dataset đa dạng, không chứa rule riêng cho sample.
2. Hình học, mái, đường, cổng, hàng rào và landscape được giữ qua sáu view.
3. Material/facade identity của cùng một surface nhất quán giữa các camera.
4. Phương án mới thắng baseline có ý nghĩa trong blind review về realism và bid appeal.
5. Mọi hard gate có evidence; thiếu evidence không được pass.
6. Có technical fallback và provenance đầy đủ cho mọi output; fallback không được gắn nhãn final.
7. UI/API thể hiện đúng trạng thái chứng nhận.
8. Human reviewer có thể duyệt hoặc từ chối toàn view-set với lý do truy vết được.

## 12. Tài liệu và cơ sở nghiên cứu

- [Controlled Realism — implementation readiness](V365_CONTROLLED_REALISM_IMPLEMENTATION_READINESS_REPORT.md)
- [V365 Multi-view Realism — nghiên cứu và kiểm nghiệm](V365_MULTIVIEW_REALISM_RESEARCH_AND_EXPERIMENTS.md)
- [V365 feasibility report](V365_LOD100_MultiView_ArchViz_FEASIBILITY_REPORT.md)
- [ControlNet](https://arxiv.org/abs/2302.05543)
- [SyncDreamer](https://arxiv.org/abs/2309.03453)
- [CAMEO](https://arxiv.org/abs/2512.03045)
- [GenesisTex](https://arxiv.org/abs/2403.17782)
- [Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Vertex AI generative AI release notes](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes)
- [Unreal Engine Path Tracer](https://dev.epicgames.com/documentation/en-us/unreal-engine/path-tracer-in-unreal-engine)
