# DEVELOPMENT PLAN — V365 INDUSTRIAL DESIGN IMAGE GENERATION & EDITING

## 1. Mục tiêu giai đoạn phát triển tiếp theo

Hệ thống cần giải quyết đồng thời hai bài toán chính:

### 1.1. Photorealistic Industrial Image Generation
Từ Site Model / LOD100 và Design DNA, hệ thống phải sinh ra bộ ảnh nhà xưởng có chất lượng gần ảnh chụp thật, đủ để:
- Trình bày với chủ đầu tư.
- So sánh phương án thiết kế.
- Dùng trong proposal / brochure / sales deck.
- Giữ đồng nhất thiết kế giữa nhiều góc nhìn.

### 1.2. Interactive Image Editing
Người dùng có thể thao tác trực tiếp trên ảnh:
- Click.
- Marker.
- Box.
- Brush.
- Lasso.
- Text prompt.
- Exemplar selection.

Sau đó yêu cầu:
- đổi màu,
- đổi vật liệu,
- thay cửa,
- xóa cây,
- thêm canopy,
- chỉnh chi tiết kiến trúc,
- áp dụng cho các object tương tự.

Hệ thống phải phân biệt:
- **Visual Edit**: preview nhanh trên ảnh.
- **Design Edit**: cập nhật thật vào Design DNA / Blender Scene.

---

# 2. Kiến trúc mục tiêu

```text
LOD100 / Site Model
        ↓
Design DNA
        ↓
Semantic Scene Graph
        ↓
Procedural Industrial Scene
        ↓
Blender 4.5 LTS
        ↓
Structural Render
        ├── RGB
        ├── Depth
        ├── Normal
        ├── Object ID
        ├── Cryptomatte
        └── Camera Metadata
        ↓
Style Reference Pack
        ↓
Prompt Compiler
        ↓
Model Router
        ├── Gemini 3.1 Flash Image → Preview / Editing
        └── Gemini 3 Pro Image     → Final / Hero Image
        ↓
Photoreal QA
        ↓
Final Image
        ↓
User Selection
        ↓
SAM3 Selection Layer
        ↓
Object Resolver
        ↓
Semantic Object ID
        ↓
Change Planner
        ├── Visual Edit
        │      ↓
        │   Local AI Edit
        │
        └── Design Edit
               ↓
          Update Design DNA
               ↓
          Blender Regenerate
               ↓
          Regional Render
               ↓
          AI Refinement
               ↓
          Multi-view Propagation
```

---

# 3. Nguyên tắc kiến trúc

## 3.1. Blender là nguồn sự thật về geometry
Blender chịu trách nhiệm:
- vị trí công trình,
- footprint,
- roof shape,
- đường giao thông,
- object layout,
- camera,
- kích thước,
- tỷ lệ,
- các thành phần kiến trúc chính.

AI không được tự quyết định lại các phần này.

## 3.2. Gemini là Appearance Engine
Gemini chịu trách nhiệm:
- material realism,
- ánh sáng,
- atmosphere,
- vegetation realism,
- micro-detail,
- weathering,
- photographic finishing.

Không dùng Gemini như source of truth cho geometry.

## 3.3. SAM3 là Selection Engine
SAM3 chịu trách nhiệm:
- hiểu vùng user đang chọn,
- tạo mask,
- chọn object bằng point / box / text / exemplar,
- hỗ trợ group selection.

SAM3 không trực tiếp sửa ảnh.

## 3.4. Object Resolver là cầu nối giữa ảnh và 3D scene
SAM3 chỉ biết pixel.

Object Resolver phải trả lời:

```text
Mask này tương ứng object nào trong Blender?
```

Input:
- SAM3 mask,
- Object ID,
- Cryptomatte,
- camera metadata,
- depth.

Output:
- semantic object ID.

Ví dụ:

```text
WH01.facade_north.door_003
```

## 3.5. Design DNA là nguồn sự thật của thiết kế
Structural edit phải update Design DNA.

Ví dụ:

```json
{
  "id": "WH01.facade_north.door_003",
  "type": "roller_shutter",
  "width": 4.0,
  "height": 4.5,
  "color": "dark_gray"
}
```

---

# 4. Workstream A — Photorealistic Generation

## A1. Benchmark Gemini

### Mục tiêu
Xác định:
- Flash hay Pro phù hợp.
- Style reference có tác động thế nào.
- Multi-turn có thực sự cần.

### Test matrix

| Test | Model | Style Ref | Turns |
|---|---|---|---|
| A | Gemini 3.1 Flash | Không | 1 |
| B | Gemini 3.1 Flash | Có | 1 |
| C | Gemini 3.1 Flash | Có | 2 |
| D | Gemini 3 Pro Image | Không | 1 |
| E | Gemini 3 Pro Image | Có | 1 |
| F | Gemini 3 Pro Image | Có | 2 |

