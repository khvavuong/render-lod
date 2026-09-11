# V365 Controlled Realism — Kế hoạch triển khai Photoreal Balanced

**Phiên bản:** 2.0

**Ngày:** 2026-09-11

**Trạng thái:** Implementation baseline

**Phạm vi:** Revit LOD100 → 6 ảnh diễn họa nhà xưởng công nghiệp đồng nhất, chân thật và có kiểm soát

## 1. Quyết định kiến trúc

Pipeline chọn hướng **Photoreal Balanced** với nguyên tắc:

> **Tự do sáng tạo ở lượt sinh ảnh, kiểm soát hình học ở dữ liệu đầu vào và các cổng QA.**

Gemini không còn phải đồng thời diễn giải RGB, depth, instance ID, semantic ID, edge và nhiều ảnh
tham khảo trong một request. Mỗi lượt sinh beauty chỉ nhận một bộ ảnh sạch, có thứ tự thẩm quyền rõ
ràng. Các pass kỹ thuật vẫn được dựng đầy đủ nhưng dùng để kiểm định, từ chối và sửa cục bộ output.

Mục tiêu của thay đổi này là đạt đồng thời hai yêu cầu:

1. Giữ đúng camera, số lượng khối, tỷ lệ, footprint, hướng mái, đường, cổng, hàng rào, cảnh quan và
   quan hệ không gian từ model.
2. Cho model ảnh đủ không gian để tạo vật liệu, ánh sáng, chi tiết thi công, môi trường và image
   science giống ảnh chụp thực tế.

```text
RVT / IFC / selected 3D view
        ↓
Canonical Scene + Semantic Scene + Design DNA
        ↓
6 cameras + clean Base RGB + technical control pack
        ↓
Design Master candidates → approval → Design Identity Pack
        ↓
Gemini Photoreal Balanced generation
        ↓
Geometry hard gates + consistency checks + realism ranking
        ├── pass → certified view
        └── fail → localized repair → revalidate
        ↓
6-view certified set → board + branding
        ↓ user command riêng
optional 6-shot video → merge + branding
```

### 1.1. Những điều không thay đổi

- Canonical Scene vẫn là nguồn đúng duy nhất cho hình học.
- Không có rule theo tên, tọa độ hoặc hình dạng của một model sample.
- Ảnh tham khảo không được quyết định footprint, camera, palette hoặc bố cục dự án.
- Sáu view phải dùng cùng một Design Identity.
- Image flow và video flow độc lập; hoàn tất ảnh không tự động gọi Veo.
- Human approval vẫn là điều kiện cuối của ảnh bàn giao.

### 1.2. Những điều phải thay đổi

- Thêm conditioning mode `photoreal_balanced` cho Gemini.
- Không gửi raw depth, instance ID, semantic ID và edge vào lượt beauty mặc định.
- Rút gọn prompt thành thứ tự thẩm quyền, immutable geometry, bounded freedom và photographic
  direction.
- Thay edge recall một chiều bằng bộ kiểm định hình học hai chiều.
- Thêm candidate selection cho Design Master và localized repair cho view lỗi.
- Tách hard gate hình học khỏi điểm realism/thẩm mỹ.
- Cập nhật manifest để truy vết input role, model, prompt, candidate và repair lineage.

## 2. Nguồn sự thật và thứ tự thẩm quyền

Thứ tự ưu tiên bắt buộc:

1. **Canonical 3D Scene** — vị trí, tỷ lệ, hình khối và quan hệ không gian.
2. **Semantic Scene** — vai trò của building, roof, road, gate, fence, landscape và context.
3. **Current-view Base RGB** — camera, composition, visible geometry của view đang sinh.
4. **Design DNA và approved Design Identity Pack** — ngôn ngữ thiết kế được phép.
5. **Approved Design Master** — biểu hiện trực quan của cùng design identity.
6. **Realism reference** — chất lượng ảnh chụp, vật liệu, ánh sáng và atmosphere.
7. **Gemini** — hoàn thiện hình ảnh trong phạm vi các nguồn trên.

