# V365 User Intent → Controlled-Realism Pipeline

**Trạng thái:** Đề xuất triển khai  
**Ngày đánh giá:** 2026-09-11  
**Mục tiêu:** Cho phép người dùng điều khiển phong cách ảnh từ giao diện mà không phá hình học,
camera, giao thông, cổng, hàng rào, cây xanh và tính đồng nhất sáu view.

## 1. Kết luận

Khả thi. Luồng hiện tại đã truyền được phần lớn dữ liệu:

```text
DesignPanel
  → DesignFormValues
  → buildDesignBrief()
  → POST /design-revisions
  → DesignBrief (Pydantic validation)
  → PlanDesign
  → immutable DesignDNA + design_revision
  → refinement_prompt + Design Identity Pack
  → Gemini Photoreal Balanced
```

Không nên gửi trực tiếp toàn bộ form thành một đoạn prompt. Phương án phù hợp là đưa mọi lựa chọn
qua một `UserRenderIntent` có schema/version, compile trên backend thành Design DNA và một prompt
envelope có thứ tự thẩm quyền. Text tự do chỉ là `soft preference`, không bao giờ có quyền thay đổi
geometry.

## 2. Hiện trạng

### Đã hoạt động

- Upload RVT, project ID, style preset, palette, decor, số tầng văn phòng, loading dock, landscape,
  entourage, thời gian và prompt tự do đã tồn tại trên UI.
- `DesignBrief` có validation chặt; dữ liệu extra bị từ chối.
- `PlanDesign.revision()` đã hash Canonical Scene và toàn bộ brief, nên thay đổi input tạo revision mới.
- Style, palette, môi trường, landscape, decor và creative prompt đã đi vào prompt/identity pack.
- Loading dock được dựng deterministically trên một facade được chọn từ model, không rải trên mọi mặt.
- Photoreal Balanced đã khóa Base RGB là geometry authority và dùng Design Master cho appearance.

### Khoảng trống cần sửa

1. `STYLE_LANGUAGE` và `DECOR_ARTICULATION` đang nằm ở frontend. Client khác có thể gửi prose khác
   với cùng preset; backend chưa phải nguồn sự thật duy nhất.
2. UI gửi một số giá trị hardcode: weather, sun angle, white balance, roof, solar, context count,
   context mode và panel module.
3. `creative_prompt` đang nối trực tiếp vào prompt. Nó cần normalization và policy check trước khi
   được xem là dữ liệu, không phải instruction có thẩm quyền.
4. `requested_office_storeys` hiện chủ yếu là prompt hint; chưa gắn rõ với facade office hợp lệ.
5. Màu HEX là màu vật liệu mục tiêu, không thể đòi pixel ảnh đúng HEX dưới mọi điều kiện ánh sáng.
6. Thời gian người dùng chọn nhưng sun azimuth/elevation vẫn cố định, có thể tạo ánh sáng phi vật lý.
7. `procedural_perimeter=6` đang được UI hardcode cho mọi dự án, trái với nguyên tắc không suy diễn
   context ngoài model nếu chưa có dữ liệu.

## 3. Contract được đề xuất

Tạo contract `UserRenderIntentV1`; frontend chỉ gửi ID enum và giá trị nghiệp vụ, không gửi prompt
kiến trúc đã diễn giải:

```json
{
  "schema_version": "1.0.0",
  "style_preset": "contemporary_industrial",
  "creative_budget": "balanced",
  "material_palette": {
    "primary_hex": "#ECE9E1",
    "secondary_hex": "#202A31",
    "glass_hex": "#294B5B",
    "accent_hex": "#176B4D",
    "paving_hex": "#74797A"
  },
  "decor_level": "balanced",
  "office_facade_rhythm": 2,
  "loading_dock_policy": "suggest_if_missing",
  "loading_dock_count": 3,
  "landscape_preset": "tropical_restrained",
  "entourage_density": "low",
  "lighting_preset": "bright_morning",
  "context_presentation": "neutral_industrial_massing",
  "realism_preset": "documentary_architectural_photo",
  "free_text": "Ưu tiên sảnh vào rõ ràng và tiết chế."
}
```

### Nhóm authority

