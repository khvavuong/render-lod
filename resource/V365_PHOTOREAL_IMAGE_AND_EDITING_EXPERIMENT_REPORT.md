# V365 Photoreal Image & Editing — Báo cáo kiểm nghiệm và hướng triển khai

Ngày đánh giá: 2026-09-14

Tài liệu được đánh giá: `V365_PLAN_PHOTOREAL_IMAGE_AND_EDITING.md`

## 1. Kết luận điều hành

Kế hoạch hiện tại đúng về kiến trúc tổng thể: Blender giữ vai trò nguồn sự thật hình học, AI đảm nhiệm vật liệu/ánh sáng/bầu không khí, sau đó phải qua QA trước khi xuất bản. Tuy nhiên, thứ tự triển khai và benchmark cần thay đổi.

Kết quả thử nghiệm thực tế cho thấy nút thắt hiện tại không đơn thuần là model Gemini chưa đủ mạnh. Ba nguyên nhân quan trọng hơn là:

1. Camera chưa được kiểm định theo ý đồ kiến trúc trước khi gọi AI.
2. Ảnh style reference có thể làm model sao chép bố cục và hình thái không thuộc dự án, gây sai geometry dù ảnh trông chân thật hơn.
3. QA hiện mới đo một phần sự tương ứng biên ảnh; chưa chặn được lỗi logic kiến trúc và còn cho phép view-set tổng thể `passed=true` khi một số view kỹ thuật đã `fail`.

Phương hướng phù hợp nhất là **Camera-first, Geometry-locked, Reference-optional, QA-gated**:

- chọn và duyệt camera bằng render rẻ trước;
- mặc định tạo ảnh bằng Gemini Pro với base RGB + structure/context evidence + Design Master, không truyền ảnh style ngoài;
- chỉ bật style reference khi đã qua kiểm tra tương thích và chỉ cho một mục tiêu hẹp;
- dùng Flash cho preview/candidate, Pro cho master/final;
- multi-turn chỉ sửa lỗi đã được QA xác định, không dùng để “làm đẹp thêm” chung chung;
- chỉ phát triển image editing sau khi six-view generation vượt acceptance gate.

## 2. Cơ sở từ tài liệu chính thức

