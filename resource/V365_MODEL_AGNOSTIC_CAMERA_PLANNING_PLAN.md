# V365 Model-Agnostic Camera Planning — Kế hoạch triển khai

**Phiên bản:** 1.1
**Ngày:** 2026-09-16
**Trạng thái:** Bước 1–4 đã triển khai; xem mục 12
**Phạm vi:** Thay hằng số camera đã tinh chỉnh tay bằng ràng buộc giải được, để một bộ quy tắc
duy nhất chạy đúng trên mọi site model LOD100

---

## 1. Vấn đề

`plan_cameras.py` chứa **173 hằng số thập phân, 78 giá trị khác nhau** điều khiển vị trí camera.
Chúng không phải kết quả thiết kế mà là kết quả dò tay trên một model duy nhất
(`model_lod100_sample.rvt`, bounds kiến trúc 352 × 166 × 11 m).

Ví dụ đo được trong một phiên làm việc, cùng một camera VIEW-02:

| Lần chỉnh | Khoảng cách | Kết quả quan sát |
|---|---|---|
| 1 | 60,5 m | 45% khung dưới là mặt đất trống |
| 2 | 35,5 m | Mặt tường dài lấp kín khung, mất cổng và chiều sâu |
| 3 | 49,7 m | Chấp nhận được |

Công thức sinh ra 49,7 m là `min(max(42.0, height * 4.5), max(50.0, site_span * 0.17))`. Con số
`4.5` không có căn cứ hình học; nó là giá trị làm model này trông ổn. Một model có tỷ lệ khác —
nhà cao 25 m trên site 80 × 60 m — sẽ nhận khung hình sai ngay lần chạy đầu.

Đây là dạng hardcode giống hệt thứ đã được loại khỏi tầng thẩm mỹ khi tách `style_packs/`. Tầng
camera chưa được xử lý tương tự.

### 1.1. Triệu chứng kèm theo

- Không có phép thử nào chạy trên nhiều model. Cả bốn file `resource/model_lod100_sample*.rvt`
  chưa từng được kiểm tra bằng cùng một bộ quy tắc.
- Mỗi model mới sẽ cần một vòng dò tay tương tự, và không có cách nào biết trước bao nhiêu vòng.

---

## 2. Nguyên tắc

> Planner phải phát biểu **bài toán**, không phát biểu **câu trả lời**.

Hiện tại planner nói "đứng cách `height × 4.5`". Nó cần nói "đứng ở khoảng cách sao cho mái lọt
khung, chủ thể chiếm 12–40% khung, tiền cảnh dưới 30%".

Bài toán **đã được viết sẵn** nhưng chưa dùng để giải: `validate_conditioning.py` định nghĩa cho
từng role các ngưỡng `minimum_focus`, `maximum_focus`, `minimum_circulation`,
`maximum_central_entourage_occlusion`. Đó chính là hàm mục tiêu. Quy trình hiện tại là người chỉnh
hằng số cho tới khi gate pass — việc này phải do planner làm.

---

## 3. Kiến trúc mục tiêu

```text
Canonical Scene + Design DNA
        ↓
Photography Pack  (dữ liệu: góc nâng, chiều cao mắt, tỷ lệ chủ thể mục tiêu, lens)
        ↓
Tầng 1 — Analytic Constraint Solver      (nghiệm đóng, không cần render)
        ↓
Camera đề xuất
        ↓
Tầng 2 — Closed-loop Refinement          (render preview → đo → chỉnh, tối đa 3 vòng)
        ↓
View Set đã thoả ngưỡng conditioning
```

---

## 4. Tầng 1 — Ràng buộc giải bằng công thức

Phần lớn hằng số hiện tại thay thế được bằng nghiệm đóng từ bounds và thông số ống kính. Những
ràng buộc này đúng với mọi model theo định nghĩa.

### 4.1. Mái phải lọt khung

Điều kiện:

```text
atan((z_đỉnh − z_camera) / d)  <  tilt + halfFOV × frame_margin
```

với `halfFOV = atan((sensor_width × aspect_inverse) / (2 × focal_length))`.

Giải ra `d` tối thiểu. Đây chính là phép tính đã dùng để chẩn đoán VIEW-05: đỉnh mái nằm ở 20,5°
trên phương ngang trong khi giới hạn khung là 20,0° — hụt nửa độ, và Gemini phản ứng bằng cách
lùi camera ra. Phép tính đó cần nằm trong code, không phải nằm trong đầu người chỉnh.

