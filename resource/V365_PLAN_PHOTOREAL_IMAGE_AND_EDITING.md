# PLAN THỬ NGHIỆM & TRIỂN KHAI — PHOTOREALISTIC INDUSTRIAL IMAGE + IMAGE EDITING

## 1. Mục tiêu

Dự án cần giải quyết song song 2 bài toán:

1. **Sinh ảnh nhà xưởng công nghiệp có chất lượng gần ảnh chụp thật**
   - Giữ đúng geometry/layout của site model.
   - Giữ camera, tỷ lệ, hình khối chính.
   - Giảm cảm giác CGI/archviz.
   - Có thể dùng style reference để định hướng chất lượng hình ảnh.
   - Có bản Preview nhanh và bản Final chất lượng cao.

2. **Cho phép người dùng thao tác trực tiếp trên ảnh để chỉnh sửa**
   - Click / marker / rectangle / brush / lasso.
   - Chỉnh đúng đối tượng người dùng chọn.
   - Có 2 loại edit:
     - Visual edit: sửa nhanh trên ảnh.
     - Design edit: cập nhật ngược vào Design DNA / Blender scene.
   - Hỗ trợ propagation sang các camera/view khác.

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
        ├── Beauty RGB
        ├── Depth
        ├── Normal
        ├── Object ID / Cryptomatte
        └── Metadata
        ↓
Style Reference Pack
        ↓
Prompt Compiler
        ↓
Model Router
        ├── Gemini 3.1 Flash Image → Preview / Edit
        └── Gemini 3 Pro Image     → Final / Hero Image
        ↓
Photoreal QA
        ↓
Final Image
        ↓
User Selection
        ├── Click
        ├── Box
        ├── Brush
        └── Lasso
        ↓
Selection Mask / Object Resolver
        ↓
        ├── Visual Edit
        │      ↓
        │   Gemini Local Edit
        │
        └── Design Edit
               ↓
          Update Design DNA
               ↓
          Blender Regenerate
               ↓
          Regional Render
               ↓
          Gemini Refinement
```

---

# 3. Nguyên tắc thiết kế

## 3.1. Blender là nguồn sự thật về geometry

Blender cần đảm bảo:

- Layout.
- Building footprint.
- Roof shape.
- Road topology.
- Camera.
- Khoảng cách giữa các khối.
- Các object chính.
- Các object cần chỉnh sửa về sau.

Blender **không cần đạt photoreal 100%**.

Mục tiêu hợp lý:

```text
Geometry accuracy     = 100%
Composition accuracy  = 100%
Object layout         = 100%
Appearance realism    = 50–70%
```

AI chịu trách nhiệm phần còn lại:

- Material micro-detail.
- Surface variation.
- Weathering nhẹ.
- Vegetation realism.
- Atmosphere.
- Photographic lighting.
- Lens / camera feeling.
- Final image finishing.

---

## 3.2. Không để CGI render trở thành style reference ngoài ý muốn

Ảnh Blender được dùng với vai trò:

> GEOMETRY REFERENCE ONLY

Style cần lấy từ các ảnh tham chiếu riêng.

Ví dụ:

```text
Image 1 = Blender structural render
Image 2 = target industrial photography style
Image 3 = target facade/material style
Image 4 = target lighting/environment style
```

Prompt phải nói rõ:

```text
Do NOT preserve the rendering style of Image 1.
Preserve only geometry, composition, camera and layout.
Use Images 2–4 as appearance references only.
```

---

# 4. Giai đoạn P0 — Benchmark model trước khi refactor

## Mục tiêu

Xác định:

- Gemini Flash có đủ không.
- Gemini Pro có tạo bước nhảy chất lượng đáng kể không.
- Style references có tạo khác biệt lớn không.
- Multi-turn có đáng tiền không.

## Input cố định

Chọn duy nhất:

- 1 Blender render tốt nhất hiện tại.
- 3 style references chất lượng tốt.
- 1 prompt chuẩn.
- 1 camera.
- 1 Design DNA.

Tuyệt đối không thay đổi input giữa các test.

## Ma trận thử nghiệm

| Test | Model | Style Reference | Multi-turn |
|---|---|---|---|
| A | Gemini 3.1 Flash Image | Không | 1 turn |
| B | Gemini 3.1 Flash Image | Có | 1 turn |
| C | Gemini 3.1 Flash Image | Có | 2 turns |
| D | Gemini 3 Pro Image | Không | 1 turn |
| E | Gemini 3 Pro Image | Có | 1 turn |
| F | Gemini 3 Pro Image | Có | 2 turns |

Mỗi config generate:

```text
4 candidates
```

Tổng:

```text
6 configs × 4 = 24 images
```

## Tiêu chí chấm

Mỗi ảnh chấm 0–5:

```text
Photorealism
Geometry preservation
Industrial realism
Material realism
Lighting realism
Vegetation realism
Business presentation quality
CGI residual score
```

Trong đó:

```text
CGI residual score:
0 = không còn cảm giác CGI
5 = CGI rất rõ
```

## Quyết định sau benchmark

### Trường hợp 1

```text
Pro + references + 1 turn
```

đã đạt gần target.

→ Không cần multi-turn mặc định.

### Trường hợp 2

```text
Pro + references + 2 turns
```

tốt hơn rõ rệt.

→ Chỉ dùng turn 2 khi QA fail.

### Trường hợp 3

Ngay cả Pro vẫn CGI.

→ Vấn đề không còn là model.

Cần xử lý:

- Scene semantics.
- Style references.
- Prompt.
- Material cues.
- Camera.
- AI conditioning.
- Hoặc bổ sung ControlNet / diffusion workflow.

---

# 5. Prompt Compiler v1

Không hardcode một prompt ngắn kiểu:

```text
Make this render photorealistic.
```

Thay vào đó build prompt từ nhiều phần.

## 5.1. Geometry constraints

```text
IMAGE 1 is the authoritative DESIGN GEOMETRY reference.

