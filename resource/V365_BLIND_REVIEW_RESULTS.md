# V365 — Kết quả chấm mù

**Thực hiện:** 2026-09-18 · `scripts/blind_review.py`
**Cách làm:** ảnh xáo theo seed dẫn xuất từ danh sách, bỏ nhãn, key ghi ra thư mục khác và **chỉ mở sau khi khoá điểm**. Rubric 1–5: composition, design, realism, material_lighting.
**Giới hạn:** một người chấm. Bỏ được thiên lệch nhãn, **không bỏ được thiên lệch người**. Kế hoạch yêu cầu hai người; chỗ đó chưa đạt.

## 1. E2 — mức tự do thiết kế (12 ảnh)

| mức | tổng | design | realism |
|---|---|---|---|
| `design_within_envelope` | **17.00** | **4.25** | **4.25** |
| `photoreal_only` | 12.75 | 2.75 | 3.00 |
| `detail_within_envelope` | 11.50 | 2.25 | 2.75 |

Ba vị trí đầu bảng **đều là** `design_within_envelope`. Bốn vị trí cuối gồm cả ba ảnh `detail` và hai ảnh `photoreal`.

Hai điều xác nhận và một điều sửa lại:

- **`detail_within_envelope` bị lấn át — xác nhận.** Nó kém nhất ở **cả** design lẫn realism, đồng thời chịu đúng rủi ro massing của mức tự do nhất (3/4 pass). Không phải đường giữa, mà là tệ nhất mọi mặt.
- **`design_within_envelope` thắng — xác nhận, và mạnh hơn tôi dám nói trước đây.** Cách biệt 4.25–5.50 điểm trên thang 20.
- **Sửa lại:** tôi từng nói tự do thiết kế chỉ làm ảnh "đẹp hơn". Chấm mù cho thấy nó nâng **realism ngang bằng design** (4.25 so với 3.00). Nó không chỉ làm kiến trúc khá hơn, nó làm ảnh giống ảnh chụp hơn.

## 2. E3 — input conditioning (8 ảnh)

| input | tổng | design | realism |
|---|---|---|---|
| C0 khối trung tính | 15.50 | 4.00 | 3.75 |
| C1 control render hiện tại | 14.25 | 3.00 | 3.75 |

**Sửa lại kết luận trước.** Tôi đã viết "C0 đẹp hơn rõ rệt". Chấm mù nói: C0 hơn về **design** (4.00 so với 3.00) nhưng **hoà về realism** (3.75 cả hai), và tổng chỉ hơn 1.25 điểm — nằm trong nhiễu với n=4.

Bằng chứng cho thấy tôi đã gộp hai thứ khác nhau: khi chấm không mù tôi thấy C0 có mái dốc, sảnh kính, biển hiệu, rồi gọi luôn đó là "chân thật hơn". Chấm mù tôi ghi về đúng ảnh đó — không biết nó là C0 — rằng *"kiến trúc tốt nhất, nhưng đọc ra như CGI bóng bẩy chứ không phải ảnh chụp"*.

## 3. Kết luận có thể hành động

**Đòn bẩy nằm ở prompt, không ở render.**

| thay đổi | lợi (thang 20) | giá |
|---|---|---|
| Nới freedom sang `design_within_envelope` | **+4.25 đến +5.50** | massing 3/4 pass; không cần đổi renderer |
| Bỏ facade tự sinh khỏi render (C0) | +1.25, trong nhiễu | massing **2/4 fail**, mất luôn ràng buộc số mái |

Nới tự do trong prompt **rẻ hơn, hiệu quả gấp ba lần, và ít rủi ro hình học hơn** so với tước bản nháp.

Điều này cũng giải thích quan sát của người dùng khi gọi thẳng API: ít ràng buộc thì đẹp hơn. Nhưng chỗ ràng buộc thật sự gây hại là **lời văn trong prompt**, không phải chi tiết trong ảnh nháp.

## 4. Việc tiếp theo mà kết quả này chỉ ra

Giả thuyết "input trung gian" (giữ mái, bỏ lam) **tụt độ ưu tiên**: C0 chỉ đem lại +1.25 nên biến thể của C0 khó vượt được +4.25 của prompt freedom.

Ưu tiên chuyển thành: **đặt `design_within_envelope` làm mặc định cho pack marketing**, rồi dồn sức vào lưới an toàn — bộ kiểm VLM cho camera và vị trí khối — vì đó là thứ biến 3/4 massing thành chấp nhận được.