### 4.2. Tỷ lệ chủ thể trong khung

Chiếu tám đỉnh của bounds kiến trúc qua ma trận camera, tính diện tích bao lồi trên mặt phẳng ảnh,
giải `d` sao cho tỷ lệ đạt mục tiêu của role. Đây là xấp xỉ trên (không tính che khuất) nên dùng
làm điểm khởi đầu cho tầng 2, không dùng làm kết luận.

### 4.3. Tỷ lệ tiền cảnh

Vị trí đường chân trời trên khung suy trực tiếp từ `tilt`. Giải `tilt` sao cho phần mặt đất dưới
chân công trình không vượt ngưỡng của role.

### 4.4. Hằng số nào được phép giữ lại

Sau tầng 1, các giá trị còn lại **không phải khoảng cách** mà là quy ước thể loại nhiếp ảnh:

- góc nâng hero aerial (hiện 28°),
- chiều cao mắt người (1,6–1,85 m),
- tỷ lệ chủ thể mục tiêu theo role,
- tiêu cự theo role.

Những giá trị này độc lập với model và **nên** là hằng số — nhưng thuộc về dữ liệu, không thuộc
về code. Xem mục 5.

---

## 5. Photography Pack

Tách theo đúng mô hình đã áp dụng cho `resource/style_packs/`.

```text
resource/photography_packs/
    documentary_industrial.json
    marketing_aerial.json
```

Nội dung mỗi pack: theo từng `ViewRole`, khai báo `elevation_deg`, `eye_height_m`,
`focal_length_mm`, `target_subject_coverage`, `max_foreground_share`, `roofline_margin`.

Thêm một phong cách nhiếp ảnh = thêm một file, không sửa code. Ràng buộc hình học ở tầng 1 vẫn do
hệ thống sở hữu và không nằm trong pack — giống cách `GEOMETRY_CONTRACT` luôn được ghép vào mọi
style pack.

---

## 6. Tầng 2 — Vòng lặp đo

Một số đại lượng không có nghiệm đóng vì phụ thuộc che khuất, địa hình và cây xanh. Với chúng,
giải bằng đo.

```text
dựng scene một lần
  └─ mỗi camera:
       render preview 768 × 432
       đo coverage bằng đúng hàm gate đang dùng
       nếu ngoài ngưỡng → chỉnh khoảng cách/góc theo dấu sai lệch
       lặp tối đa 3 vòng
       render final ở độ phân giải yêu cầu
```

### 6.1. Ràng buộc chi phí

Vòng lặp **phải nằm trong cùng một phiên Blender**. Dựng scene là phần tốn thời gian; render
preview một view thì nhanh. Chạy lại container cho mỗi vòng sẽ nhân chi phí dựng scene lên nhiều
lần và làm phương án mất khả thi.

Container đã có `python3-numpy`, nên tính coverage tại chỗ được. Logic đo phải dùng chung nguồn
với `validate_conditioning.py` để gate và solver không bao giờ lệch nhau.

### 6.2. Tính tất định

Vòng lặp phải hội tụ tất định: cùng scene và cùng pack phải cho cùng view set. Không dùng số ngẫu
nhiên; giới hạn số vòng cố định; ghi lại số vòng đã dùng vào artifact để truy vết.

---

## 7. Thước đo khoá khung hình

Hiện đang dùng sai một thước đo. `edge_alignment_f1` được dùng để đánh giá "provider có dựng lại
camera không", nhưng nó không đo điều đó.

Bằng chứng đo được: VIEW-02 giữ **đúng** camera — cùng góc, cùng đường chân trời, cùng tháp nền —
mà chỉ đạt f1 = 0,35, vì mặt tôn có hàng chục gân dọc và sai lệch vài pixel khi vẽ lại đã đủ làm
sụp điểm. Ngược lại VIEW-05 bị dựng lại hoàn toàn thành góc drone và cũng cho điểm thấp. Hai tình
huống khác hẳn nhau nhưng thước đo không phân biệt được.

### 7.1. Thước đo cần xây

