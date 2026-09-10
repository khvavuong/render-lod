# V365 Controlled Realism — Kế hoạch cải thiện chất lượng diễn họa

**Phiên bản:** 1.0  
**Ngày:** 2026-09-10  
**Trạng thái:** Approved direction / implementation baseline  
**Phạm vi:** Revit LOD100 → 6 ảnh diễn họa nhà xưởng công nghiệp đồng nhất, chân thực và có kiểm soát

## 1. Mục tiêu và quyết định kiến trúc

Mục tiêu của giai đoạn tiếp theo là làm cho bộ ảnh giống ảnh chụp công trình thực tế hơn, đồng thời
không đánh đổi độ đúng của model, giao thông nội bộ, mái, cổng, hàng rào, cảnh quan hoặc sự đồng
nhất giữa sáu góc nhìn.

Kiến trúc mục tiêu được chốt theo nguyên tắc:

> **PBR-first, shared-scene, mask-bounded generation, evidence-based QA.**

Ảnh PBR từ scene 3D dùng chung phải đạt khoảng 70–85% chất lượng cuối. AI chỉ đảm nhiệm phần hoàn
thiện hình ảnh còn lại trong phạm vi được phép; AI không được là nguồn quyết định hình học hoặc tự
thiết kế lại công trình.

```text
RVT / IFC / Canonical Scene
        ↓
Semantic Scene + Design DNA
        ↓
Procedural Detail + Versioned Asset Library
        ↓
Shared PBR Scene
        ↓
6 cameras + RGB/depth/normal/ID/semantic/control masks
        ↓
Bounded AI refinement: global low-strength → local masked repair
        ↓
Geometry + semantic + cross-view + realism QA
        ↓
Human approval
        ↓
Certified View Set + Board + Video inputs
```

## 2. Kết quả đầu ra cần đạt

Mỗi design revision phải tạo được:

1. Sáu ảnh có vai trò camera khác nhau và cùng một ngôn ngữ thiết kế.
2. Một ảnh gộp sáu view đã qua cùng bộ color management và branding.
3. Conditioning pack đầy đủ cho từng view: RGB, depth, normal, edge, instance ID, semantic mask và
   các control mask.
4. Báo cáo QA có bằng chứng đo được, không chỉ kiểm tra file tồn tại.
5. Manifest ghi lại model hash, design revision, asset-library version, material IDs, camera specs,
   provider/model, prompt version, seed và lịch sử repair.
6. Ảnh PBR fallback an toàn khi AI refinement không đạt gate.

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

## 4. Creative Budget — sáng tạo có giới hạn

### 4.1. Ba lớp kiểm soát

| Lớp | Thành phần điển hình | Quyền của AI |
|---|---|---|
| `LOCKED` | Footprint, silhouette, số khối, trục/hướng mái, ridge, đường, cổng, hàng rào, curb, vị trí landscape, opening chính | Không được thêm, xóa, dịch chuyển hoặc đổi topology |
| `BOUNDED` | Vật liệu facade, panel rhythm, canopy, chi tiết sảnh, loại và mật độ cây, loading accessories | Chỉ chọn trong Design DNA, grammar và asset library đã duyệt |
| `FREE` | Trời, mây, atmospheric haze, color grade nhẹ, distant neutral context, người/xe nhỏ | Được sáng tạo nhưng không che công trình hoặc tạo thông tin địa điểm giả |

Policy phải tồn tại dưới dạng dữ liệu/mask, không chỉ là câu chữ trong prompt.

### 4.2. Preset cho người dùng

- `conservative`: giữ tối đa hình ảnh PBR; AI chủ yếu chỉnh ánh sáng và vi sai bề mặt.
- `balanced`: cho phép phát triển facade/cảnh quan trong Design DNA. Đây là preset mặc định.
- `expressive`: tăng lựa chọn thẩm mỹ trong vùng `BOUNDED`, nhưng không nới vùng `LOCKED`.

Tên preset không được làm thay đổi các nguyên tắc bắt buộc về hình học và công năng.

## 5. Thiết kế kỹ thuật mục tiêu

### 5.1. Semantic enrichment

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

### 5.3. PBR renderer

- Preview dùng engine nhanh; final dùng Cycles hoặc path tracer tương đương.
- Scene-linear workflow và AgX/filmic color management.
- Một sun/sky rig, exposure family và white balance cho cả view-set.
- Vật liệu dùng albedo, roughness, normal/displacement đúng dải vật lý; tránh trắng cháy và màu phát
  sáng giả.
- Bắt buộc có contact shadow, atmospheric perspective và surface variation đúng tỷ lệ.
- Context xác thực phải lấy từ model hoặc `ContextPack` có provenance. Nếu không có dữ liệu địa điểm,
  chỉ dùng translucent massing/tree belt trung tính.

### 5.4. Control pack

Ngoài conditioning pack hiện có, mỗi view cần thêm:

- `locked_mask`;
- `bounded_mask`;
- `free_mask`;
- mask riêng cho roof, road, gate/fence, landscape, facade và context;
- projected material/asset IDs;
- visible surface ID và correspondence map giữa các camera;
- base silhouette và protected edge map.

