# V365 — E2: Ablation mức tự do thiết kế

**Thực hiện:** 2026-09-17 · sau khi E0 gỡ mâu thuẫn adapter
**Thiết kế:** 2 model sạch × 2 góc (site, facade) × 3 mức freedom = 12 ảnh, cùng provider, cùng conditioning, không reference ngoài
**Pack:** ba file trong `.artifacts/e2/packs/`, **chỉ khác nhau đúng trường `design_freedom`** — đã kiểm chứng bằng diff từng trường

## 1. Vì sao phải đo lại

Số liệu freedom đo trước E0 không dùng được. Khi đó adapter gửi kèm mọi request một khối
`MONOCHROME STRUCTURE AUTHORITY` đòi giữ *"facade bay boundaries and exact authored/proposed
opening count"*, kể cả khi prompt vừa cấp quyền thiết kế lại mặt tiền. Mọi ảnh "tự do" thực ra
được sinh dưới hai chỉ thị trái nhau.

E0 đã cho khối đó ba biến thể theo mức freedom. E2 là lần đầu đo được biên độ thật.

## 2. Giữ hình học — silhouette recall so với base

| model | góc | photoreal_only | detail_within_envelope | design_within_envelope |
|---|---|---|---|---|
| A | view-01 site | 0.998 | **0.999** | 0.693 |
| A | view-05 facade | 0.009 | 0.087 | 0.009 |
| B | view-01 site | 0.954 | 0.777 | 0.784 |
| B | view-05 facade | 0.645 | 0.672 | **0.737** |

Ba điều đọc được:

**`detail_within_envelope` không tốn gì trên A/view-01** — 0.999 so với 0.998 của mức nghiêm ngặt
nhất. Đây là so sánh sạch: cùng camera, cùng base render, cùng pack trừ một trường.

**Trên B/view-05, `design_within_envelope` giữ hình học *tốt nhất*** (0.737 so với 0.645). Mức tự
do nhất không phải lúc nào cũng trôi xa nhất.

**A/view-05 gần bằng 0 ở cả ba mức** (0.009 / 0.087 / 0.009). Camera này hỏng độc lập với
freedom — đúng ca đã phân tích ở mục 14 của kế hoạch camera: khoảng lùi bị sân kẹp còn 23.6 m
nên mái bị cắt ngoài khung, và provider dựng lại camera. Không mức freedom nào chữa được một
khung hình cụt.

## 3. Chất lượng thiết kế và tính chân thực — quan sát ảnh

**A/view-01 (aerial site).** `design_within_envelope` chân thực hơn hẳn: bối cảnh khu công nghiệp
có thật, xe cộ đúng tỉ lệ, biển hiệu trên dock, đầu hồi văn phòng có kính. `photoreal_only` đứng
thứ hai. `detail_within_envelope` **kém nhất về cảm giác ảnh chụp** ở góc này — mờ và phẳng hơn,
và các khối proxy nổi rõ thành mảng trắng lớn.

**B/view-05 (facade).** `design_within_envelope` rõ ràng tốt nhất: lam đứng thành bản có chiều sâu
và đổ bóng thật thay vì mảng màu phẳng, portal có soffit, có biển "LOGISTICS HUB", và tường rào
thành panel bê tông đúc thật. `photoreal_only` và `detail_within_envelope` gần như nhau, phẳng hơn.

## 4. Kết luận tạm thời

Ba mức **không** xếp thành một thang đơn điệu giữa "đẹp" và "trung thực". Quan hệ phụ thuộc góc:

- Ở góc facade, `design_within_envelope` thắng **cả hai** trục trên model B.
- Ở góc aerial, nó thắng về chân thực nhưng mất 0.3 điểm silhouette trên model A.
- `detail_within_envelope` giữ hình học tốt nhưng không đẹp hơn mức nghiêm ngặt ở góc aerial.

Vì vậy chưa nên chốt một mức duy nhất cho mọi role. Giả thuyết đáng kiểm nghiệm tiếp: **freedom
nên gắn theo role chứ không theo cả bộ** — góc facade cho tự do rộng, góc aerial giữ chặt hơn vì
đó là ảnh phải đọc ra mặt bằng tổng thể.

## 5. Giới hạn của lần đo này

Mỗi ô đúng **một mẫu**. Sinh ảnh là ngẫu nhiên; chênh lệch nhỏ như 0.645 với 0.672 nằm trong
khoảng chưa phân biệt được. Kế hoạch yêu cầu lặp lại cấu hình đứng đầu ít nhất ba lần trước khi
tuyên bố thắng, và điều đó chưa làm.

Phán quyết `verify-massing` cho 12 ảnh **chưa lấy được**: API trả 429 Too Many Requests sau 12 lần
generate. Đây là giới hạn hạn mức, không phải lỗi code; phải chạy lại khi hết rate limit. Cho đến
lúc đó, cột "giữ hình học" chỉ có silhouette recall, mà chính nó đã được chứng minh ở E0 là sai
10/11 lần khi dùng làm cổng.

Nhận xét về chất lượng thiết kế và chân thực là của một người đánh giá, không mù, biết trước ô nào
là mức nào. Kế hoạch yêu cầu review mù với rubric 1–5 và ít nhất hai người; chưa làm.