Khi có xung đột:

- Base RGB thắng Design Master về camera và hình học.
- Design DNA thắng realism reference về palette và thiết kế.
- Realism reference chỉ được truyền chất lượng hoàn thiện, không truyền project-specific content.
- Gemini không được tự suy diễn một thay đổi có ảnh hưởng đến topology hoặc công năng.

## 3. Creative Budget

### 3.1. Ba lớp kiểm soát

| Lớp | Thành phần | Quyền của Gemini |
|---|---|---|
| `LOCKED` | Silhouette, footprint, số khối, trục và tính liên tục mái, ridge, đường, cổng, hàng rào, curb, opening chính | Không thêm, xóa, dịch chuyển hoặc đổi topology |
| `BOUNDED` | Vật liệu facade/mái, panel rhythm, canopy, sảnh, landscaping detail, cửa và phụ kiện công nghiệp | Phát triển trong Design DNA và construction grammar |
| `FREE` | Trời, mây, atmospheric haze, micro-imperfection, người/xe nhỏ, color grade nhẹ | Được sáng tạo nếu không che hoặc làm sai nội dung chính |

Policy phải tồn tại dưới dạng dữ liệu, semantic role và mask. Prompt chỉ mô tả lại policy; prompt
không phải cơ chế khóa duy nhất.

### 3.2. Input người dùng đã chốt

Production không còn cho chọn một “creative budget” chung. Người dùng chọn design package và các
component kit có nghĩa về cấu tạo: envelope, facade rhythm, office entrance, logistics, boundary,
gate và landscape. Mỗi kit chỉ được bật khi model capability có semantic evidence tương ứng.

Màu nhận diện bị giới hạn ở 3%, 5% hoặc 8% diện tích facade nhìn thấy. Không có control “số tầng”
hoặc “số cửa dock”; các giá trị này phải đến từ model, không được dùng làm proxy trang trí.

## 4. Dữ liệu đầu vào

### 4.1. Semantic Scene tối thiểu

Extraction phải nhận diện hoặc đánh dấu cần review các role:

- `primary_building`, `secondary_building`, `office`, `utility`, `guardhouse`;
- `roof`, `ridge`, `facade`, `glazing`, `loading_door`, `personnel_door`, `canopy`;
- `internal_road`, `external_road`, `yard`, `parking`, `curb`, `drainage`;
- `gate`, `fence`;
- `landscape`, `tree`, `shrub`;
- `context_building`, `context_ground`.

Nếu model có nhiều 3D view/design option chồng lấn, pipeline phải chọn scope hợp lệ trước khi
canonicalize. Không chắc chắn thì trả `unknown` hoặc `needs_review`, không âm thầm đoán.

### 4.2. Control pack cho mỗi view

Mỗi view phải có:

- `base_rgb.png` — guide sạch, dễ đọc;
- `depth.png`;
- `normal.png` nếu renderer hỗ trợ;
- `instance_id.png`;
- `semantic.png`;
- `edges.png`;
- `locked_mask.png`;
- `bounded_mask.png`;
- `free_mask.png`;
- mask riêng cho `primary_building`, `roof`, `road`, `gate`, `fence`, `landscape`, `context`;
- camera specification và projected bounds;
- control-pack manifest với checksum và provenance.

Control pass là dữ liệu QA. Chỉ adapter/provider mode có lý do được benchmark và phê duyệt mới được
đưa một control pass vào request sinh ảnh.

### 4.3. Clean Base RGB

Base RGB cần:

- giữ đúng toàn bộ visible geometry;
- có màu trung tính, không mang palette CAD tím/xanh giả;
- phân biệt được main building, auxiliary building, road, landscape và context;
- không chứa label, path debug, selection highlight hoặc UI overlay;
- không dùng low-poly asset nổi bật đến mức kéo Gemini về phong cách CGI;
- thể hiện rõ cổng, hàng rào, cửa, đường và mái nếu model có dữ liệu.

Guide không cần là ảnh bàn giao. Nó cần rõ ràng, sạch và đúng.

## 5. Gemini Photoreal Balanced

