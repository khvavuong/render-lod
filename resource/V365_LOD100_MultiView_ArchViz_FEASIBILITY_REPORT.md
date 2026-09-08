# V365 LOD100 Multi-View ArchViz — Feasibility & Validation Report

**Ngày đánh giá:** 2026-09-08  
**Tài liệu được đánh giá:** `V365_LOD100_MultiView_ArchViz_REQUIREMENTS.md` v1.0  
**Mẫu kiểm nghiệm:** `model_lod100_sample.rvt`

## 1. Kết luận quyết định

**Có thể làm**, với điều kiện chia mục tiêu thành ba mức rõ ràng:

| Mức | Đánh giá | Điều có thể cam kết |
|---|---|---|
| Engineering spike trên 1 model | Khả thi cao | 4 camera render từ cùng một designed 3D scene; hard objects nhất quán tuyệt đối ở base render |
| Production pilot cho nhà xưởng | Khả thi có điều kiện | Ảnh marketing tốt, có QA và human review; không cam kết mọi ảnh AI tự động đạt ngay |
| Hệ thống tự động đạt toàn bộ acceptance target trong tài liệu | Chưa đủ bằng chứng | Cần benchmark, asset library, dữ liệu thật và có thể cần structural diffusion/custom model |

Kiến trúc cốt lõi trong requirements là đúng:

> Revit geometry → shared designed 3D scene → multi-camera passes → generative refinement → QA.

Điểm cần sửa không phải nguyên tắc kiến trúc mà là **phạm vi, thứ tự triển khai và mức cam kết**. Tài liệu hiện gộp spike, pilot, platform production và R&D model riêng thành một baseline; nếu xây đồng thời tất cả sẽ làm chậm việc kiểm chứng rủi ro quan trọng nhất.

## 2. Những gì đã kiểm nghiệm

### 2.1. File RVT sample

Kiểm tra không thay đổi file gốc cho thấy:

- file hợp lệ dạng Revit compound document;
- phiên bản lưu: **Revit 2026**;
- build: `20251103_1515(x64)`;
- worksharing không bật;
- tên dự án: `NHÀ XƯỞNG`;
- tổng diện tích trong Project Information: **66.080 m²**;
- file 2,1 MB;
- preview nhúng 128×128 cho thấy một master plan/campus gồm nhiều building mass;
- file có hai external references dạng bảng keynote/assembly code đang ở trạng thái not found; chúng không phải blocker cho spike hình học.

Kết luận: sample phù hợp để thử bài toán campus LOD100, nhưng thumbnail nhúng không đủ để xác định category, element count, kích thước, tọa độ hay surface identity. Muốn kiểm nghiệm geometry phải mở bằng Revit API hoặc đưa qua APS/exporter.

### 2.2. Khả năng dùng Gemini

Đã xác thực trực tiếp bằng API key hiện có:

- endpoint nhận diện `gemini-3.1-flash-image` / Nano Banana 2;
- generation 1K từ preview RVT thành công;
- thời gian quan sát của một request: khoảng **23 giây**;
- output: JPEG 1024×1024, khoảng 934 KB;
- interaction thử nghiệm đã được xoá khỏi Google sau khi kiểm tra.

Kết quả giữ được ý niệm tổng thể của campus nhưng tự sáng tác nhiều chi tiết kiến trúc và site. Đây là bằng chứng thực nghiệm ủng hộ quyết định dùng Gemini cho appearance/refinement, không dùng nó để bảo đảm footprint, opening count hay façade topology.

Lưu ý vận hành: Interactions API mặc định `store=true`. Production phải lựa chọn rõ giữa:

- `store=false` để giảm retention, nhưng không dùng được `previous_interaction_id`; hoặc
- stateful session và chấp nhận/configure retention sau data-governance review.

### 2.3. Kiểm nghiệm end-to-end sau khi có APS credentials

Vertical slice đã được triển khai và chạy thật trên sample local:

- APS OAuth và transient OSS bucket hoạt động;
- signed-S3 upload thành công cho RVT 2.166.784 bytes;
- Model Derivative dịch RVT 2026 → IFC2X3 thành công;
- IFC artifact khoảng 208 KB, source được pin bằng SHA-256;
- IfcOpenShell trích xuất 42 element, 7.164 vertex và 14.144 triangle;
- semantic baseline nhận 14 main shed, 15 office block, 5 service yard,
  5 utility block và 3 unknown;
- Design DNA R01 chứa 29 building/façade và grammar sinh 34 loading dock;
- Blender headless container render một shared scene qua 4 camera;
- mỗi view có RGB, clay, depth PNG/EXR, normal EXR, instance ID, semantic mask,
  edge và camera spec;
- Gemini Flash refinement pilot cho `view-01` thành công ở 1376×768.

Kết quả pilot AI có chất lượng marketing tốt và giữ bố cục campus ở mức tổng thể,
nhưng đã diễn giải lại mái, đường và cảnh quan. Vì vậy kết luận ban đầu được giữ nguyên:
base render là geometry-authoritative; output Gemini phải được gắn nhãn
`MARKETING_GENERATIVE` và qua reject/human-review gate.

Phần chưa kiểm nghiệm vẫn gồm Revit Automation fallback, AEC granular geometry,
cross-view metric trên nhiều model, protected compositing và benchmark 10–20 mẫu.

## 3. Đối chiếu các giả định nền tảng

### 3.1. Autodesk extraction

**Model Derivative phù hợp nhất để mở spike.** Autodesk xác nhận Revit 2023–2026 là nhóm major versions và RVT có thể được dịch sang SVF/SVF2/IFC. Sample Revit 2026 vì vậy nằm trong phạm vi hỗ trợ hiện tại.