| Nhóm | Ví dụ | Cách xử lý |
|---|---|---|
| `LOCKED` | massing, roof topology, road, gate, fence, green polygons, camera | Chỉ đọc từ model; form không được override |
| `BOUNDED` | facade rhythm, dock/entrance trên facade hợp lệ, decor, palette | Compile deterministically và kiểm tra sau sinh |
| `FREE` | mây, vi sai cây, người/xe nhỏ, micro-texture, grain | Gemini được sáng tạo trong giới hạn |
| `OPERATIONAL` | provider, model, conditioning mode, 1K/2K | Backend/config quyết định, không đưa lên form thường |

## 4. Ma trận tham số UI

| Tham số | Khả thi | Khuyến nghị |
|---|---:|---|
| Phong cách | Cao | Gửi preset ID; backend resolve thành design tokens và prompt fragment versioned |
| Palette | Cao | Lưu HEX làm material target; QA dùng tolerance/Delta-E thay vì exact pixel |
| Decor | Cao | Map thành numeric facade grammar; chỉ tác động facade `focus` |
| Số tầng | Có điều kiện | Đổi nhãn thành “Nhịp tầng khối văn phòng”; chỉ áp dụng office surface trong envelope |
| Loading dock | Có điều kiện | Thêm policy `preserve_existing/suggest_if_missing/exact_on_eligible_facade` |
| Landscape | Cao | Chỉ thay character/species trong polygon xanh đã authored |
| Người và xe | Cao | Presentation-only; giới hạn mật độ và central occlusion |
| Thời điểm | Cao | Dùng lighting preset hoặc tính sun từ geolocation; không ghép giờ với sun angle cố định |
| Context | Cao | `authored_only` mặc định; neutral massing chỉ tại footprint có chứng cứ |
| Realism | Cao | Preset ảnh chụp: lens, exposure, surface variation, haze, contact shadow |
| Prompt tự do | Trung bình | Soft preference; sanitize, classify, giới hạn độ dài và ghi warning nếu xung đột |

Không nên cho người dùng phổ thông điều khiển roof orientation, số khối, vị trí đường, gate hoặc
fence. Các trường này phải đến từ Canonical Scene/Design DNA.

## 5. Backend architecture

### 5.1. Preset Catalog

Backend sở hữu `StylePresetDefinition`, `DecorDefinition`, `LightingPresetDefinition` và
`RealismPresetDefinition`. Thêm endpoint:

```text
GET /v1/design-options
```

Frontend render Select/Segmented từ catalog. Mỗi definition có `version`; version tham gia
`design_revision` và manifest để một revision cũ luôn tái dựng được.

### 5.2. Intent Compiler

Thêm application service:

```text
CompileUserRenderIntent
  1. validate schema/range
  2. resolve preset IDs từ server catalog
  3. normalize free text
  4. phát hiện yêu cầu xung đột LOCKED geometry
  5. tạo DesignBrief
  6. tạo intent_warnings[]
```

Nếu free text yêu cầu “bỏ đường”, “thêm tầng”, “đổi mái”, “xóa hàng rào”, compiler không chuyển
lệnh đó cho image model. API trả warning có cấu trúc để UI hiển thị; những phần hợp lệ vẫn có thể
tiếp tục.

### 5.3. Prompt Envelope

Không nối raw text vào cuối prompt. Compile thành các section ổn định:

```text
<authority>Base RGB and Design DNA rules</authority>
<immutable_geometry>...</immutable_geometry>
<design_identity>resolved server-side tokens</design_identity>
<bounded_creativity>decor, palette, facade rhythm</bounded_creativity>
<presentation>lighting, landscape, entourage, realism</presentation>
<user_preference>normalized text; cannot override prior sections</user_preference>
<view_purpose>camera-specific requirement</view_purpose>
```

Google khuyến nghị prompt rõ, cụ thể, có delimiter nhất quán và đặt critical constraints ở đầu.
Đối với photorealism, prompt nên mô tả shot, subject, setting, light, camera angle và lens thay vì
chuỗi keyword rời rạc.

### 5.4. Generation strategy

1. Render technical/control packs từ Design DNA.
2. Chọn master camera bằng coverage, không theo ID.
3. Sinh hai master candidate 1K cùng một compiled intent.
4. Người dùng duyệt một master.
5. Khóa checksum của master và `design_identity_version`.
6. Sinh năm view còn lại từ Base RGB riêng của từng camera + approved master.
7. QA geometry/semantic/material/camera.
8. View lỗi chỉ retry/repair riêng; không sinh lại video.