### 5.1. Vai trò model

Đường production mặc định:

- `gemini-3.1-flash-image`: sinh candidate và năm view production với chi phí thấp.
- `gemini-3-pro-image`: tùy chọn cho Design Master/hero khi benchmark chứng minh cải thiện đáng kể.
- `gemini-3.1-flash-lite-image`: chỉ dùng preview giá thấp sau khi vượt benchmark fidelity.

Model ID, giá và capability phải lấy từ cấu hình, được pin trong manifest và kiểm tra compatibility
khi khởi động worker.

### 5.2. Input contract

Design Master đầu tiên nhận:

1. Current-view Base RGB — `geometry_authority`.
2. Một realism reference đã duyệt — `quality_only`.
3. Prompt có Design DNA và authority policy.

Các view tiếp theo nhận:

1. Current-view Base RGB — `geometry_authority`.
2. Approved Design Master — `design_identity`.
3. Tối đa một realism reference — `quality_only`.
4. Prompt ngắn cho camera role hiện tại.

Không gửi mặc định:

- raw depth;
- raw semantic/instance ID;
- structural edge map;
- nhiều ảnh tham khảo cùng vai trò;
- output của view trước như nguồn bố cục.

Khả năng nhận nhiều ảnh của provider không phải lý do để dùng hết giới hạn. Mỗi input phải có một
vai trò duy nhất và có checksum trong manifest.

### 5.3. Prompt contract

Prompt production gồm bốn section:

```text
AUTHORITY
The Base RGB is the sole authority for camera, massing, footprint,
roof orientation, roads, gates, fences and object placement.

IMMUTABLE GEOMETRY
Preserve the exact number, continuity, proportions and placement of all
primary and auxiliary buildings and all authored site infrastructure.

BOUNDED DESIGN FREEDOM
Apply the approved Design Identity. Add construction-plausible facade,
roof, door, canopy, drainage, landscape and entourage detail without
changing geometry or circulation.

PHOTOGRAPHIC DIRECTION
Create a professional real-world architectural photograph with physically
plausible daylight, material response, contact shadows, atmospheric depth,
subtle imperfections and camera characteristics matching this view.
```

Negative constraints chỉ giữ các failure mode quan trọng:

1. Không thêm/xóa/nhân bản building.
2. Không đổi hướng, nhịp hoặc tính liên tục của mái.
3. Không di chuyển/xóa đường, cổng, hàng rào hoặc opening chính.
4. Không biến context thành công trình chính hay tạo context sai loại hình khu công nghiệp.
5. Không dùng màu phi thực tế, futuristic form, logo hoặc chữ tự sinh.

Không dùng prompt dài như một thay thế cho QA.

### 5.4. Response contract

- Chỉ yêu cầu image output.
- Aspect ratio phải khớp camera/output contract.
- Candidate dùng 1K; certified final dùng 2K mặc định.
- 4K chỉ dành cho hero đã duyệt nếu có nhu cầu bàn giao.
- Lưu provider request ID, model ID, resolution, latency, cost estimate và checksum.
- Không phụ thuộc hidden conversation state giữa các camera.

Conversational editing chỉ dùng trong cùng một localized repair chain và phải lưu interaction
lineage. Cross-view generation luôn truyền input tường minh để có thể tái lập và audit.

## 6. Design Master và Design Identity Pack

### 6.1. Chọn camera master

Không hardcode `VIEW-01`. Camera master được chọn bằng rule:

- nhìn thấy phần lớn primary massing;
- nhìn rõ mái và ít nhất một mặt facade chính;
- có đường/cổng/site relation đủ để đánh giá;
- không bị context hoặc foreground che;
- occupancy nằm trong khoảng camera QA đã hiệu chỉnh.

Nếu không có camera đạt, camera planner phải sửa view trước khi gọi API.

### 6.2. Candidate policy

- Sinh hai candidate master ở 1K.
- Cả hai phải qua hard geometry gates.
- Candidate đạt hard gate được xếp hạng theo consistency, realism và bid appeal.
- Nếu cả hai fail, repair candidate tốt hơn tối đa một lần hoặc dừng để review control scene.
- Không tiếp tục sinh năm view còn lại trước khi master được duyệt.