Preserve exactly:
- camera position
- camera perspective
- building count
- building position
- building footprint
- roof geometry
- main facade proportions
- road topology
- logistics yard layout

Do not add, remove, move or resize major architectural masses.
```

## 5.2. Appearance instruction

```text
Do NOT preserve the CGI rendering style of Image 1.

Completely reinterpret:
- materials
- surface response
- environment
- atmosphere
- vegetation appearance
- photographic characteristics
```

## 5.3. Style reference rule

```text
Images 2–4 are APPEARANCE REFERENCES ONLY.

Use them for:
- lighting
- material realism
- industrial photography style
- vegetation realism
- atmospheric tone

Do not copy their geometry or layout.
```

## 5.4. Industrial photography target

```text
Create a high-end real-world drone photograph
of a modern operating industrial factory complex.

The result must look like a professional industrial
site photograph, not architectural visualization.
```

## 5.5. Realism cues

```text
Use:
- physically believable corrugated metal
- realistic concrete variation
- non-uniform roughness
- subtle weathering
- natural glass reflections
- imperfect grass edges
- realistic trucks
- believable industrial utility details
- soft atmospheric haze
- physically plausible sunlight and shadows
```

## 5.6. Anti-CGI prompt

```text
Avoid:
- CGI appearance
- 3D render look
- architectural visualization style
- plastic vegetation
- perfectly uniform surfaces
- perfect grass borders
- sterile roads
- over-sharpening
- excessive HDR
- artificial global illumination look
- miniature effect
```

---

# 6. Multi-turn strategy

## Không dùng multi-turn theo kiểu

```text
Turn 1: make realistic
Turn 2: more realistic
Turn 3: even more realistic
Turn 4: more photorealistic
```

Cách này gây:

- Drift.
- Over-processing.
- Geometry mutation.
- AI look.
- Chi phí tăng.

## Chiến lược đúng

### Turn 1

Generate near-final image.

### QA

Phân tích lỗi còn lại.

Ví dụ:

```text
- vegetation synthetic
- concrete too clean
- roof too uniform
- CGI lighting
```

### Turn 2

Chỉ fix lỗi cụ thể:

```text
Preserve all architecture, camera and composition.

Improve only:
- concrete surface variation
- vegetation realism
- subtle metal weathering
- photographic lighting characteristics

Do not redesign any object.
```

## Production rule

```text
Preview:
Flash
1 turn default
max 2 turns

