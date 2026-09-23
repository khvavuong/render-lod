# V365 — E3: Ablation input conditioning (C0 / C1)

**Thực hiện:** 2026-09-18 · sau E0 và E2
**Thiết kế:** 2 model × 2 góc (site, facade) × 2 input = 8 ảnh, cùng camera, cùng `design_within_envelope`, cùng provider
**C0** khối trung tính — cờ `--neutral-massing` bỏ toàn bộ `create_design_details`
**C1** control render hiện tại

## 1. Giả thuyết được kiểm nghiệm

E0 đo được trên model A: **42 element nguồn**, nhưng **116 facade, 42 dock, 15 lối vào, 2 mái** đều
do `plan-design` sinh ra. Prompt gọi tất cả là *"approved design"*. Giả thuyết nêu từ đầu dự án:
gửi một thiết kế nửa vời rồi bắt giữ nguyên sẽ **chặn trần chất lượng**, và khối trắng sạch sẽ cho
kết quả tốt hơn.

Lần thử trước dùng `clay.png` không tách được biến vì file đó vẫn mang lam đỏ. Đây là lần đầu
kiểm nghiệm đúng cách.

## 2. Chất lượng thiết kế — giả thuyết đúng

**A/view-01 (aerial).** C0 cho mái dốc có sống mái thật, pavilion văn phòng lắp kính curtain wall,
khối sẫm có biển "TECH-BASE", nhà bảo vệ, bãi xe và cây cọ. Đọc ra như một khu công nghiệp được
thiết kế thật. C1 cho lại đúng grammar tự sinh: nhà xưởng kem phẳng với sọc đỏ.

**A/view-05 (facade).** C0 cho portal lối vào có canopy đỏ và góc kính, biển "APEX LOGISTICS",
khối nhấn sẫm — điềm đạm và đáng tin. C1 cho tháp lam đỏ quen thuộc, ồn hơn và giống render hơn.

Cả hai góc đều nghiêng về C0.

## 3. Giữ hình học — giả thuyết sai

| | C0 massing | C1 massing |
|---|---|---|
| A view-01 | pass (base 4, gen 4) | pass (base 2, gen 2) |
| A view-05 | pass | pass |
| B view-01 | **fail** — thêm một khối | pass |
| B view-05 | **fail** — thêm một khối trong hàng rào | pass |

**C0 trượt 2/4, toàn bộ trên model B. C1 đạt 4/4.**

Và một điều tinh vi hơn ở A/view-01: base của C0 có **4 khối hộp phẳng** còn base của C1 có **2 mái
liên tục**. Cả hai đều "khớp base của chính nó", nhưng nghĩa là **C0 không hề bị ràng buộc bởi số
mái mà Design DNA cam kết** — `--neutral-massing` bỏ luôn `roof_assemblies`, tức bỏ chính thứ mà
`verify-massing` tồn tại để đo.

## 4. Kết luận

Giả thuyết **đúng về cái đẹp, sai về an toàn**. Khối trắng sạch mua được chất lượng thiết kế bằng
giá của độ trung thực hình học, và trên model B cái giá đó là 100% số view.

C0 đã bỏ **mọi thứ** cùng lúc: grammar mặt tiền, cụm mái, và dock. Nhưng chỉ có grammar mặt tiền
là thứ bị nghi chặn trần chất lượng; cụm mái lại chính là thứ cổng đang đo và là cam kết thật của
Design DNA.

**Việc tiếp theo có căn cứ: một input trung gian** — giữ `roof_assemblies` và vị trí dock, bỏ
grammar mặt tiền (lam, dải nhấn, clerestory). Cần một cờ hẹp hơn `--neutral-massing`, và đó là thí
nghiệm đáng làm tiếp chứ không phải chốt C0 hay C1.

## 5. Giới hạn

Mỗi ô **một mẫu**, chưa lặp. Nhận xét về cái đẹp là của một người, **chưa qua review mù** — công cụ
`scripts/blind_review.py` đã có nhưng chưa dùng cho bộ này.

C2 (PBR tăng cường) **chưa chạy**: chưa có chế độ render tương ứng, nên E3 mới trả lời được một nửa
câu hỏi của kế hoạch.