### 6.3. Design Identity Pack

Master được duyệt phải tạo một bản ghi có version gồm:

- palette và allowed color ranges;
- roof/facade material family và finish;
- facade rhythm, trim, canopy, door/window language;
- office/auxiliary-building treatment;
- gate/fence family;
- planting character và density band;
- daylight, weather, exposure, white balance và color-grade family;
- allowed entourage và mức độ micro-imperfection;
- source master checksum, Design DNA revision và reviewer decision.

Design Identity Pack mô tả ngôn ngữ, không chứa hình học riêng để sao chép từ master sang view khác.

## 7. Sinh bộ sáu view

1. Preflight toàn bộ sáu control pack.
2. Chọn camera master bằng rule.
3. Sinh và duyệt Design Master.
4. Đóng băng Design Identity Pack.
5. Sinh từng view còn lại với Base RGB riêng và cùng identity.
6. Chạy hard geometry/semantic QA ngay sau từng view.
7. Repair cục bộ view fail; không đợi sinh hết bộ mới phát hiện lỗi.
8. Khi từng view pass, chạy cross-view consistency QA.
9. Chỉ compose board và branding sau khi đủ sáu certified images.

Generation có thể song song sau khi Design Master được duyệt, nhưng kết quả vẫn phải được tập hợp qua
cross-view gate trước khi công bố hoàn tất.

## 8. Geometry và Semantic QA

### 8.1. Nguyên tắc

- Geometry/Semantic là hard gate.
- Realism/Aesthetic là ranking hoặc review gate.
- Thiếu evidence không được tính là pass.
- Threshold ban đầu là giả thuyết cần hiệu chỉnh bằng benchmark, không phải cam kết sản phẩm.

### 8.2. Bộ metric bắt buộc

| Metric | Phát hiện |
|---|---|
| Primary silhouette IoU | Sai hình khối, footprint chiếu hoặc mái ngoài biên |
| Edge precision/recall/F1 | Vừa mất cạnh thật, vừa phát minh cạnh mới |
| Bidirectional chamfer distance | Biên bị dịch chuyển dù vẫn có edge gần đó |
| Roof/ridge continuity | Chia mái dài thành nhiều mái nhỏ, đổi hướng hoặc đứt ridge |
| Connected-component/count | Thêm, xóa hoặc nhập nhầm building/auxiliary block |
| Road topology/coverage | Mất hoặc đổi đường nội bộ/ngoại bộ |
| Gate/fence presence and continuity | Mất cổng, hàng rào hoặc đặt sai boundary |
| Semantic-region retention | Cây xanh, yard, facade, context bị thay vai trò |
| Occlusion/occupancy | Công trình bị che hoặc camera framing không đạt |
| Forbidden-palette leakage | Màu annotation/CAD hoặc màu ngoài Design DNA |

Edge recall một chiều hiện tại chỉ được giữ làm telemetry tương thích, không đủ quyền chứng nhận.

### 8.3. Ngưỡng khởi điểm cho bake-off

Các mức dưới đây chỉ dùng để bắt đầu hiệu chỉnh:

- primary silhouette IoU: `>= 0.95` cho aerial, `>= 0.92` cho ground/close view;
- locked-edge F1: `>= 0.80`;
- bidirectional edge distance: `<= 3 px` tại output 1K;
- building count và roof topology: không sai khác;
- authored gate/fence/road critical component recall: `1.0`;
- forbidden palette leakage: không vượt ngưỡng hiện hành.

Sau pilot, threshold phải được chốt bằng correlation với human review và lưu theo `qa_profile_version`.

## 9. Cross-view consistency

Kiểm tra tối thiểu:

- màu và material family của roof/facade trên các surface cùng semantic role;
- facade rhythm, cửa, canopy và office treatment;
- gate/fence family;
- daylight, shadow softness, haze, exposure và white balance;
- landscape density và entourage scale;
- project context hierarchy.