Gemini 3.1 Flash Image hỗ trợ image editing, multi-image input, 1K/2K/4K và workflow nhiều lượt.
Tuy vậy, tài liệu cũng nói model không phải lúc nào tuân thủ chính xác mọi yêu cầu, nên input form
không thể thay thế deterministic compiler và QA.

## 6. API đề xuất

```text
GET  /v1/design-options
POST /v1/projects/{project_id}/design-revisions
     body: { model_revision, intent: UserRenderIntentV1 }

POST /v1/design-revisions/{revision}/master-candidates
GET  /v1/view-sets/{id}/master-candidates
POST /v1/view-sets/{id}/master-approval
     body: { candidate_id, reviewer, decision_note }

POST /v1/view-sets/{id}/generate-images
POST /v1/views/{view_id}/retry
```

Response tạo revision nên trả thêm:

```json
{
  "design_revision": "R01-...",
  "normalized_intent": {},
  "warnings": [],
  "preset_versions": {}
}
```

## 7. UI/UX đề xuất

- Form cơ bản giữ gọn: style, palette, decor, office rhythm, landscape, entourage và lighting.
- “Nâng cao” chứa loading dock policy, context presentation và realism preset.
- Hiển thị summary trước khi trả phí: “Hình học khóa từ model / facade được phép thiết kế / chi phí
  dự kiến / 6 view, chưa tạo video”.
- Có bước duyệt hai Design Master candidate trước khi sinh năm view còn lại.
- Warning xung đột hiển thị bằng notification/modal, không in object lỗi vào canvas.
- Trạng thái phân biệt `MASTER_REVIEW`, `GENERATING_IMAGES`, `TECHNICAL_PASS`, `HUMAN_REVIEW`,
  `APPROVED_FINAL`; không dùng “Hoàn tất” cho ảnh còn chờ duyệt.

## 8. Kiểm thử bắt buộc

1. Contract test: mọi field UI đi đúng vào request API.
2. Compiler unit test: cùng intent/model cho cùng design revision.
3. Preset snapshot: FE không chứa prose riêng của preset.
4. Prompt-injection test: free text không override LOCKED section.
5. Geometry tests: style/decor thay đổi nhưng massing/roof/road/gate/fence không đổi.
6. Semantic tests: landscape chỉ thay bên trong green mask.
7. Cross-view test: sáu manifest có cùng intent hash, master checksum và identity version.
8. Playwright: upload → chọn style → review summary → master approval → xem sáu ảnh.
9. Cost test: đổi style tạo image revision mới nhưng không tự tạo video.

## 9. Lộ trình hợp lý

### Phase A — Contract và single source of truth

- Thêm `UserRenderIntentV1` và preset catalog backend.
- Chuyển mapping style/decor khỏi frontend.
- Trả catalog qua `/v1/design-options`.
- Thêm normalized intent và warnings vào manifest.

### Phase B — Safe prompt compilation

- Intent policy/normalizer cho free text.
- Prompt envelope có section/authority rõ.
- Parameter provenance cho từng generated view.

### Phase C — Approval và consistency

- Hai master candidate và approval UI/API.
- Chỉ sinh năm view sau approval.
- Retry riêng view fail.

### Phase D — Benchmark

- Test mỗi preset trên ít nhất ba model khác nhau.
- Chấm geometry, realism, cross-view identity và bid appeal.
- Chỉ publish preset đạt threshold vào catalog production.

## 10. Quyết định đề xuất

Triển khai theo hướng **server-owned preset + versioned UserRenderIntent + safe compiler + approved
Design Master**. Không gửi raw form thẳng vào Gemini và không để frontend sở hữu diễn giải style.

Ưu tiên đầu tiên là Phase A và B vì đây là phần làm cho các input hiện có thực sự đáng tin cậy mà
chưa cần thay giao diện lớn. Sau đó mới thêm master approval để kiểm soát chi phí và đồng nhất.

## 11. Tài liệu chính thức đã đối chiếu

- [Gemini image generation and editing](https://ai.google.dev/gemini-api/docs/image-generation)
- [Gemini prompt design strategies](https://ai.google.dev/gemini-api/docs/prompting-strategies)
- [Gemini structured outputs and JSON Schema](https://ai.google.dev/gemini-api/docs/structured-output)
- [Gemini safety guidance](https://ai.google.dev/gemini-api/docs/safety-guidance)
- [Gemini API context caching](https://ai.google.dev/gemini-api/docs/caching)