Mỗi test:
- 4 outputs.
- Tổng: 24 images.

### Chấm điểm
- Photorealism.
- Geometry preservation.
- Industrial realism.
- Material realism.
- Lighting realism.
- CGI residual.
- Business presentation quality.

### Deliverable
```text
benchmark_report.md
benchmark_results/
```

---

## A2. Style Reference Pack

Chuẩn hóa style:

```text
style_packs/
    modern_industrial_blue/
        architecture.png
        material.png
        lighting.png
        style.json
```

Style JSON gồm:
- photography style,
- material language,
- lighting,
- atmosphere,
- vegetation,
- traffic density,
- color palette.

---

## A3. Prompt Compiler

Không dùng prompt hardcode.

Prompt được build từ:
- Design DNA.
- Camera DNA.
- Style Pack.
- Geometry constraints.
- Negative CGI cues.
- User customization.

Các nhóm prompt:
1. Geometry lock.
2. Appearance reinterpretation.
3. Reference interpretation.
4. Photography target.
5. Industrial realism.
6. Anti-CGI constraints.

---

## A4. Model Router

### Preview
```text
Gemini 3.1 Flash Image
1K / 2K
```

### Final
```text
Gemini 3 Pro Image
2K / 4K
```

### Multi-turn
Chỉ dùng khi QA fail.

Rule:

```text
Preview:
1 turn default
max 2 turns

Final:
1 turn default
max 2 turns
```

---

## A5. Photoreal QA

QA cần phát hiện:
- CGI lighting.
- Plastic vegetation.
- Uniform materials.
- Clean concrete quá mức.
- Geometry drift.
- Missing object.
- Strange vehicles.
- Changed camera perspective.

Output:

```json
{
  "status": "pass",
  "photoreal_score": 4.4,
  "geometry_score": 4.8,
  "issues": []
}
```

Nếu fail:
- tạo targeted refinement prompt.
- chạy turn 2.

---

# 5. Workstream B — Interactive Image Editing

## B1. Frontend Interaction Layer

User hỗ trợ:
- Click.
- Box.
- Brush.
- Lasso.
- Text.
- Exemplar.

Actions:
- Preview Edit.
- Apply to Design.
- Apply to Similar.
- Undo.
- Redo.

---

## B2. SAM3 Selection Service

### Input
- image,
- prompt type,
- points / box / text / exemplar.

### Output
- mask(s),
- score,
- optional semantic concept.

### Modes

#### Point / Box
MVP.

#### Text
Ví dụ:

```text
select all loading doors
```

#### Exemplar
User chọn một object:

```text
find similar objects
```

#### Group
Bulk edit.

---

## B3. Selection Mask Refinement

Với ảnh 2K/4K:

```text
Full Image
    ↓
SAM3 rough selection
    ↓
Crop object + context
    ↓
Second-pass segmentation
    ↓
Accurate high-resolution mask
```

Mask preprocessing:
- dilation,
- feather,
- edge refinement.

---

## B4. Object Resolver

### Input
```text
SAM3 Mask
+
Object ID Pass
+
Cryptomatte
+
Depth
+
Camera
```

### Algorithm
1. Project Blender object masks.
2. Calculate overlap with SAM3 mask.
3. Rank candidates.
4. Resolve semantic ID.
5. If ambiguous → ask user confirmation.

Example:

```text
Door_001 = 0.04
Door_002 = 0.11
Door_003 = 0.89 ← resolved
Window_004 = 0.02
```

---

## B5. Change Planner

User:

```text
Đổi cửa này thành cửa cuốn màu xám.
```

Output:

```json
{
  "mode": "design_edit",
  "operation": "replace_asset",
  "target": "WH01.facade_north.door_003",
  "parameters": {
    "family": "roller_shutter",
    "color": "dark_gray"
  }
}
```

Supported operations:
- change_color
- change_material
- replace_asset
- resize
- move
- delete
- add
- bulk_change

---

# 6. Visual Edit vs Design Edit

## 6.1. Visual Edit

Dùng cho:
- preview nhanh,
- màu,
- vật liệu,
- landscaping,
- object nhỏ.

Pipeline:

```text
SAM3 Mask
    ↓
Local Crop
    ↓
Gemini / Imagen Edit
    ↓
Composite
    ↓
Preview
```

Không update Design DNA.

## 6.2. Design Edit

Dùng cho:
- thay cửa,
- tăng kích thước,
- thêm canopy,
- thay opening,
- thay đổi geometry.

Pipeline:

```text
SAM3
 ↓
Object Resolver
 ↓
Semantic ID
 ↓
Change Planner
 ↓
Design DNA
 ↓
Blender Regenerate
 ↓
Regional Render
 ↓
Gemini Refinement
 ↓
Updated Image
```

---

# 7. Multi-view Propagation

Hệ thống có 6 camera chuẩn:

```text
CAM_01_HERO_AERIAL
CAM_02_MAIN_ENTRANCE
CAM_03_LOGISTICS_OPERATION
CAM_04_REVERSE_AERIAL
CAM_05_ARCH_DETAIL
CAM_06_MARKETING_GOLDEN_HOUR
```

Sau khi edit một object:

```text
Object
  ↓
Visibility Resolver
  ↓
affected cameras
```

Ví dụ:

```text
Door_003:
CAM_02 = visible
CAM_04 = visible
CAM_05 = visible
```

Chỉ re-render các camera bị ảnh hưởng.

---

# 8. Semantic Object Registry

Mọi object quan trọng phải có stable ID.

Không dùng:

```text
Cube.003
Object.291
```

Dùng:

```text
WH01.facade_north.door_003
WH01.office.canopy_001
WH01.site.tree_018
```

Metadata:

```json
{
  "semantic_id": "WH01.facade_north.door_003",
  "type": "industrial_door",
  "family": "opening",
  "visible_in": [
    "CAM_02",
    "CAM_04",
    "CAM_05"
  ]
}
```

---

# 9. Edit History

Mỗi edit lưu thành event:

```json
{
  "edit_id": "edit_001",
  "design_id": "factory_001",
  "source_camera": "CAM_05",
  "target": "WH01.facade_north.door_003",
  "instruction": "Đổi thành cửa cuốn màu xám",
  "operation": "replace_asset",
  "status": "committed"
}
```

Hỗ trợ:
- undo,
- redo,
- version compare,
- design history.

---

# 10. Kiến trúc dịch vụ

```text
Frontend
   │
   ▼
API Gateway
   │
   ├─────────────── SAM3 Service
   │                       │
   │                       ▼
   │                Mask / Selection
   │
   ├─────────────── Object Resolver
   │
   ├─────────────── Change Planner
   │
   ├─────────────── Visual Edit Service
   │                       │
   │                 Gemini / Imagen
   │
   ├─────────────── Design Service
   │                       │
   │                  Design DNA
   │
   ├─────────────── Blender Worker
   │
   ├─────────────── QA Service
   │
   └─────────────── Storage / Metadata
```

---

# 11. Stack đề xuất

## Frontend
- React / Next.js.
- Konva.js hoặc Fabric.js.
- WebSocket.

## Backend
- FastAPI.
- Redis.
- Celery / Dramatiq / RQ.

## AI
- SAM3.
- Gemini 3.1 Flash Image.
- Gemini 3 Pro Image.
- Imagen explicit-mask editing nếu cần.

## Rendering
- Blender 4.5 LTS.
- Cycles.
- Python automation.

## Storage
- PostgreSQL.
- S3 / MinIO.
- Redis cache.

---

# 12. Roadmap phát triển

## Phase 0 — Benchmark Photoreal Pipeline
**Thời gian:** 1–2 ngày

Tasks:
- [ ] Kiểm tra Gemini model hiện tại.
- [ ] Chuẩn bị 1 baseline render.
- [ ] Chuẩn bị 3 style reference.
- [ ] Build prompt benchmark.
- [ ] Generate 24 outputs.
- [ ] Chấm chất lượng.
- [ ] Chốt Flash / Pro / Multi-turn.

### Exit Criteria
Có model strategy rõ ràng.

---

## Phase 1 — Photoreal Generation v1
**Thời gian:** 4–7 ngày

Tasks:
- [ ] Style Pack.
- [ ] Prompt Compiler.
- [ ] Model Router.
- [ ] Flash Preview.
- [ ] Pro Final.
- [ ] Generation logging.
- [ ] QA checklist.

### Exit Criteria
Ảnh final không còn cảm giác CGI rõ ràng và geometry được giữ.

---

## Phase 2 — SAM3 Editing MVP
**Thời gian:** 5–7 ngày

Tasks:
- [ ] SAM3 inference service.
- [ ] Point selection.
- [ ] Box selection.
- [ ] Mask overlay.
- [ ] Mask refinement.
- [ ] Local crop edit.
- [ ] Gemini / Imagen edit.
- [ ] Composite.
- [ ] Undo / redo.

### Exit Criteria
User click đúng một object và edit được đúng vùng.

---

## Phase 3 — Object Grounding
**Thời gian:** 5–7 ngày

Tasks:
- [ ] Export Object ID.
- [ ] Export Cryptomatte.
- [ ] Stable semantic IDs.
- [ ] Object Resolver.
- [ ] Mapping SAM3 mask → semantic object.
- [ ] Ambiguity handling.