Chiếu một tập điểm mốc 3D đã biết (góc công trình, chân cột, mép mái) qua ma trận camera đã lưu
trong `camera.json`, định vị chúng trong ảnh sinh, đo độ lệch vị trí.

- lệch nhỏ và đồng đều → giữ khung, chấp nhận được;
- lệch lớn hoặc có thành phần scale/rotation → camera đã bị dựng lại, từ chối.

Thước đo này mới là điều kiện tiên quyết cho tính năng editing tương tác, vì `instance_id.png`
thuộc về base render: nếu ảnh giao hàng lệch khung thì thao tác click → object không ánh xạ được.

---

## 8. Phép thử chấp nhận

Không coi là hết hardcode cho tới khi **cùng một bộ ràng buộc** chạy qua gate trên nhiều model có
tỷ lệ khác nhau, **không chỉnh tham số giữa các model**.

Tiêu chí: `validate-conditioning` trả `passed: true` cho toàn bộ 6 view.

### 8.1. Tập model dùng được

```text
resource/model_lod100_sample.rvt     352 × 166 × 11 m   tỷ lệ span/cao 32,0
resource/model_lod100_sample_2.rvt   125 × 142 × 15 m   tỷ lệ span/cao  9,4
```

Hai model lệch nhau 3,4 lần về tỷ lệ span/cao, đủ để phát hiện hằng số chỉ đúng cho một hình dáng.
Trên thực tế phép thử này đã bắt được ba lỗi trong lần triển khai đầu (xem 12.3), trong đó hai lỗi
vẫn cho ảnh "trông tạm được" nếu chỉ chạy một model.

### 8.2. Model bị loại khỏi tập thử

`sample_3` và `sample_4` **không dùng được** và đã được chấp nhận loại bỏ.

Cả hai extract IFC thành công qua APS nhưng bị canonicalizer từ chối:

```text
IFC contains overlapping focus-building alternatives;
use a view-scoped Revit export so one coherent 3D option is selected
```

Hai file chứa nhiều phương án thiết kế chồng lên nhau trong cùng một export 3D, nên không xác định
được khối nào là công trình thật. Guard tại `providers/ifc.py` từ chối thay vì đoán — đúng nguyên
tắc fail-closed.

Muốn đưa lại vào tập thử thì phải export lại từ Revit theo view đã chọn một phương án. Đây là vấn
đề dữ liệu nguồn, không phải giới hạn của camera planner.

**Lưu ý vận hành:** kiểm tra cấu trúc IFC trước khi gọi APS. Hai lần extract này tốn phí cho model
cuối cùng không dùng được.

---

## 9. Thứ tự triển khai

| Bước | Nội dung | Kiểm chứng |
|---|---|---|
| 1 | Ràng buộc mái lọt khung (4.1) | Đơn vị: nghiệm thoả bất đẳng thức với nhiều tỷ lệ bounds |
| 2 | Tỷ lệ chủ thể và tiền cảnh (4.2, 4.3) | Đơn vị |
| 3 | Photography Pack (5) | Test: mọi pack đều giữ ràng buộc hệ thống |
| 4 | Chạy phép thử bốn model (8) | Gate conditioning |
| 5 | Vòng lặp đo trong Blender (6) | Gate conditioning + kiểm tra tính tất định |
| 6 | Thước đo khoá khung hình (7) | Đối chiếu với các ca đã biết: VIEW-02 giữ khung, VIEW-05 bị dựng lại |

Bước 1–4 không cần gọi provider nên kiểm chứng rẻ. Bước 6 cần ảnh sinh.

---

## 10. Rủi ro

**R1 — Tầng 1 và tầng 2 mâu thuẫn.** Nghiệm đóng có thể cho khoảng cách mà đo thực tế lại trượt
ngưỡng, do che khuất. Giảm thiểu: tầng 1 chỉ cung cấp điểm khởi đầu, tầng 2 có quyền quyết định
cuối.

**R2 — Vòng lặp không hội tụ.** Một số model có thể không tồn tại vị trí thoả mọi ràng buộc.
Giảm thiểu: giới hạn số vòng, và khi hết vòng thì trả camera tốt nhất kèm cờ `unsatisfied` để gate
fail-closed thay vì âm thầm chấp nhận.

**R3 — Không đủ mẫu.** Bốn model mẫu có thể cùng một họ tỷ lệ. Giảm thiểu: kiểm tra tỷ lệ
span/height của bốn model trước khi coi phép thử là đủ; nếu quá giống nhau, cần thêm mẫu.