Final:
Pro
1 turn default
max 2 turns only if QA fails
```

---

# 7. Model Router

## Preview mode

Dùng:

```text
Gemini 3.1 Flash Image
```

Mục tiêu:

- Interactive.
- Nhanh.
- Chi phí thấp.
- User thử màu/phong cách.
- User thay Design DNA.

Resolution:

```text
1K hoặc 2K
```

## Finalize mode

Dùng:

```text
Gemini 3 Pro Image
```

Mục tiêu:

- Hero image.
- Ảnh trình chủ đầu tư.
- Ảnh marketing.
- Output cuối.

Resolution:

```text
2K mặc định
4K khi export final
```

---

# 8. Style Reference Pack

## Cấu trúc

```text
style_packs/
    industrial_modern_vietnam/
        architecture_01.png
        lighting_01.png
        material_01.png
        style.json

    industrial_logistics_blue/
        architecture_01.png
        lighting_01.png
        material_01.png
        style.json
```

## style.json

Ví dụ:

```json
{
  "id": "industrial_logistics_blue",
  "photography": {
    "shot": "drone oblique",
    "lens_equivalent": "35mm",
    "lighting": "soft late afternoon",
    "contrast": "moderate",
    "white_balance": "neutral"
  },
  "materials": {
    "facade": "blue corrugated metal",
    "roof": "light grey",
    "yard": "industrial concrete"
  },
  "environment": {
    "vegetation": "low density",
    "atmosphere": "subtle haze",
    "traffic": "medium"
  }
}
```

---

# 9. Blender output cần bổ sung

Mỗi camera render ra một folder:

```text
renders/
    design_001/
        cam_01/
            beauty.png
            depth.exr
            normal.exr
            object_id.exr
            cryptomatte.exr
            metadata.json

        cam_02/
            ...
```

## metadata.json

```json
{
  "camera_id": "cam_01",
  "design_id": "design_001",
  "objects": {
    "184": "WH01.facade_north.door_003",
    "185": "WH01.facade_north.window_004"
  }
}
```

---

# 10. Image Editing MVP

## Mục tiêu

User có thể:

- Click.
- Marker.
- Box.
- Brush.
- Lasso.

Sau đó nhập:

```text
"Đổi cửa này thành màu đen"
```

hoặc:

```text
"Đổi cửa này thành cửa cuốn"
```

---

# 11. Selection pipeline

Frontend gửi:

```json
{
  "image_id": "design_001_cam_01",
  "selection": {
    "type": "point",
    "x": 0.65,
    "y": 0.74
  },
  "instruction": "Đổi cửa này thành cửa cuốn màu xám"
}
```

Backend:

```text
Selection
    ↓
Mask generator
    ↓
Object Resolver
    ↓
Semantic Object ID
```

Ví dụ:

```text
WH01.facade_north.door_003
```

---

# 12. Hai loại edit

## 12.1. Visual Edit

Dùng khi:

- đổi màu.
- thử vật liệu.
- xóa vật nhỏ.
- thay cây.
- đổi chi tiết trang trí.
- preview nhanh.

Flow:

```text
User selection
    ↓
Mask
    ↓
Crop
    ↓
Gemini Flash local edit
    ↓
Blend
    ↓
Preview
```

Không update Blender.

UI nên hiển thị:

```text
PREVIEW ONLY
```

---

## 12.2. Design Edit

Dùng khi:

- đổi loại cửa.
- tăng kích thước cửa.
- xóa cửa.
- thêm canopy.
- đổi roof element.
- thay khối kiến trúc.
- thay vị trí asset quan trọng.

Flow:

```text
User selection
    ↓
Semantic ID
    ↓
Change Planner
    ↓
Structured Operation
    ↓
Update Design DNA
    ↓
Regenerate Blender Object
    ↓
Regional Render
    ↓
Gemini local refinement
    ↓
Final
```

---

# 13. Change Planner

Input:

```text
"Đổi cửa này thành cửa cuốn màu xám"
```

Output:

```json
{
  "operation": "replace_opening",
  "target": "WH01.facade_north.door_003",
  "parameters": {
    "door_type": "roller_shutter",
    "color": "dark_gray"
  }
}
```

---

# 14. Stable Semantic ID

Không dùng:

```text
Cube.003
Door.018
Object.921
```

Dùng:

```text
WH01.NF.B05.D01
```

hoặc:

```text
WH01.facade_north.door_003
```

ID phải deterministic.

Sau regenerate:

```text
WH01.facade_north.door_003
```

vẫn giữ nguyên.

---

# 15. Multi-view propagation

Giả sử một cửa xuất hiện ở:

```text
Camera A ✓
Camera B ✓
Camera C ✗
Camera D ✓
```

Sau khi edit:

```text
Door_003 changed
        ↓