Khi correspondence map đủ tin cậy, dùng reprojection trên các surface cùng nhìn thấy. Khi chưa đủ,
kết hợp masked color/material embedding, VLM-assisted review và human review. VLM không có quyền
override hard geometry failure.

## 10. Candidate ranking

Áp dụng hard gate trước. Candidate fail hard gate không được cứu bằng điểm thẩm mỹ cao.

Candidate đã pass có thể xếp hạng ban đầu:

```text
total_score =
    0.55 * geometry_score
  + 0.20 * cross_view_consistency
  + 0.15 * photographic_realism
  + 0.10 * bid_appeal
```

Trọng số là giả thuyết benchmark. Human blind review chấm riêng:

1. Đúng model và giao thông.
2. Đồng nhất thiết kế giữa sáu view.
3. Giống ảnh chụp thực tế.
4. Hợp lý và thi công được cho nhà xưởng công nghiệp.
5. Có sức thuyết phục trong hồ sơ đấu thầu.

## 11. Localized Repair

Repair request chỉ chứa:

- candidate hiện tại;
- crop Base RGB có thẩm quyền;
- crop/mask vùng fail;
- semantic role và metric fail;
- một chỉ thị sửa ngắn;
- Design Master/Identity nếu lỗi liên quan appearance.

Quy tắc:

- mask nhỏ nhất có thể;
- không regenerate toàn frame vì một lỗi cục bộ;
- tối đa hai repair cho một view;
- chạy lại metric liên quan và toàn bộ hard gate sau mỗi repair;
- không pass sau giới hạn thì trạng thái `NEEDS_REVIEW`, không phát hành final;
- giữ đầy đủ parent checksum và repair lineage.

Ví dụ chỉ thị:

```text
Restore the exact continuous longitudinal roof and ridge shown in the
authoritative Base RGB crop. Change only the masked roof region. Preserve
all facade, camera, lighting and surrounding content unchanged.
```

## 12. Context khu công nghiệp

Context có ba trường hợp:

1. **Authored context:** lấy trực tiếp từ model, thuộc `LOCKED` hoặc `BOUNDED` theo semantic role.
2. **Provenance ContextPack:** dữ liệu site/GIS/ảnh được phép sử dụng, có version và nguồn.
3. **Neutral generated context:** chỉ dùng khi không có dữ liệu địa điểm; phải được gắn nhãn
   non-authoritative.

Neutral context phải tuân theo grammar khu công nghiệp:

- đường trục/nhánh, verge, lô công nghiệp và khoảng lùi hợp lý;
- cây theo hàng, setback hoặc dải xanh, không biến site thành rừng;
- context building là khối xưởng trung tính, giảm tương phản/chi tiết để focus công trình chính;
- không tạo landmark, địa hình, mặt nước hoặc mật độ đô thị không có cơ sở;
- không che cổng, hàng rào, đường và mặt tiền chính.

“Khối mờ” không được biến thành hộp kính trong suốt phi thực tế. Dùng massing trung tính, atmospheric
perspective và giảm saturation/contrast để thể hiện thứ bậc thị giác.

## 13. Tách Image Flow và Video Flow

### ImageGenerationJob

Kết thúc sau:

- sáu ảnh certified;
- view-set QA report;
- board sáu ảnh;
- branding;
- manifest cuối.

Job này không bao giờ tự gọi Veo.

### VideoGenerationJob

Chỉ được tạo bằng thao tác riêng trên một approved image view-set:

- tạo đủ sáu shot;
- kiểm tra shot;
- merge showreel không audio;
- chèn branding;
- lưu cost/retry/state riêng.

Retry ảnh không tạo lại video; retry video không tạo lại ảnh.

## 14. Trạng thái output