**R4 — Chi phí render của vòng lặp.** Xem 6.1. Nếu không giữ được vòng lặp trong một phiên Blender
thì phương án mất khả thi và phải dừng ở tầng 1.

---

## 11. Quan hệ với kế hoạch SAM3

`V365_NEXT_DEVELOPMENT_PLAN_SAM3.md` giả định ảnh giao hàng giữ đủ hình học để thao tác cục bộ có
nghĩa. Giả định đó hiện **chưa thành lập**: VIEW-05 đã được đo là bị dựng lại thành góc khác hẳn.

Kế hoạch này là điều kiện tiên quyết chưa được ghi trong kế hoạch SAM3. Cụ thể, Phase 3 (Object
Grounding) không thể hoạt động nếu ảnh giao hàng lệch khung so với base render, vì ánh xạ
click → object đi qua `instance_id.png` của base render.

---

## 12. Kết quả triển khai bước 1–4

### 12.1. Đã xây

| Thành phần | Vị trí |
|---|---|
| Ràng buộc giải bằng công thức | `src/v365_archviz/application/camera_framing.py` |
| Photography Pack | `src/v365_archviz/domain/photography_pack.py` |
| Hai pack mẫu | `resource/photography_packs/` |
| Test | `tests/test_camera_framing.py`, `tests/test_photography_pack.py` |

Bốn camera đã chuyển sang solver: VIEW-01, VIEW-03, VIEW-04, VIEW-05.

### 12.2. Phép thử chấp nhận

Chạy trên hai model có canonical scene, **cùng một bộ ràng buộc, không chỉnh tham số giữa hai
model**:

| View | Model 1 (352×166×11, tỷ lệ 32,0) | Model 2 (125×142×15, tỷ lệ 9,4) |
|---|---|---|
| view-01 overall | 0,169 | 0,357 |
| view-02 context | 0,158 | 0,128 |
| view-03 hero | 0,328 | 0,158 |
| view-04 detail | 0,152 | 0,263 |
| view-05 office_hero | 0,195 | 0,200 |
| view-06 loading_detail | 0,297 | 0,135 |

**Kết quả: 6/6 pass trên cả hai model.**

Đạt tiêu chí mục 8 trên tập model dùng được. `sample_3` và `sample_4` đã được loại khỏi tập thử
vì lý do dữ liệu nguồn — xem 8.2.

### 12.3. Phát hiện quan trọng — không phải hằng số nào cũng là hardcode

Trong quá trình triển khai, ba lỗi xuất hiện và cả ba đều do phép thử đa model phát hiện. Với một
model, hai lỗi đầu vẫn cho ảnh "trông tạm được".

**Lỗi 1 — định nghĩa sai chủ thể.** Truyền chiều rộng cả mặt đứng vào ràng buộc tỷ lệ chủ thể. Với
model 2 có mặt đứng dài 125 m, khoảng cách giải ra **210 m** cho một view chi tiết. Sửa: với view
chi tiết tầm mắt, chủ thể là một đoạn mặt đứng **cao bằng công trình**, không phải cả elevation
(hàng trăm mét) cũng không phải riêng ô cửa (2–5 m).

**Lỗi 2 — xoá nhầm ràng buộc vật lý.** Biểu thức cũ `min(max(22.0, height * 2.3), max(14.0,
cross_span * 0.24))` bị coi là hai hằng số dò tay. Thực ra số hạng thứ hai là **giới hạn không
gian**: không thể lùi xa hơn khoảng sân cho phép. Xoá nó đi thì solver đẩy camera xuyên vào dãy
nhà đối diện và render ra ảnh xám trơn.

**Lỗi 3 — áng chừng sai không gian.** Sau khi khôi phục clamp, dùng `cross_span * 0.28` làm
clearance. Với model 1 cho 46,5 m trong khi khoảng hở thật giữa hai dãy mái chỉ **42 m**, tức
clearance thật là 19 m — sai 2,4 lần, nên clamp không bao giờ kích hoạt. Sửa: đo trực tiếp khoảng
hở giữa các `roof_assemblies` (`_corridor_gap_m`).

### 12.4. Phân loại hằng số