Visibility Resolver
        ↓
A → rerender
B → rerender
C → skip
D → rerender
```

Sau đó:

```text
regional render
+
Gemini refinement
```

cho từng camera.

---

# 16. QA pipeline

## QA geometry

Check:

```text
- building count changed?
- roof shape changed?
- road boundary changed?
- facade proportion drifted?
- camera perspective changed?
```

## QA visual

Check:

```text
- remaining CGI look
- plastic vegetation
- unrealistic vehicles
- excessive cleanliness
- repetitive texture
- over-sharp edges
- lighting mismatch
- inconsistent shadows
```

## QA edit

Check:

```text
- only selected object changed?
- neighboring objects unchanged?
- selected object matches instruction?
- mask blending artifacts?
```

---

# 17. Metrics

## Photoreal generation

Track:

```text
Photorealism Score
Geometry Preservation Score
Industrial Realism Score
CGI Residual Score
Style Match Score
Human Preference Score
```

## Editing

Track:

```text
Selection accuracy
Object resolution accuracy
Edit locality
Unwanted change rate
Geometry consistency
Cross-view consistency
Average edit latency
```

---

# 18. Phase plan

## P0 — Benchmark

Duration:

```text
1–2 days
```

Tasks:

- [ ] Confirm current Gemini model.
- [ ] Prepare 1 Blender baseline image.
- [ ] Prepare 3 style references.
- [ ] Build benchmark prompt.
- [ ] Generate 24 images.
- [ ] Score all outputs.
- [ ] Decide Flash vs Pro usage.
- [ ] Decide if multi-turn adds enough value.

Deliverable:

```text
benchmark_report.md
benchmark_results/
```

---

## P1 — Photoreal Pipeline v1

Duration:

```text
3–5 days
```

Tasks:

- [ ] Add Style Reference Pack.
- [ ] Build Prompt Compiler.
- [ ] Add Model Router.
- [ ] Add Flash Preview.
- [ ] Add Pro Final.
- [ ] Add 1K/2K/4K options.
- [ ] Add structured generation logs.

Deliverable:

```text
Blender → Gemini → Photoreal Image
```

---

## P2 — QA & Multi-turn

Duration:

```text
2–4 days
```

Tasks:

- [ ] Define photoreal QA checklist.
- [ ] Detect common CGI cues.
- [ ] Add conditional Turn 2.
- [ ] Limit max turns.
- [ ] Log quality gain per turn.
- [ ] Compare cost / quality.

Deliverable:

```text
Auto retry only when QA fails
```

---

## P3 — Image Editing MVP

Duration:

```text
5–7 days
```

Tasks:

- [ ] Add canvas overlay.
- [ ] Point selection.
- [ ] Rectangle selection.
- [ ] Brush/lasso.
- [ ] Generate mask.
- [ ] Crop region.
- [ ] Gemini Flash local edit.
- [ ] Blend back.
- [ ] Add undo/redo.

Deliverable:

```text
User can select and visually edit an object.
```

---

## P4 — Semantic Object Editing

Duration:

```text
5–7 days
```

Tasks:

- [ ] Export Object ID.
- [ ] Export Cryptomatte.
- [ ] Add stable semantic IDs.
- [ ] Implement Object Resolver.
- [ ] Build Change Planner.
- [ ] Update Design DNA.
- [ ] Regenerate selected object.
- [ ] Regional render.

Deliverable:

```text
Marker → Object → Design DNA → Blender
```

---

## P5 — Multi-view Consistency

Duration:

```text
5–10 days
```

Tasks:

- [ ] Build view visibility mapping.
- [ ] Detect impacted cameras.
- [ ] Re-render only impacted views.
- [ ] Gemini refinement per view.
- [ ] Cross-view QA.

Deliverable:

```text
Edit once → all views updated consistently.
```

---

# 19. Ưu tiên triển khai

Thứ tự khuyến nghị:

```text
1. Benchmark Gemini
2. Fix reference strategy
3. Prompt Compiler
4. Flash / Pro model routing
5. Photoreal QA
6. Local image editing
7. Object ID mapping
8. Design edit
9. Multi-view propagation
```

Không nên làm trước:

```text
- train custom diffusion model
- train LoRA ngay
- xây multi-view generation model ngay
- tiếp tục micro-optimize Blender materials vô hạn
```

Chỉ nghiên cứu các hướng trên nếu:

```text
Gemini Pro
+
3 strong style references
+
prompt tốt
```

vẫn không đạt target.

---

# 20. Acceptance Criteria

## Photoreal v1 đạt khi

- [ ] Người review không còn nhận xét ảnh là "CGI rõ ràng".
- [ ] Geometry chính không đổi.
- [ ] Roof/layout không drift.
- [ ] Material có natural variation.
- [ ] Vegetation không còn synthetic rõ rệt.
- [ ] Concrete/asphalt không quá sạch.
- [ ] Lighting giống photography hơn archviz.
- [ ] Pro output đủ chất lượng để present chủ đầu tư.

## Edit v1 đạt khi

- [ ] User click/marker đúng object.
- [ ] Edit không phá vùng ngoài selection.
- [ ] Color/material edit phản hồi nhanh.
- [ ] Structural edit cập nhật được Design DNA.
- [ ] Undo/redo hoạt động.
- [ ] Multi-view có thể propagate được.

---

# 21. Kiến trúc production đề xuất cuối cùng

```text
                    INPUT
                     │
                     ▼
             LOD100 / Site Model
                     │
                     ▼
                Design DNA
                     │
                     ▼
             Semantic Scene Graph
                     │
                     ▼
          Procedural Industrial Scene
                     │
                     ▼
                Blender 4.5 LTS
                     │
          ┌──────────┼──────────┐
          │          │          │
        RGB        Depth     Object ID
          │          │          │
          └──────────┼──────────┘
                     ▼
             Style Reference Pack
                     │
                     ▼
              Prompt Compiler
                     │
                     ▼
                Model Router
          ┌──────────┴──────────┐
          │                     │