Nguồn: [Revit Support Updates in Model Derivative API](https://aps.autodesk.com/blog/revit-support-updates-model-derivative-api)

**AEC Data Model không nên là dependency bắt buộc của pilot lúc này.** Element/property API đã GA, nhưng direct/granular geometry và Data Interoperability SDK vẫn được Autodesk mô tả là public beta. Nó nên tiếp tục tồn tại sau `IGeometryProvider`, nhưng chỉ bật sau khi có beta access và pass compatibility test trên model thật.

Nguồn: [Access Revit Geometry with AEC Data Model in Public Beta](https://aps.autodesk.com/blog/access-revit-geometry-aec-data-model-public-beta), [Autodesk DevCon 2026 update](https://aps.autodesk.com/blog/building-agentic-ai-whats-new-autodesk-platform-services)

**Revit Automation là fallback tốt**, đặc biệt khi cần Revit element identity hoặc export tùy chỉnh. Tuy nhiên AppBundle Revit 2026 sẽ chịu thay đổi runtime sang Revit 2026.5/.NET 10 ngày 2026-09-21, nên spike cần test compatibility theo thông báo Autodesk.

Nguồn: [Revit Automation 2026.5/.NET 10 migration notice](https://aps.autodesk.com/blog/revit-automation-engine-upgrading-revit-20265-and-net-10-september-21-2026)

**Khuyến nghị extraction cho spike:**

1. Upload local RVT vào APS Object Storage.
2. Model Derivative dịch RVT 2026 → IFC.
3. Parse IFC bằng IfcOpenShell thành canonical scene.
4. Giữ `GlobalId`, category/type, transform và mesh provenance.
5. Chỉ chuyển sang direct AEC geometry hoặc Revit Automation nếu fidelity/semantics không đạt.

IFC ở đây là artifact tạm của provider, không phải domain model. Canonical Scene vẫn là contract nội bộ; vì vậy không phá vỡ nguyên tắc provider abstraction.

### 3.2. Generative image layer

Tên model trong requirements là đúng tại ngày đánh giá. Google mô tả:

- `gemini-3.1-flash-image`: general-purpose, 0.5K/1K/2K/4K, nhiều reference;
- `gemini-3-pro-image`: production asset phức tạp;
- image API có giới hạn và không hứa tuân thủ tuyệt đối số lượng output/objects.

Nguồn: [Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation), [Gemini 3.1 Flash Image model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image)

Giá niêm yết tại ngày đánh giá cho Flash Image standard xấp xỉ $0.067/ảnh 1K, $0.101/ảnh 2K và $0.151/ảnh 4K, chưa gồm input/thinking và retries. Một view-set 4 ảnh thường rẻ ở riêng phần output, nhưng chi phí thực tế phải nhân với số lần repair/regenerate và các provider khác.

Nguồn: [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing)

### 3.3. Research foundation

Các paper chính trong requirements tồn tại và hỗ trợ hướng geometry/conditioning/correspondence:

- CAADRIA 2025 thực sự nghiên cứu shoebox architectural model và multi-view depth consistency;
- CAMEO, CVPR 2026, supervise attention bằng geometric correspondence;
- MVRoom và AnchoredDream củng cố luận điểm phải duy trì geometry/layout trong pipeline.

Tuy nhiên đây là **evidence cho hướng R&D**, không phải bằng chứng rằng có thể ghép các repo thành production system ngay. Phần lớn làm novel-view/indoor/object generation, domain và data distribution khác nhà xưởng Revit.

Nguồn: [CAADRIA 2025 paper](https://arxiv.org/abs/2503.03068), [CAMEO — CVPR 2026](https://openaccess.thecvf.com/content/CVPR2026/html/Kwon_Correspondence-Attention_Alignment_for_Multi-View_Diffusion_Models_CVPR_2026_paper.html), [MVRoom](https://arxiv.org/abs/2512.04248), [AnchoredDream](https://arxiv.org/abs/2601.16532)

## 4. Các điểm cần điều chỉnh trong requirements

### 4.1. Tách hard consistency khỏi photorealistic consistency

Shared 3D scene **bảo đảm base render nhất quán**, nhưng Gemini refinement có thể làm thay đổi silhouette/openings. Vì vậy không nên diễn đạt toàn pipeline như có “hard guarantee” nếu final pixel vẫn do image model sinh lại.

Nên có hai output class:

- `GEOMETRY_CERTIFIED`: PBR/hybrid render, AI chỉ sửa các vùng soft hoặc dùng compositing có mask bảo vệ hard geometry.
- `MARKETING_GENERATIVE`: đẹp hơn nhưng phải qua QA/human review và gắn confidence/provenance.

### 4.2. QA target đang quá sớm

Các target `silhouette IoU >= 0.97`, `automatic QA pass >= 90% after repair` và `hard opening mismatch = 0` chưa có benchmark chứng minh. Giữ chúng dưới dạng **hypothesis targets**, không dùng làm lịch cam kết trước khi chạy 10–20 model.

Đặc biệt:

- silhouette phải định nghĩa foreground/vegetation/occlusion policy;
- opening count detector cần labeled data hoặc deterministic protected masks;
- DINO/LPIPS/SSIM không tự phân biệt đúng thiết kế với cùng style;
- reflection, shadow và perspective làm pixel similarity sai lệch dù thiết kế đúng.

### 4.3. Auto-repair không nên là pilot gate ban đầu

Region inpainting có thể sửa artifact cục bộ, nhưng sửa opening/dock thường làm hỏng lân cận. Pilot đầu tiên nên:

1. detect/reject;
2. cho human chọn base render, regenerate hoặc local edit;
3. thu dữ liệu fail;
4. chỉ tự động repair loại lỗi đã đo được success rate.

### 4.4. Design grammar và asset library là phần việc lớn nhất

Không phải Temporal hay Gemini, mà asset library + procedural façade/site grammar quyết định chất lượng sản phẩm. Cần giới hạn grammar v1:

- rectangular/near-rectangular shed;
- flat/low-slope/gable roof;
- 1 office zone;
- modular metal panels;
- loading docks/rolling doors;
- road, parking, landscape dạng preset.

Các hình học ngoài profile này phải đi `needs_input` hoặc base-only, không cố auto-design.

### 4.5. Temporal/Kubernetes/PostgreSQL chưa cần cho spike

Giữ workflow/domain contract từ ngày đầu, nhưng spike có thể chạy bằng một CLI/job runner và filesystem artifacts. Temporal, PostgreSQL, S3 và Kubernetes chỉ kích hoạt khi vertical slice chứng minh geometry và visual quality. Điều này không tạo throw-away architecture nếu interfaces và manifest được giữ ổn định.

## 5. Kiến trúc thử nghiệm đề xuất

```text
RVT 2026 local
  → APS Model Derivative → IFC (temporary)
  → IfcOpenShell canonicalizer
  → canonical_scene.json + mesh buffers
  → manual semantic overrides for sample
  → manually approved Design DNA v0
  → Blender shared scene
  → 4 fixed cameras
  → PBR RGB + depth + normal + instance ID + edge
  → Gemini Flash image edit (one request/view, shared references)
  → geometry-protected compositing / reject gate
  → side-by-side human evaluation
```

Chưa đưa vào spike đầu:

- custom ControlNet training;
- auto semantic inference bằng LLM;
- Temporal cluster;
- Kubernetes GPU scheduling;
- automated region repair;
- AEC granular geometry beta;
- full concept-board product UI.

## 6. Kế hoạch kiểm nghiệm theo cổng quyết định

### Gate 0 — Input readiness (0,5–1 ngày)

Đầu vào cần có:

- APS app credentials và quyền upload/translate;
- xác nhận được phép gửi hình dự án sang Google;
- Blender LTS/headless trên dev machine hoặc container;
- một Design Brief thủ công cho sample.

Pass khi RVT version và permissions được resolve, không lộ secrets trong logs.

### Gate 1 — Geometry extraction (2–4 ngày)

Deliverables:

- Model Derivative job reproducible;
- IFC/CSP artifact tạm;
- element inventory, bounding boxes, units, transforms;
- viewer screenshot đối chiếu với canonical mesh.

Pass criteria:

- đúng số building mass chính;
- bounding box và vị trí không drift;
- element/source IDs trace được;
- không có linked model quan trọng bị thiếu.

Nếu IFC thất bại: chuyển Revit Automation exporter. Không chuyển sang parse SVF2 bằng format không chính thức.

### Gate 2 — Shared designed scene (4–7 ngày)

Deliverables:

- surface frames ổn định;
- manual semantic mapping;
- grammar v0 cho panel, office, dock, roof;
- 4 camera và conditioning pack.

Pass criteria:

- cùng một object ID xuất hiện đúng ở mọi camera nhìn thấy nó;
- render lại cho kết quả hình học/camera giống nhau;
- depth và instance ID khớp RGB.

Đây là go/no-go quan trọng nhất.

### Gate 3 — Generative refinement experiment (2–4 ngày)

Chạy ma trận nhỏ:

- 4 views;
- base PBR và Gemini Flash;
- 2 strategy: independent-with-shared-references và stateful sequence;
- ít nhất 3 repetitions/strategy.

Tổng tối thiểu: 24 ảnh để nhìn thấy variance, không kết luận từ một ảnh đẹp.

Chấm thủ công, không chỉ embedding:

- mass/roof/opening fidelity;
- vật liệu và accent giống nhau giữa views;
- visual quality;
- thời gian, token/cost, retry rate.

### Gate 4 — Pilot decision (1–2 ngày)

Quyết định theo kết quả:

- **Pass:** build pilot với geometry-protected hybrid workflow.
- **Conditional:** giữ PBR final cho hard regions, AI cho environment/material soft regions.
- **Fail:** không mở rộng orchestration; đầu tư ControlNet/domain dataset trước.

## 7. Ước lượng nguồn lực

Đây là range planning, chỉ chốt lại sau Gate 1:

| Chặng | Thời gian | Nhân sự tối thiểu |
|---|---:|---|
| Vertical spike 1 model | 2–3 tuần | 1 BIM/Revit engineer + 1 graphics/ML engineer |
| Internal demo ổn định 3–5 models | thêm 4–6 tuần | 2–3 engineers + architectural reviewer |
| Production pilot 10–20 models | tổng 10–14 tuần | 3–4 engineers + asset/architectural designer |
| Platform production + automated QA/repair | 4–6 tháng hoặc hơn | team đa chuyên môn; phụ thuộc benchmark |

Không nên cam kết Phase E/custom multi-view model trong timeline pilot. Đây là chương trình R&D riêng, chỉ khởi động khi có đủ dữ liệu và failure taxonomy.

## 8. Rủi ro và phương án xử lý ưu tiên

| Rủi ro | Mức | Hành động ngay |
|---|---|---|
| Direct AEC geometry còn beta | Cao | Model Derivative→IFC trước; giữ provider interface |
| Gemini đổi hard geometry | Critical | protected masks, reject gate, base-render fallback |
| RVT semantics nghèo/không chuẩn | Cao | manual override UI/JSON trước auto inference |
| Grammar scope phình to | Cao | typology whitelist v1 |
| QA metric cho false pass | Critical | human rubric + labeled benchmark |
| Model/API retention | Cao | `store=false` hoặc retention policy + DPA review |
| APS pricing thay đổi | Trung bình | log MB/job, translations/job, automation minutes |
| Revit 2026.5/.NET 10 migration | Trung bình | pin/test AppBundle nếu dùng Automation |

Autodesk đã công bố AEC Data Model pricing có hiệu lực từ 2026-10-06 và usage được đo theo Data In/Data Out; cần đưa telemetry chi phí vào ngay từ spike nếu thử provider này.

Nguồn: [AEC Data Model pricing announcement](https://aps.autodesk.com/blog/data-model-apis-included-subscriptions-plus-flexible-ways-scale), [usage reporting](https://aps.autodesk.com/blog/aec-data-model-api-updated-usage-reporting)

## 9. Tiêu chí Go / No-Go thực tế

### Go sang pilot khi

- sample RVT được extract đúng và trace được IDs;
- 4 base renders cùng một scene không sai hard objects;
- ít nhất một strategy AI đạt chất lượng chấp nhận được ở đa số repetitions;
- mọi AI failure hard-geometry được detector hoặc reviewer bắt;
- base PBR vẫn đủ tốt làm fallback;
- chi phí và latency/view-set được ghi nhận.

### No-Go hoặc đổi hướng khi

- extraction không bảo toàn mass/transform;
- scene grammar không thể biểu diễn sample mà phải hard-code theo view;
- Gemini thường xuyên làm sai mass/opening và protected compositing không cứu được;
- chỉ đạt consistency bằng regenerate không giới hạn;
- khách hàng yêu cầu pixel-final phải có độ chính xác kỹ thuật tương đương BIM.

## 10. Khuyến nghị cuối

Tiếp tục dự án, nhưng phê duyệt trước **vertical spike 2–3 tuần**, không phê duyệt ngay toàn bộ production architecture.

Thứ tự đầu tư đúng là:

1. extraction fidelity;
2. canonical scene + IDs;
3. industrial grammar + assets;
4. deterministic 4-view render;
5. Gemini refinement experiment;
6. benchmark/QA;
7. orchestration scale;
8. custom multi-view R&D nếu dữ liệu chứng minh cần thiết.

Nếu Gate 2 thành công, dự án đã giải quyết được phần khó nhất về consistency. Nếu Gate 3 chỉ đạt chất lượng trung bình, sản phẩm vẫn có đường lui khả thi: PBR/hybrid final với AI chỉ tác động lên các vùng mềm.