Từ ba lỗi trên rút ra phân loại cần áp dụng khi tiếp tục dọn các hằng số còn lại:

| Loại | Xử lý | Ví dụ |
|---|---|---|
| **Ý đồ nhiếp ảnh** | Chuyển sang Photography Pack | góc nâng 28°, chiều cao mắt 1,75 m, tỷ lệ chủ thể |
| **Ràng buộc vật lý của site** | Giữ lại, nhưng **đo từ model** thay vì áng chừng theo tỷ lệ | khoảng hở giữa hai dãy mái |
| **Hằng số dò tay thật sự** | Thay bằng nghiệm đóng | khoảng cách stand-off |

Nhầm loại 2 thành loại 3 là nguyên nhân của lỗi 2, và là rủi ro chính khi dọn nốt các camera còn
lại.

### 12.5. Còn lại

- VIEW-02 và VIEW-06 vẫn dùng hằng số dò tay; chưa chuyển sang solver.
- Bước 5 (vòng lặp đo) và bước 6 (thước đo khoá khung hình) chưa bắt đầu.
- Tập thử hiện là hai model. Khi có thêm model LOD100 hợp lệ với tỷ lệ khác, nên bổ sung vào tập
  thử trước khi dọn nốt các hằng số còn lại.

---

## 13. Phát hiện ngoài phạm vi: instance pass không giải mã được tin cậy

Phát hiện khi kiểm chứng phép chiếu của bước 6. Không thuộc phạm vi camera planning nhưng là
**điều kiện tiên quyết cho kiến trúc editing**, nên ghi lại ở đây.

### 13.1. Triệu chứng

`instance_id.png` mã hoá `obj.pass_index` thành màu RGB. Đọc ngược từ ảnh render thật cho ra
index không tồn tại trong manifest: pixel `[114, 0, 0]` giải ra index 114, trong khi manifest
không có index nào trong khoảng 95–130.

### 13.2. Nguyên nhân

Index được phát dưới dạng **linear**, còn PNG ghi qua **transfer function sRGB**. Byte trên đĩa
không phải byte index.

Kiểm chứng: index 43 ở dạng linear `43/255` sau khi mã hoá sRGB cho ra byte **114** — đúng giá trị
quan sát được, và index 43 là `batched-context_landscape`, tức mặt đất, thứ chiếm nhiều pixel nhất
trong một ảnh aerial.

Renderer đặt `view_transform = "Standard"` kèm comment nói rõ ý định *"ID passes are data, not
presentation imagery"*, nhưng `Standard` vẫn áp sRGB. Cần `Raw` / `Non-Color`.

### 13.3. Hệ quả nghiêm trọng hơn: mất phân biệt

Mã hoá sRGB không song ánh trên 8 bit:

- **70 giá trị byte bị trùng**; chỉ **183/256** index phân biệt được trên mỗi kênh.
- Ví dụ index 75 và 76 cùng ra byte 148 — hai object khác nhau, cùng một màu trong ảnh.

Ngoài ra quan sát thấy `[115, 1, 1]` thay vì `[115, 0, 0]`: sai lệch **1 đơn vị** ở kênh G hoặc B
làm index nhảy **256 hoặc 65536**. Mã hoá little-endian qua ba kênh không chịu được nhiễu.

### 13.4. Đính chính

Đánh giá trước đó trong `V365_NEXT_DEVELOPMENT_PLAN_SAM3.md` — rằng Phase 3 (Object Grounding) rẻ
hơn kế hoạch vì *"794 instance đã nằm sẵn trong pixel, chỉ thiếu bảng tra"* — **không đúng**. Bảng
tra là cần nhưng chưa đủ: kênh truyền tải đang mất mát.

### 13.5. Hướng sửa

Ghi ID pass ở định dạng không qua transfer function:

- PNG 16-bit với colour management `Raw`, hoặc
- EXR float, hoặc
- giữ 8-bit nhưng dùng một kênh cho index thấp và bảng tra thưa, chấp nhận trần 183 object/view.

Phải sửa **trước** khi xây tầng editing, vì toàn bộ ánh xạ click → object dựa vào pass này.

Manifest đã được sửa để ghi `encoded_rgb8` — byte thực tế xuất hiện trong file — thay vì byte
index thô. Đó là điều kiện cần để đối chiếu, nhưng không giải quyết được mất phân biệt ở 13.3.