Ba control mask phải không chồng lấn ngoài policy cho phép và phủ toàn ảnh. Contract này độc lập với
Gemini, Imagen hay ControlNet để có thể benchmark/thay provider.

### 5.5. Hai lượt generative refinement

**Lượt 1 — global photographic finish**

- Input là PBR RGB cùng control pack.
- Edit strength thấp.
- Chỉ điều chỉnh image science, vật liệu vi mô, bóng/khí quyển và độ tự nhiên.
- Không được thay đổi vùng `LOCKED`.

**Lượt 2 — local semantic repair**

- Chỉ chạy với vùng QA không đạt.
- Inpaint theo mask nhỏ nhất có thể.
- Mỗi lỗi tối đa hai lần repair.
- Sau mỗi lần phải chạy lại gate liên quan và cross-view gate.
- Không đạt sau giới hạn thì reject refinement và trả PBR fallback/human review.

Không regenerate toàn frame chỉ vì một chi tiết cục bộ lỗi.

### 5.6. Multi-view appearance

Giải pháp chuyển tiếp vẫn có thể dùng một hero view đã duyệt làm style reference, nhưng không coi
đó là consistency guarantee.

Giải pháp production:

1. Duyệt một hero design/material state.
2. Bake hoặc ánh xạ appearance về UV/triplanar/world-space của shared scene.
3. Render lại sáu camera từ material state chung.
4. Dùng AI theo view chỉ cho vùng occluded/unseen và photographic finish.
5. So sánh các surface ID cùng nhìn thấy bằng reprojection.

## 6. QA và trạng thái chứng nhận

### 6.1. Các gate bắt buộc

| Gate | Kiểm tra | Hành động khi lỗi |
|---|---|---|
| Artifact | File, kích thước, checksum, provenance | Fail job |
| Geometry | Silhouette, protected edge, roof/ridge, footprint | Local repair hoặc PBR fallback |
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
| A | Base hiện tại + AI full-frame | Baseline |
| B | PBR cải thiện, không AI | Đo đóng góp của renderer/asset |
| C | PBR + AI full-frame strength thấp | Đo rủi ro drift toàn ảnh |
| D | PBR + global low-strength + local masked repair | Phương án khuyến nghị |
| E | PBR + controlled provider/ControlNet/Imagen | So sánh mức spatial control |

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

Chỉ chọn phương án production sau blind review. Dự kiến D cho cân bằng tốt nhất; E là ứng viên thay
thế nếu controlled API đạt chất lượng và độ ổn định cao hơn.

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

### Phase 1 — PBR foundation (ưu tiên cao nhất)

**Mục tiêu:** base render tự nó đã rõ thiết kế và gần ảnh cuối.

Deliverables:

- material/asset library v1;
- procedural detail cho mái, facade, road/site và landscape;
- deterministic scattering;
- final render profile với scene-linear/AgX;
- render B trên dataset pilot.

Exit criteria:

- sáu view dùng đúng cùng asset/material IDs;
- road, gate, fence và landscape không phụ thuộc AI;
- blind review xác nhận PBR tốt hơn baseline clay;
- không có logic theo tên hoặc tọa độ model mẫu.

### Phase 2 — Bounded generative refinement

**Mục tiêu:** AI tăng độ chân thực mà không được redesign.

Deliverables:

- control-mask contract;
- provider capability interface cho mask, edit strength và reference role;
- hai lượt refinement;
- local repair và fail-closed fallback;
- benchmark C, D và E.

Exit criteria:

- vùng `LOCKED` vượt toàn bộ geometry gate;
- lỗi cục bộ không kích hoạt regenerate toàn frame;
- D hoặc E thắng B về realism/bid appeal mà không tăng critical geometry failure.

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
- Chuẩn hóa final PBR color/lighting profile.
- Version hóa material và asset manifest.

### P1

- Bổ sung roof/facade/site procedural detail.
- Xây deterministic vegetation/vehicle/people scattering.
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
| AI thay mái/đường/cổng | Locked mask, geometry gate, PBR fallback |
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
6. Có PBR fallback và provenance đầy đủ cho mọi output.
7. UI/API thể hiện đúng trạng thái chứng nhận.
8. Human reviewer có thể duyệt hoặc từ chối toàn view-set với lý do truy vết được.

## 12. Tài liệu và cơ sở nghiên cứu

- [V365 Multi-view Realism — nghiên cứu và kiểm nghiệm](V365_MULTIVIEW_REALISM_RESEARCH_AND_EXPERIMENTS.md)
- [V365 feasibility report](V365_LOD100_MultiView_ArchViz_FEASIBILITY_REPORT.md)
- [ControlNet](https://arxiv.org/abs/2302.05543)
- [SyncDreamer](https://arxiv.org/abs/2309.03453)
- [CAMEO](https://arxiv.org/abs/2512.03045)
- [GenesisTex](https://arxiv.org/abs/2403.17782)
- [Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Vertex AI generative AI release notes](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/release-notes)
- [Unreal Engine Path Tracer](https://dev.epicgames.com/documentation/en-us/unreal-engine/path-tracer-in-unreal-engine)