### Exit Criteria
System biết chính xác user đang edit object nào trong Blender.

---

## Phase 4 — Design-aware Editing
**Thời gian:** 7–10 ngày

Tasks:
- [ ] Change Planner.
- [ ] Structured edit schema.
- [ ] Update Design DNA.
- [ ] Blender regeneration.
- [ ] Regional render.
- [ ] Photoreal refinement.
- [ ] Edit history.

### Exit Criteria
Structural edit cập nhật thật vào thiết kế.

---

## Phase 5 — Multi-view Propagation
**Thời gian:** 5–10 ngày

Tasks:
- [ ] Camera visibility map.
- [ ] Impacted-view resolver.
- [ ] Incremental rerender.
- [ ] AI refine từng view.
- [ ] Cross-view QA.

### Exit Criteria
Edit một object → tất cả view liên quan cập nhật đúng.

---

## Phase 6 — Advanced SAM3
**Thời gian:** sau MVP

Tasks:
- [ ] Text-guided selection.
- [ ] Select all similar.
- [ ] Exemplar search.
- [ ] Bulk edit.
- [ ] Apply-to-similar workflow.

Example:

```text
"Chọn tất cả cửa loading và đổi màu sang xám."
```

---

# 13. Milestone đề xuất

## Milestone 1 — Photoreal Proof
Có ít nhất một phương án đạt chất lượng ảnh trình chủ đầu tư.

## Milestone 2 — Interactive Edit Demo
Click vào cửa → đổi màu / vật liệu.

## Milestone 3 — Design-aware Demo
Click cửa → đổi thành cửa cuốn → Blender cập nhật.

## Milestone 4 — Multi-view Demo
Edit một cửa → ba camera liên quan tự cập nhật.

## Milestone 5 — Semantic Bulk Edit
"Đổi tất cả loading doors sang màu xám."

---

# 14. KPI kỹ thuật

## Generation
- Photorealism score.
- Geometry preservation score.
- CGI residual score.
- Average generation latency.
- Cost / final image.

## Selection
- Mask IoU.
- Object grounding accuracy.
- User correction rate.

## Editing
- Edit locality.
- Outside-mask modification rate.
- Structural edit success rate.

## Multi-view
- Cross-view object consistency.
- Re-render success rate.
- Average propagation time.

---

# 15. Rủi ro chính

## Risk 1 — Gemini vẫn giữ CGI look
Mitigation:
- style references,
- prompt compiler,
- Pro benchmark,
- better scene semantics.

## Risk 2 — SAM3 mask đúng nhưng object mapping sai
Mitigation:
- Object ID + Cryptomatte + depth,
- confidence threshold,
- user confirmation.

## Risk 3 — AI edit làm thay đổi vùng khác
Mitigation:
- local crop,
- explicit mask,
- compositing,
- preserve original outside mask.

## Risk 4 — Structural edit làm mất consistency
Mitigation:
- mọi structural edit update Design DNA,
- không dùng image-only edit làm design truth.

## Risk 5 — Multi-view quá chậm
Mitigation:
- visibility resolver,
- regional render,
- chỉ update affected cameras.

---

# 16. Thứ tự ưu tiên nên làm ngay

```text
1. Benchmark Gemini
2. Chốt photoreal generation pipeline
3. SAM3 point/box editing
4. Local masked edit
5. Object Resolver
6. Stable semantic ID
7. Design Edit
8. Multi-view propagation
9. SAM3 text/exemplar bulk edit
```

---

# 17. Target workflow cuối cùng

```text
User load Site Model
        ↓
System generate Design DNA
        ↓
Blender build industrial scene
        ↓
Generate 6 standard cameras
        ↓
Gemini photorealization
        ↓
User xem ảnh
        ↓
Click một cửa
        ↓
SAM3 chọn đúng cửa
        ↓
User nói:
"Đổi thành cửa cuốn màu xám"
        ↓
System tạo preview nhanh
        ↓
User chọn Apply to Design
        ↓
Design DNA update
        ↓
Blender regenerate
        ↓
Affected views rerender
        ↓
Gemini refinement
        ↓
6-view design package updated
```

---

# 18. Định hướng sản phẩm

Thông điệp kiến trúc của sản phẩm:

> **User edits the image, but the system edits the design.**

Khác biệt của V365 không nằm ở việc chỉ generate ảnh đẹp.

Giá trị chính là:

```text
Site Model
→ Design
→ Photoreal Visualization
→ Interactive Editing
→ Persistent Design Change
→ Multi-view Consistency
```

Đây là hướng phát triển nên được giữ xuyên suốt cho các phase tiếp theo.