## 14. Khoảng cách bị kẹp: nghịch đảo đã có, nhưng chưa dùng được

### 14.1 Đo được gì

Chiếu điểm mái qua đúng camera đã render của lần chạy `final3`, khung 2048×1152:

| view | lens | roofline y (px) | kết luận |
|---|---|---|---|
| view-03 | 35 mm | 18.1 | sát mép trên |
| view-05 | 35 mm | **−38.2** | **mái bị cắt ngoài khung** |
| view-06 | 35 mm | 91.2 | trong khung |

VIEW-05 được giải cho khoảng lùi 37 m ở 35 mm, nhưng `available_apron_clearance` kẹp xuống
23.6 m, rồi vẫn render bằng 35 mm của pack. Gemini nhận một khung cụt mái nên dựng lại camera:
`edge_alignment_recall = 0.057`. Đây là nguyên nhân thật của VIEW-05, không phải prompt — pack
`marketing_brochure` cho kết quả 0.017, tệ tương đương, nên trục tự do thiết kế không liên quan.

### 14.2 Nghịch đảo closed-form (đã có, đã test)

`camera_framing.py` bổ sung ba hàm, mỗi hàm round-trip đúng với hàm thuận:

- `focal_length_for_roofline` — nghịch đảo `distance_for_roofline`
- `focal_length_for_width_coverage` — nghịch đảo `distance_for_width_coverage`
- `tilt_for_roofline` — góc ngẩng giữ được mái khi cả khoảng cách lẫn ống kính đã hết biên độ
- `framed_focal_length` — gộp hai ràng buộc, chặn dưới bởi sàn ống kính kiến trúc

### 14.3 Vì sao chưa nối vào planner

Nối vào rồi đo lại thì **hồi quy**: giữ được mái nhưng chủ thể teo lại dưới ngưỡng gate.

| view | focus_coverage trước | sau khi nới lens | ngưỡng |
|---|---|---|---|
| view-05 | 0.209 (pass) | **0.082 (fail)** | `minimum_focus = 0.15` |
| view-06 | 0.308 (pass) | **0.082 (fail)** | `minimum_focus = 0.15` |

Giữ mái 11 m từ 23.6 m cần 18 mm; ở 18 mm chủ thể chỉ còn 8% khung và `circulation_coverage`
lên 0.806 — gần như toàn sân bê tông. Gate báo đúng: `focus_subject_too_small_or_missing`.

Hai ràng buộc không cùng thoả được từ khoảng cách đó. Nới lens chỉ **dời chỗ hỏng** từ phía
provider sang phía gate, không sửa được gì.

### 14.4 Nguyên nhân gốc thật sự

**Khoảng cách mới là cái sai, không phải ống kính.** `_corridor_gap_m` đưa khe hở giữa hai nhà
xưởng cho một cú máy chụp mặt tiền văn phòng — nhưng camera đó đứng ở sân đón, phía đường tiếp
cận, nơi rộng hơn nhiều. `available_apron_clearance` đang trả lời sai câu hỏi cho role đó.

Ngoài ra `_elevation_stand_off` coi chủ thể của **mọi** role mặt đất là "hình vuông cạnh bằng
chiều cao toàn nhà". Với `office_hero`, chủ thể đúng là khối văn phòng; với `loading_detail` là
cửa dock. Ràng buộc roofline đang áp lên sai chủ thể.

### 14.5 Việc còn lại

1. Cho `available_clearance` phụ thuộc role: khe hở giữa xưởng chỉ đúng cho cú máy trong hành lang.
2. Cho `RoleFraming` khai báo chủ thể mà role đó đóng khung, thay vì luôn dùng chiều cao toàn nhà.
3. Chỉ khi hai điều trên đúng thì nối `framed_focal_length` / `tilt_for_roofline` vào planner,
   và đo lại bằng chính hai chỉ số đã dùng ở đây: roofline-in-frame và `focus_coverage`.

Cho đến lúc đó `_elevation_stand_off` giữ tiêu cự của pack. Hằng số tiêu cự trong `Camera(...)`
đã được thay bằng giá trị lấy từ photography pack — hôm nay trùng số nên không đổi hành vi,
nhưng nó là lỗi ngầm cùng lớp với lỗi "fit một tiêu cự, render tiêu cự khác" đã gặp ba lần.
