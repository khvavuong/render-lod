# V365 — E0: Audit authority và request

**Thực hiện:** 2026-09-17 · commit `4d53964`
**Phạm vi:** E0 của [V365_RENDER_QUALITY_RESEARCH_PLAN.md](V365_RENDER_QUALITY_RESEARCH_PLAN.md) — không gọi image provider trả phí
**Trạng thái:** Đạt exit criteria. Ba lỗi chặn đã xác định, sửa và có test hồi quy.

## 1. Baseline đã đóng băng

| Hạng mục | Giá trị |
|---|---|
| Renderer | Blender 4.0.2, image `v365-archviz-renderer:layered-v1` id `00c47a17670b`, build 2026-09-16 14:42 |
| Cảnh báo | Image cũ hơn `scripts/blender/render_conditioning.py` (sửa 2026-09-16 16:20). Bản vá `encoded_rgb8` chưa vào image. |
| Model sạch | `480b5e6346f2877b` (391×210×11 m), `a7d22ba36b4fa342` (150×174×15 m) |
| Model bị chặn | sample 3/4 — canonicalizer từ chối vì focus-building alternatives chồng lấn |
| Prompt baseline | `LAYERED_BASE_PROMPT` (đường job) · `compose_style_prompt` (đường CLI) |
| Bộ ảnh đối chứng | `.artifacts/proof/{a1,a2,b2}` — 18 view có số đo; `.artifacts/ab_brochure`, `.artifacts/ab_detail` |

## 2. Bảng authority: nguồn so với đề xuất

Đo từ `canonical_scene.json` (nguồn, do RVT/IFC sinh) và `design_dna.json` (do `plan-design` sinh).

| | model 1 `480b5e63` | model 2 `a7d22ba3` |
|---|---|---|
| **NGUỒN** — elements | 42 | 101 |
| **NGUỒN** — surfaces | 148 | 32 |
| **NGUỒN** — `site_boundary` | **0** | **0** |
| ĐỀ XUẤT — roof assemblies | 2 | 2 |
| ĐỀ XUẤT — facades | 116 | 8 |
| ĐỀ XUẤT — loading docks | 42 | 6 |
| ĐỀ XUẤT — office entrances | 15 | 2 |
| ĐỀ XUẤT — context proxies | 12 | 12 |

**Kết luận E0 quan trọng nhất:** với model 1, nguồn cho 42 element, còn 116 facade + 42 dock + 15 lối vào + 2 mái là **do pipeline tự sinh**. Prompt hiện gọi toàn bộ số đó là *"approved design and must stay in its authored locations"*. Phần lớn thứ đang bị khoá không phải chứng cứ nguồn — nó là phỏng đoán của chính ta.

Hệ quả đã quan sát được: mái do rule suy ra từ massing phẳng, lam đỏ và dải accent do `facade_rhythm_kit` sinh — tất cả được trình bày với provider như thiết kế đã duyệt, nên trần chất lượng của ảnh bị chặn bởi trần chất lượng của grammar tự sinh.

## 3. Ba lỗi chặn exit criteria

### 3.1. Đường job không mang được DesignFreedom và ContextPolicy

```
run_generation_job.py:81    _, prompt = build_refinement_prompt(paths.design_dna)
run_generation_job.py:378   _, prompt = build_refinement_prompt(paths.design_dna)
```

Không truyền `style_pack` và không truyền `prompt_file`, nên rơi về `LAYERED_BASE_PROMPT` — prompt nghiêm ngặt nhất.

```
run_generation_job.py:161, 331, 421   composite_context_proxy=True
```

Hardcode cả ba chỗ, bỏ qua `ContextPolicy` của pack.

Toàn bộ lớp style pack chỉ chạy được từ CLI (`--style-pack`). Đường API/UI — đường sản phẩm thật đi qua — không chạm tới được. Yêu cầu *"người dùng cần có khả năng custom các phương án này"* hiện chưa nối dây.

### 3.2. Adapter mâu thuẫn với freedom vừa mở ở prompt

`providers/gemini.py:263` gửi kèm **mọi** request, không phụ thuộc `DesignFreedom`:

> MONOCHROME STRUCTURE AUTHORITY — preserve its project silhouette, roof continuity, **facade bay boundaries and exact authored/proposed opening count**.

Khi pack đặt `design_within_envelope`, prompt nói *"facade là của bạn để thiết kế"* còn adapter đồng thời đòi giữ nguyên ranh giới bay và đúng số opening. Hai chỉ thị trái nhau trong cùng một request.

Thí nghiệm `marketing_brochure` ở phiên này vẫn cho ảnh đẹp hơn rõ **dù đang bị mâu thuẫn này kìm** — nên biên độ cải thiện thật còn lớn hơn số đã đo.

### 3.3. Adapter gắn cứng vai trò vào view id

```
gemini.py:277   if request.view_id in {"view-01", "view-04"}:   # khối AERIAL SITE-PLAN
gemini.py:249   "...the approved VIEW-06 golden-hour photography variant"
```