Google hiện mô tả `gemini-3.1-flash-image` là model cân bằng tốc độ/chất lượng và hỗ trợ consistency với nhiều ảnh tham chiếu; `gemini-3-pro-image` dành cho asset chuyên nghiệp và kiểm soát sáng tạo chính xác hơn. API hỗ trợ text-and-image editing, output 1K/2K/4K và tối đa 14 ảnh đầu vào tùy loại. Google cũng khuyến nghị multi-turn cho quá trình chỉnh sửa lặp, với `previous_interaction_id` để nối trạng thái. Nguồn: [Gemini image generation documentation](https://ai.google.dev/gemini-api/docs/image-generation), [Gemini 3.1 Flash Image](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-image), [Gemini 3 Pro Image](https://ai.google.dev/gemini-api/docs/models/gemini-3-pro-image).

Điều quan trọng: khả năng nhận nhiều reference không có nghĩa là càng nhiều reference càng đúng. Reference phải có vai trò rõ ràng và không được cạnh tranh với geometry authority.

Theo bảng giá chính thức tại thời điểm đánh giá, Flash Image khoảng 0,067 USD/ảnh 1K, 0,101 USD/ảnh 2K; Pro Image khoảng 0,134 USD/ảnh 1K/2K. Batch gần bằng một nửa mức standard và phù hợp cho benchmark ngoại tuyến. Nguồn: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

## 3. Hiện trạng codebase

### Đã có và nên giữ

- Base RGB cùng depth, normal/edge, instance, semantic và structure guide.
- Design DNA, view-set có vai trò camera, Design Master và master chaining.
- Router Gemini Flash/Pro theo profile.
- Context proxy có đăng ký theo camera và cơ chế bảo vệ/đo edge alignment.
- Manifest chứa provenance, hash input/output và provider configuration.

### Chưa đủ để triển khai đúng kế hoạch

- Chưa có camera candidate generator + semantic visibility/occlusion gate trước paid generation.
- Chưa có `StylePack` typed contract và compatibility gate; reference hiện vẫn có thể được đưa thẳng vào request.
- Gemini adapter chưa lưu/đọc `interaction_id`, chưa hỗ trợ `previous_interaction_id`; manifest thực tế có `provider_request_id=null`.
- Gemini capability đang khai báo `supports_multi_turn_state=false` và `supports_masked_edit=false`.
- Provenance của `RefineViewSet` đang ghi lặp `context_composition_guide` thành `reference_01` và `reference_02`: request thực tế chỉ gửi một guide, nhưng lớp persist bổ sung guide lần thứ hai. Cần sửa trước khi dùng manifest để audit/benchmark tự động.
- Chưa có visual QA thật sự cho realism, kiến trúc công nghiệp và consistency; nhiều mục chỉ là `evidence_not_available`.
- Chưa có frontend canvas/selection resolver cho click, box, brush, lasso.
- Chưa có stable semantic object mapping đủ để chuyển từ vùng chọn 2D sang đối tượng thiết kế và lan truyền đa view.

## 4. Thử nghiệm thực tế

### 4.1. Thiết lập

- Model revision: `c4ce997413f576c7`
- Design revision: `R01-22464b7e6485`
- View thử: `view-04`, role `detail`
- Cùng base render, structure guide, context proxy và approved Design Master.
- Profile: `preview_fast`, output 1K, thinking `high`.
- Mỗi cấu hình chỉ sinh một candidate để tránh chi phí không cần thiết.

VIEW-04 được chọn vì đây là góc khó: camera đi sát mặt bên nhà xưởng, có khối phụ trợ ở tiền cảnh và từng bị AI biến thành hai dãy nhà xưởng đối diện nhau.

### 4.2. Kết quả

| Mẫu | Model | Style reference ngoài | Edge F1 | Chamfer | Kết quả trực quan |
|---|---|---:|---:|---:|---|
| A — pipeline hiện tại | Gemini 3.1 Flash Image | Có | 0,835 | 1,434 px | Giữ biên khá tốt nhưng phát minh dãy nhà đối diện, sai logic site |
| B — nâng model | Gemini 3 Pro Image | Có | 0,346 | 3,672 px | Vật liệu/ánh sáng thật hơn nhưng thay đổi mạnh phối cảnh và khối phụ trợ |
| C — reference ablation | Gemini 3 Pro Image | Không | **0,871** | **1,233 px** | Tốt nhất: mặt đứng, đường nội bộ và context trong suốt hợp lý hơn; vẫn bị giới hạn bởi camera gốc |

Artifacts:

- A: `.artifacts/generated/c4ce997413f576c7/R01-22464b7e6485/view-04/refined.jpg`
- B: `.artifacts/benchmarks/photoreal-p0-20260914/B-pro-reference-one-turn/view-04/refined.jpg`
- C: `.artifacts/benchmarks/photoreal-p0-20260914/C-pro-no-style-reference/view-04/refined.jpg`

Các con số trên là phép đo hình học hiện có của pipeline, không phải điểm thẩm mỹ tổng hợp. Chúng hữu ích để phát hiện drift nhưng chưa thể thay thế đánh giá logic kiến trúc.

### 4.3. Điều học được

1. **Nâng Flash lên Pro không tự động tăng độ chính xác.** Mẫu B đẹp hơn về vật liệu nhưng sai hình học nhiều hơn A.
2. **Style reference là biến gây nhiễu mạnh nhất trong thử nghiệm này.** Khi bỏ reference ngoài, cùng Pro và cùng conditioning đạt cả fidelity lẫn realism tốt hơn rõ rệt.
3. **Base camera đặt trần chất lượng đầu ra.** Mẫu C tốt nhưng vẫn chỉ là một service-side detail; không thể biến thành góc trình diễn giàu ý đồ mà không thay camera.
4. **Edge metric chưa hiểu semantics.** Mẫu A có F1 khá cao dù model tạo sai loại công trình ở bên trái. QA phải kết hợp instance/semantic, không chỉ edge.
5. **Ảnh sample nên là tiêu chuẩn chấm, không phải mặc định là pixel reference.** Nên trích đặc tính như độ chân thực vật liệu, độ phức tạp môi trường, ánh sáng, mật độ giao thông và mức độ “camera photograph”; không sao chép hình khối hoặc bố cục sample.

## 5. Sửa lại chiến lược benchmark P0

Không nên chạy ngay ma trận 24 ảnh trong kế hoạch cũ. Với 12 ảnh Flash và 12 ảnh Pro ở 1K, riêng output đã khoảng 2,41 USD; ở 2K khoảng 2,82 USD, chưa tính lượt multi-turn. Quan trọng hơn, benchmark lớn trên camera chưa đạt sẽ tối ưu sai biến.

P0 mới gồm bốn gate tuần tự:

### Gate 0 — Camera benchmark không gọi AI

- Sinh 3–5 camera candidate cho mỗi role từ Blender Eevee/workbench.
- Chấm coverage, target visibility, occlusion, mặt tiền/cổng/hàng rào/đường nhìn thấy và tỷ lệ sky/ground/building.
- Loại camera có vật cản tiền cảnh, mặt đứng trống hoặc trùng coverage.
- Một người duyệt contact sheet camera trước khi phát sinh chi phí AI.

### Gate 1 — Conditioning ablation

Chỉ dùng hai view đại diện: một overall/context và một hero/detail.

- Flash, không external style reference.
- Pro, không external style reference.
- Pro + một reference đã qua compatibility gate.

Mỗi cấu hình một candidate. Chỉ sinh thêm seed/candidate cho hai cấu hình đứng đầu.

### Gate 2 — Controlled multi-turn

Chỉ chạy khi turn 1 vượt geometry gate nhưng còn một lỗi cục bộ rõ ràng. Turn 2 nhận lỗi máy đọc được, ví dụ “giữ nguyên mọi geometry; chỉ sửa asphalt từ concrete sang dark asphalt trong semantic region road”. Không dùng yêu cầu rộng như “make it more realistic”.

### Gate 3 — Six-view pilot

Sinh đủ sáu view trên một revision chưa từng dùng để tune. Không approve/promote baseline nếu bất kỳ critical view nào fail.

## 6. Kiến trúc production đề xuất

```text
RVT/IFC
  -> Semantic scene + stable IDs
  -> Camera candidate planner
  -> Cheap render + camera QA gate
  -> Approved 6-camera contract
  -> Blender conditioning pack
  -> Prompt compiler (geometry / appearance / context / negatives)
  -> Model router
       Preview: Flash 0.5K/1K
       Final candidate: Pro 2K, no external style ref by default
       Optional style ref: compatibility-gated
  -> Geometry + semantic + visual QA
  -> Optional targeted multi-turn correction
  -> Cross-view consistency QA
  -> Human review
  -> Branded delivery
```

### Reference policy

Mỗi ảnh input phải có đúng một role:

- `geometry_authority`: base RGB/registered render; luôn ưu tiên cao nhất.
- `structure_evidence`: edge/depth/semantic guide; không dùng làm style.
- `identity_anchor`: approved Design Master của chính dự án.
- `context_evidence`: camera-registered transparent massing/context.
- `appearance_reference`: tùy chọn, chỉ mang vật liệu/ánh sáng/decor; không được mang bố cục.

Mặc định `appearance_reference = none`. Nếu bật, compatibility gate phải kiểm tra loại công trình, tỷ lệ mái, khí hậu, mật độ site, camera family và bảng màu. Reference không tương thích được chuyển thành **textual style attributes**, không gửi ảnh trực tiếp.

### Model routing

- Flash Lite/Flash: contact sheet, preview, UI feedback và candidate rẻ.
- Pro: Design Master và final views sau camera gate.
- Batch: benchmark/re-render ngoại tuyến; không dùng cho yêu cầu tương tác cần phản hồi ngay.
- Không regenerate toàn bộ six-view chỉ vì một view lỗi; retry theo view và lưu lineage.

### QA bắt buộc

Một view chỉ pass khi đồng thời đạt:

- camera-role compliance;
- edge/depth alignment;
- semantic retention cho building, gate, fence, road, greenery, context proxy;
- industrial plausibility: loại cửa, khẩu độ cổng, hàng rào, mái, loading/service access;
- material plausibility và anti-CGI;
- identity consistency với master và các view đã pass.

View-set `passed=true` phải là phép AND của mọi critical view. Trạng thái `review` hoặc `fail` của một critical view phải chặn publish và chặn promote baseline.

## 7. Image Editing: phạm vi phù hợp

Image editing là hướng khả thi nhưng không nên là cách cứu một generation pipeline chưa ổn định.

### Visual Edit v1

- Người dùng chọn vùng bằng box/brush.
- Backend resolve vùng bằng instance/semantic buffers.
- Gemini multi-turn sửa một thuộc tính cục bộ: màu, vật liệu, cây xanh, xe/người, grading.
- Luôn gửi lại ảnh gốc/turn trước, vùng semantic và preservation constraints.
- QA so sánh ngoài vùng chọn; nếu drift vượt ngưỡng thì reject.

### Design Edit v2

- Các thay đổi có ý nghĩa xây dựng như vị trí cửa, kích thước cổng, mái, hàng rào phải cập nhật Design DNA/scene trước.
- Render lại conditioning pack rồi generate lại các view bị ảnh hưởng.
- Không cho phép pixel edit trở thành nguồn sự thật thiết kế.

### Điều kiện kỹ thuật trước khi làm UI edit

1. Gemini adapter lưu `interaction_id`, bật `store` theo policy và hỗ trợ `previous_interaction_id`.
2. Manifest có parent/child lineage cho từng lượt edit.
3. Selection resolver map từ pixel sang stable semantic/object ID.
4. Outside-mask preservation QA và rollback.

## 8. Thứ tự triển khai khuyến nghị

### P0A — Camera QA và fail-closed QA

- Candidate generator + contact sheet.
- Role-specific camera metrics.
- Sửa aggregate pass logic.
- Chặn paid generation khi camera fail.

### P0B — Reference contract và benchmark harness

- Typed reference roles.
- Default no external appearance reference.
- Loại bỏ việc ghi lặp context guide trong generation manifest.
- Compatibility gate + reference ablation report.
- Lưu model, prompt, reference hashes, metrics, cost estimate và reviewer decision.

### P1 — Photoreal v1

- Pro final 2K sau camera approval.
- Design Master của chính dự án làm identity anchor.
- Semantic QA cho gate/fence/road/greenery/context.
- Retry riêng view lỗi; six-view approval gate.

### P2 — QA-driven multi-turn

- Provider interaction state.
- Machine-readable correction prompt.
- Tối đa một correction turn tự động; lượt sau cần human review.

### P3 — Visual Editing MVP

- Box/brush selection, preview, undo, history.
- Local appearance edits trước.
- Design edits và multi-view propagation triển khai sau khi stable IDs ổn định.

## 9. Acceptance criteria đề xuất

Một pilot được coi là sẵn sàng bàn giao khi:

- 6/6 camera khác nhau về mục tiêu và cùng kể một câu chuyện thiết kế;
- 6/6 view giữ đúng footprint, khối tích, mái, cửa/cổng/hàng rào/đường quan trọng;
- không view nào có semantic critical fail;
- context industrial nhất quán, khối lân cận giữ ngôn ngữ trong suốt/không tranh focus;
- màu sắc, facade DNA, cửa và roof system đồng nhất;
- ít nhất 5/6 view được reviewer đánh giá đạt realism bàn giao, view còn lại không dưới mức chấp nhận;
- không có lỗi aggregate `passed=true` khi view thành phần fail;
- mọi output có provenance, cost và lineage tái lập được.

## 10. Quyết định đề xuất

Không tiếp tục theo hướng “thêm prompt + thêm ảnh sample + tăng số candidate”. Tiếp tục với phương án C làm baseline kỹ thuật mới: **Gemini Pro, approved project master, registered context evidence, không external style reference mặc định**. Việc tiếp theo cần triển khai trước tiên là camera QA và fail-closed QA; đây là hai thay đổi có tác động chất lượng lớn nhất và không làm tăng chi phí sinh ảnh.