- `CONTROL_READY`: control pack đã qua preflight.
- `MASTER_CANDIDATES_READY`: có candidate để duyệt.
- `DESIGN_MASTER_APPROVED`: identity đã khóa.
- `GENERATIVE_REVIEW`: ảnh đã sinh nhưng chưa đủ hard-gate evidence.
- `GEOMETRY_CERTIFIED`: toàn bộ geometry/semantic hard gate pass.
- `VIEWSET_CONSISTENT`: sáu view pass cross-view checks.
- `APPROVED_FINAL`: đã được người có thẩm quyền duyệt thẩm mỹ.
- `NEEDS_REVIEW`: vượt retry/repair budget hoặc evidence không đủ.

UI/API không được hiển thị “Hoàn tất” khi chưa đạt `APPROVED_FINAL`, trừ khi nhãn trạng thái nói rõ
đây là kết quả kỹ thuật hoặc đang chờ duyệt.

## 15. Manifest và reproducibility

Mỗi candidate/view phải lưu:

- project, model hash, selected source view và design revision;
- camera spec và camera-role version;
- Canonical/Semantic Scene checksum;
- control-pack checksum;
- input images với role và checksum;
- Design DNA và Design Identity version;
- provider/model/endpoint contract;
- prompt template version và rendered prompt hash;
- requested aspect ratio/resolution;
- provider request ID, latency và cost estimate;
- candidate rank và mọi QA evidence;
- repair history;
- reviewer decision;
- final branding checksum.

Không cam kết tái tạo bit-for-bit nếu provider không cung cấp seed deterministic. Hệ thống phải tái
lập được toàn bộ input, policy, request và quyết định chọn output.

## 16. Thí nghiệm quyết định

### 16.1. Bake-off ba phương án

Dùng cùng model, camera, Design DNA và realism reference:

| Mã | Input Gemini | Vai trò |
|---|---|---|
| A — `full` | RGB + depth + instance + semantic + edge + references/master | Baseline hiện tại |
| B — `minimal` | RGB + edge + reference/master | Đo ảnh hưởng khi giảm pass |
| C — `photoreal_balanced` | RGB + master + một realism reference; technical pass chỉ dùng QA | Phương án mục tiêu |

Chạy trước trên ba camera role:

- overview/aerial;
- close architectural view;
- human-eye ground view.

Mỗi phương án dùng 1K, không watermark trong bước metric. Không thay camera hoặc prompt intent giữa
các nhánh.

### 16.2. Dataset

Sau spike một model, benchmark phải mở rộng tối thiểu 10 RVT đại diện:

- một và nhiều khối;
- xưởng dài, campus và office-attached;
- một, hai hoặc ba mặt tiền;
- mái và site access khác nhau;
- mức semantic completeness khác nhau.

Không chốt production dựa trên một file sample.

### 16.3. Tiêu chí chọn phương án

Phương án C được chọn nếu:

- không tăng critical geometry failure so với baseline sau repair budget;
- realism và bid-appeal blind score tăng có ý nghĩa;
- consistency giữa view không giảm dưới gate;
- median cost nằm trong ngân sách;
- tỷ lệ human correction giảm.

Nếu C drift nhẹ, ưu tiên localized repair. Chỉ thử thêm softened structural guide khi bằng chứng cho
thấy một loại lỗi lặp lại; không quay lại gửi toàn bộ raw pass theo mặc định.

## 17. Chi phí và routing

Theo giá tham chiếu ngày 2026-09-11 của Gemini 3.1 Flash Image:

- 1K: khoảng `$0.067/image`;
- 2K: khoảng `$0.101/image`;
- 4K: khoảng `$0.151/image`;
- batch khoảng một nửa output cost nhưng có độ trễ và không phù hợp trước khi master được duyệt.

Routing đề xuất:

1. Hai Design Master candidate ở 1K.
2. Sau approval, năm view còn lại ở 2K.
3. Retry/repair chỉ view fail.
4. 4K/upscale chỉ cho hero đã duyệt.
5. Batch có thể dùng cho năm view sau master nếu SLA cho phép.

Cost manifest phải tính output, input và retry thực tế; giá tài liệu chỉ là ước lượng lập kế hoạch.

## 18. Kế hoạch triển khai

### 18.0. Trạng thái baseline ngày 2026-09-11

- Hoàn tất: Photoreal Balanced request contract, six-view camera plan, semantic material QA,
  Design Master approval gate, image/video flow độc lập và output publishing.