Gemini 3.1 Flash Image   Gemini 3 Pro Image
 Preview / Editing        Final / Hero Image
          │                     │
          └──────────┬──────────┘
                     ▼
                  QA
                     │
                     ▼
               Final Image
                     │
               User Selection
                     │
           ┌─────────┴─────────┐
           │                   │
     Visual Edit          Design Edit
           │                   │
        Gemini             Design DNA
                               │
                             Blender
                               │
                        Regional Render
                               │
                        Gemini Refinement
                               │
                               ▼
                        Updated Images
```

---

# 22. Việc nên làm ngay ngày đầu tiên

1. Kiểm tra model Gemini hiện tại trong repo.
2. Chọn 1 Blender render baseline.
3. Chọn đúng 3 style references.
4. Viết Prompt Compiler v1.
5. Chạy benchmark 24 ảnh.
6. Chấm score.
7. Chốt:
   - Flash cho Preview?
   - Pro cho Final?
   - Turn 2 có thực sự cần?
8. Sau khi photoreal đạt ngưỡng mới bắt đầu image editing.

---

# 23. Quyết định kỹ thuật đề xuất

## Photoreal generation

```text
Blender = geometry truth
Gemini Flash = preview
Gemini Pro = final
Style References = appearance truth
Multi-turn = QA-driven refinement only
```

## Editing

```text
Visual edit = local Gemini edit
Design edit = update Design DNA + Blender + local Gemini refinement
```

## Multi-view

```text
One Scene Graph
One Design DNA
Many cameras
Never generate independent designs per image
```

---

# 24. Expected End State

Người dùng có thể:

```text
1. Load Site Model
2. Chọn style
3. Generate preview
4. Nhìn ảnh gần như ảnh chụp
5. Click vào cửa
6. Nói "đổi cửa này thành cửa cuốn màu xám"
7. Xem preview nhanh
8. Nhấn Apply to Design
9. Hệ thống cập nhật scene thật
10. Các view khác tự cập nhật
11. Export Final bằng Gemini Pro 4K
```

Đây là target workflow nên hướng tới cho sản phẩm.