Giả định view-01/view-04 luôn là aerial và view-06 luôn là golden hour. Camera search ở E1 sẽ chọn slot theo năng lực của site, nên ràng buộc này phải chuyển sang dựa trên `ViewRole` thay vì chuỗi view id.

## 4. Lỗi đã sửa trong phiên, giữ lại làm hồ sơ

| Lỗi | Bằng chứng | Trạng thái |
|---|---|---|
| Prompt bắt "preserve" hàng rào/cổng không tồn tại | `site_boundary` = 0.00000 trên 12/12 view của cả hai model | Đã sửa, có test hồi quy |
| `ProtectRefinement` nung logo vào `unbranded_refined` | 4/6 file của board B2 dính logo, view-01 chồng hai lớp | Đã sửa, test kiểm chứng fail-với-code-cũ |

## 5. Số đo dùng cho các bước sau

**Cổng edge sai 10 trên 11 lần.** Đối chiếu phán quyết cổng edge với `verify-massing` trên 18 view:

| | massing PASS | massing FAIL |
|---|---|---|
| edge từ chối | **10** | 1 |
| edge chấp nhận | 7 | 0 |

Board A1 — massing 6/6, ảnh đạt review — bị cổng edge từ chối 4/6 view. Đã kiểm chứng tận mắt A1 view-05 (recall 0.099): camera giữ nguyên, báo động giả.

Biến thể chỉ tính đường bao ngoài **không cứu được**: phân bố trên 18 view chạy liên tục 0.000–1.000, không tồn tại ngưỡng tách được.

**Ba mức freedom trên view-01** (silhouette recall so với base):

| mức | recall | massing | nhận xét |
|---|---|---|---|
| `photoreal_only` | 0.942 | pass | giữ sát nhất, ảnh kém nhất |
| `detail_within_envelope` | 0.759 | **pass 2/2** | ảnh đẹp hơn rõ, khối đúng |
| `design_within_envelope` | 0.738 | pass | gần cùng cái giá với mức trên |

Không có đường giữa rẻ tiền: mở chút nào thì recall cũng rơi về ~0.75. Metric không phân biệt được "phát triển mặt tiền" với "dịch toà nhà".

**Instance pass không giải mã được:** 305 đối tượng, 4746 màu trong ảnh, **0% khớp manifest**. Mã hoá `instance_index` little-endian khiến hai đối tượng liền kề khác nhau 1/255.

## 6. Exit criteria

| Điều kiện | Trạng thái |
|---|---|
| Một authority nhất quán cho cùng một request | Đạt — §7 |
| Không gọi proposal chưa duyệt là approved | Đạt — §7.2 |
| Request thể hiện đúng freedom/context | Đạt — §7.1 |
| Baseline đóng băng | Đạt — §1 |
| Model nguồn sạch, ghi version | Đạt — §1 |

## 7. Sửa chữa đã thực hiện

### 7.1. Đường job mang được style pack

`GenerationJob` thêm trường `style_pack_ref`. `run_generation_job` nạp pack và truyền vào cả hai
call site của `build_refinement_prompt`, và `composite_context_proxy` ở cả ba call site giờ đọc
`ContextPolicy` của pack thay vì hardcode `True`.

Test: job có pack thì `design_freedom` và `context_policy` đi theo; job không pack thì giữ mặc
định nghiêm ngặt.

### 7.2. Structure authority phụ thuộc DesignFreedom

`ViewConditioningInput` thêm `design_freedom` và `role`. Khối MONOCHROME STRUCTURE AUTHORITY
trong `providers/gemini.py` giờ có ba biến thể:

| mức | khối yêu cầu giữ |
|---|---|
| `photoreal_only` | silhouette, roof continuity, facade bay boundaries, **exact opening count** |
| `detail_within_envelope` | silhouette, roof continuity, vị trí và số dock; bay line là *nơi đặt nhấn*, không phải thiết kế xong |
| `design_within_envelope` | silhouette, footprint, vị trí cửa xe tải; mọi thứ bên trong outline là **massing study, không phải thiết kế** |

Silhouette được giữ ở cả ba mức, nếu không thì các cổng phía sau không còn gì để đo.

Điều này gỡ mâu thuẫn: trước đây pack `design_within_envelope` gửi đi một prompt nói *"facade là
của bạn"* kèm một khối ảnh đòi giữ đúng số opening — hai chỉ thị không thể cùng tuân thủ.

### 7.3. Ràng buộc theo ViewRole thay vì view id

Khối AERIAL SITE-PLAN AUTHORITY giờ khoá theo `role in {"overall", "detail"}` thay vì
`view_id in {"view-01", "view-04"}`. Test kiểm chứng: aerial nằm ở slot view-04 vẫn nhận được
khối, còn facade nằm ở slot view-01 thì không.

Đây là điều kiện tiên quyết cho E1: camera search gán slot theo năng lực của site, nên số thứ tự
view không còn hàm ý vai trò.

**193 test pass, ruff sạch.**