- Hoàn tất: model capability API, semantic design-kit catalog, form hai bước, deterministic preview
  token, capability fallback, kit-aware conditioning và Playwright flow.
- Có baseline: correspondence map, consistency report, repair planning và certification states.
- Chưa bật mặc định vì cần benchmark có phí: hai master candidate, chained overlap reference và
  Gemini masked repair. Các mục này không được coi là điều kiện để form production phát sinh chi phí;
  chúng chỉ được mở khi A/B chứng minh lợi ích.

### Phase 0 — Baseline và contract

Deliverables:

- đóng băng bộ input/output baseline;
- thêm `photoreal_balanced` vào conditioning mode;
- định nghĩa input-role và candidate manifest;
- version prompt contract;
- benchmark runner A/B/C cho ba view;
- không thay behavior production mặc định trong lúc chưa có kết quả bake-off.

Exit criteria:

- request snapshot chứng minh C chỉ gửi đúng các input được phép;
- có cost, latency và checksum cho từng candidate;
- baseline tái chạy được.

### Phase 1 — Design Master workflow

Deliverables:

- camera-master selector không hardcode view ID;
- hai-candidate master generation;
- Design Identity Pack schema;
- approval state và API/UI;
- khóa generation các view còn lại trước approval.

Exit criteria:

- master pass geometry gates;
- reviewer chọn/reject được candidate;
- identity version được ghi vào mọi view sau đó.

### Phase 2 — Geometry QA v2

Deliverables:

- silhouette IoU;
- edge precision/recall/F1;
- bidirectional chamfer;
- roof continuity/count;
- road/gate/fence/semantic checks;
- evidence report và threshold profile có version.

Exit criteria:

- ảnh phát minh thêm edge không thể pass chỉ nhờ recall;
- thiếu gate evidence tạo `NEEDS_REVIEW`;
- metric unit/integration tests dùng fixture tốt và fixture lỗi có chủ ý.

### Phase 3 — Localized repair

Deliverables:

- repair planner từ failed metrics;
- crop/mask request builder;
- Gemini same-image edit adapter;
- repair budget, lineage và revalidation;
- UI hiển thị nguyên nhân repair/fail.

Exit criteria:

- lỗi cục bộ không regenerate toàn view-set;
- repair không làm hỏng vùng ngoài mask theo tolerance;
- quá retry budget không bị gắn nhãn final.

### Phase 4 — Cross-view certification

Deliverables:

- identity consistency validator;
- surface correspondence/reprojection khi đủ dữ liệu;
- view-set certification state;
- board/branding chỉ nhận certified inputs.

Exit criteria:

- sáu ảnh cùng roof/facade/gate/fence/lighting identity;
- view trùng camera hoặc bị che bị chặn trước final;
- report truy vết được candidate của từng view.

### Phase 5 — Production hardening

Deliverables:

- worker idempotency và provider retry policy;
- rate-limit/backoff/circuit breaker;
- model/prompt/schema version pinning;
- latency/cost/failure observability;
- retention/security policy;
- full frontend/API flow và Playwright tests.

Exit criteria:

- retry không tạo revision hoặc charge trùng ngoài policy;
- provider lỗi không làm mất artifact đã pass;
- image/video flow độc lập và trạng thái UI chính xác.

## 19. Backlog theo codebase

### P0

- `providers/gemini.py`: thêm mode và payload builder theo input role.
- `providers/contracts.py`: mở rộng candidate, reference role và repair contract.
- `providers/image_factory.py` và `cli.py`: expose mode mới.
- `application/refinement_prompt.py`: prompt template ngắn, có version.
- `application/refine_viewset.py`: Design Master candidate/approval orchestration.
- `application/protect_refinement.py`: giữ recall telemetry, bổ sung QA v2 thay vì pixel restore.
- `application/validate_viewset.py`: hard gate và cross-view evidence.
- schemas: Design Identity Pack, candidate manifest, QA profile.
- tests: request snapshot, no-raw-pass assertion, metric fixtures và state transition.

### P1

- camera-master selector;
- candidate ranking;
- localized repair planner/executor;
- UI duyệt Design Master và hiển thị QA status;
- benchmark report A/B/C.

### P2

- surface correspondence/reprojection;
- automated realism ranking;
- batch routing sau master approval;
- benchmark Gemini Pro master và Flash production.

### Không làm trong giai đoạn này

- Fine-tune/LoRA khi chưa có dataset ảnh đã duyệt.
- Dựng full PBR asset library như giải pháp chính cho photorealism.
- Custom multi-view diffusion trước khi đo giới hạn của Photoreal Balanced.
- Google Image Search grounding trong production mặc định; reference phải được curate và version để
  tránh biến động, attribution và lệch phong cách.
- Tối ưu theo riêng `model_lod100_sample*.rvt`.
- Tăng độ dài prompt thay cho việc sửa contract và QA.

## 20. Rủi ro và kiểm soát

| Rủi ro | Kiểm soát |
|---|---|
| Gemini đổi mái/hình khối khi được nới tự do | Base RGB authority + geometry hard gates + localized repair |
| Sáu view khác phong cách | Approved master + versioned Design Identity + cross-view gate |
| Reference kéo sai palette/bố cục | Một reference `quality_only`, role rõ, Design DNA thắng |
| Base RGB kéo output về CGI | Guide sạch/trung tính, bỏ raw technical pass khỏi beauty request |
| Context thành rừng hoặc sai khu công nghiệp | Industrial context grammar + semantic masks + review |
| Khối context trong suốt phi thực tế | Neutral massing + haze/low contrast thay vì glass transparency |
| QA false pass | Metric hai chiều, topology checks và human audit |
| Chi phí tăng | Hai master candidates, một candidate/view, local retry, budget cap |
| Provider/model thay đổi | Pin model, schema/prompt version và regression benchmark |
| Không có seed deterministic | Reproducible request/evidence, không cam kết bit-identical output |

## 21. Definition of Done

Chương trình chỉ hoàn thành khi:

1. `photoreal_balanced` thắng baseline về realism/bid appeal trên dataset, không chỉ trên sample.
2. Hình khối, mái, đường, cổng, hàng rào, landscape và auxiliary buildings được giữ qua sáu view.
3. Sáu view có cùng Design Identity và không trùng vai trò camera.
4. Mọi hard gate có evidence; thiếu evidence không được pass.
5. Candidate/repair/provider lineage truy vết đầy đủ.
6. Lỗi cục bộ được repair riêng; retry ảnh không sinh video.
7. Board, branding và video chỉ nhận approved/certified source images.
8. UI/API phản ánh đúng trạng thái và không báo hoàn tất sớm.
9. Không có logic riêng cho sample hoặc một kiểu nhà xưởng.
10. Human reviewer đánh giá bộ ảnh đạt mức bàn giao về đúng model, chân thật, khả thi và sức thuyết
    phục.

## 22. Tài liệu tham chiếu

- [Controlled Realism — implementation readiness](V365_CONTROLLED_REALISM_IMPLEMENTATION_READINESS_REPORT.md)
- [V365 Multi-view Realism — nghiên cứu và kiểm nghiệm](V365_MULTIVIEW_REALISM_RESEARCH_AND_EXPERIMENTS.md)
- [V365 feasibility report](V365_LOD100_MultiView_ArchViz_FEASIBILITY_REPORT.md)
- [Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation)
- [Gemini 3.1 Flash Image](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Multi-View Depth Consistent Image Generation for Architectural Design](https://arxiv.org/abs/2503.03068)
- [MV-Adapter: Multi-view Consistent Image Generation Made Easy](https://arxiv.org/abs/2412.03632)
- [ControlNet](https://arxiv.org/abs/2302.05543)

---

**Quyết định mặc định để bắt đầu triển khai:** xây Phase 0 và chạy bake-off A/B/C trên ba camera
role. Không thay production default trước khi `photoreal_balanced` vượt hard geometry gates và thắng
blind review về độ chân thật.
