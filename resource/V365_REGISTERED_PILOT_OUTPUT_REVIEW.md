# V365 — Registered pilot: triển khai và đánh giá output

Ngày: 18/09/2026. Phạm vi: tiếp nối P0/P1, không editing, không thay Tender/Legacy.

## Kết luận

Luồng đăng ký thiết kế → camera preview → sáu ảnh → review đã hoạt động qua API/worker.
Sáu ảnh đều sinh thành công; **bộ ảnh chưa đạt exit bàn giao**. Chất ảnh có triển vọng,
nhưng camera, câu chuyện từng shot và identity chưa ổn định. Không bật mặc định Marketing
và không gọi đây là hoàn tất P2–P5 về chất lượng.

Người dùng chọn proposal tổng thể làm hướng chính cho vòng này. Lựa chọn chỉ áp dụng
cho job này, không hardcode kiến trúc/palette vào các phương án sau. Brief/reference mới
vẫn tạo job/input snapshot khác; mỗi phương án đăng ký family riêng. Hiện mỗi job có một
family immutable; chưa có UI batch nhiều phương án hoặc nhiều revision family trong một job.

## Phần đã triển khai

- P2: chọn anchor cụ thể; family ID từ source/anchor/yêu cầu; provenance `source` và
  `client_approved`, evidence/scope/reviewer; công năng và mặt khuất chưa duyệt giữ unknown.
  API nhận requirements theo từng field; UI hiện nhận định hướng qua notes, chưa có editor
  từng field. Một anchor chưa chứng minh toàn bộ master family tương thích.
- P3: runtime candidate search theo bounds/target scene, semantic composition scores,
  collision screening, diversity và contact sheet; chọn một camera cho mỗi purpose.
  `envelope_only` bỏ design programme/facade/context/entourage procedural, giữ source geometry.
  Scores là soft priors; occlusion/mặt khuất chưa có đo lường đầy đủ và chưa phải fidelity output.
- P4: worker gửi toàn bộ reference, selected design và geometry image với typed roles;
  frozen prompt/reference instructions/model/hash; reservation/cache riêng, cap sáu ảnh;
  stage QA giữ fidelity/realism/consistency unknown; UI đối chiếu source/output từng cặp,
  checklist và evidence notes; board chỉ xuất sau review approve. Human review marketing
  không trở thành `geometry_certified` hoặc certification `approved_final`.
- P5: opt-in, không auto retry chất lượng thấp, có API progress/call reservations;
  tests hai kích thước site tổng hợp chứng minh camera thay đổi theo bounds. Chưa có
  benchmark ảnh nhiều site/LOD, đối chứng legacy tương đương hoặc rollout exit.

## Pilot chạy thật

Job `job-cabc3257a982fe39`, family `family-beb2995f062cc4166b28`.
Parent proposal view-01 đã được người dùng chọn; view-05 độc lập không dùng làm anchor thứ hai.
Provider model được giữ từ snapshot parent. Hai proposal trước + sáu ảnh registered =
**tám reservations** tổng cộng; không gọi VLM hoặc thêm image retry trong vòng này.

Camera pool có 48 candidates, render 512×288 qua Docker/Blender. Vòng đầu không có
office candidate hợp lệ vì source không có `office_block`. Đã giữ bằng chứng cũ và
rerender tám camera office về source entrance, không tự thêm office vào source contract.
Geometry của entrance không chứng minh facade văn phòng đã thiết kế. Đây là hạn chế rõ.

Ảnh provider là JPEG 2752×1536 (request 2K/16:9). Job dừng `human_review`;
delivery chưa approved. Artifact root:
`.artifacts/generated/a7d22ba36b4fa342/R01-30c3e1709447/job-cabc3257a982fe39/registered/`.

[Board review — chưa duyệt](../.artifacts/reference_led_registered_pilot/a7d22ba36b4fa342-R01-30c3e1709447-standard-v40-cabc3257/review_board.jpg),
[camera contact sheet](../.artifacts/generated/a7d22ba36b4fa342/R01-30c3e1709447/job-cabc3257a982fe39/shots/contact_sheet.jpg),
[advisory review/hash evidence](../.artifacts/generated/a7d22ba36b4fa342/R01-30c3e1709447/job-cabc3257a982fe39/registered/agent_visual_review.json).

## Sử dụng luồng mới

UI Reference-led panel: chọn proposal → nhập reviewer/notes → đăng ký thiết kế → search
camera → xem contact sheet và chọn một candidate cho mỗi role → lưu shots → xác nhận
generate sáu ảnh → đối chiếu từng cặp geometry/output → ghi notes/checklist → approve/reject.
Review reject không tự cấp ngân sách hoặc tạo lại ảnh. Đổi thiết kế sau generation cần job mới.

API bổ sung: `design-registration`, `reference-progress`, `shots/search`, `shots/select`,
`shots/previews/{candidate_id}`, `registered-generation`, `delivery-review` dưới
`/v1/view-sets/{view_set_id}/`. Khởi động lại backend/worker và deploy frontend build mới.
CLI diagnostic có `--execute`/`--generate` rõ ràng, không tự approve hoặc đổi snapshot job cũ.

## Đánh giá trực tiếp sáu ảnh

Đây là đánh giá advisory của agent qua ảnh thật và preview, không phải người dùng ký duyệt,
VLM score, phép đo kích thước 3D hay kết luận thống kê. Không dùng số điểm thẩm mỹ tự bịa.

| Output | Purpose | Quan sát / vấn đề |
|---|---|---|
| view-01 | context | Chất ảnh tốt, xe cab-over/xe máy/cổng có bối cảnh phù hợp; ground preview bị chuyển thành aerial. Có chữ/branding tự sinh không đáng tin. |
| view-02 | detail/reverse | Aerial rõ bố cục; mái chia đoạn/office thay đổi so với các ảnh khác. Không chứng minh reverse camera hoặc topology source đúng. |
| view-03 | hero | Ánh sáng ấm, vật liệu tốt; thành aerial thay vì human-scale. Input search v2 cũng có lỗi eye height cho role này, không quy toàn bộ lỗi cho provider. |
| view-04 | loading_detail | Xe/cấu tạo vận hành có triển vọng; ảnh vẫn aerial và nghiêng về office tổng thể, không thể hiện operations ở eye level. |
| view-05 | office_hero | Office/glazing/canopy nhìn đẹp nhưng vẫn aerial; tỷ lệ office và mái thay đổi giữa các ảnh. Preview entrance không đủ evidence office architecture. |
| view-06 | overall | Hai shed đọc rõ, bối cảnh công nghiệp có triển vọng; office/canopy/cổng khác nhóm view-03–05. Fidelity đo được chưa xác minh. |

Toàn bộ sáu output có viewpoint nâng cao/aerial. Những role có preview eye-level
(context, office, loading) không giữ viewpoint. Ba ảnh không đáp ứng mục đích ground shot;
hero cũng không đáp ứng câu chuyện human-scale. Giữ cùng màu/vật liệu không đủ để gọi
là cùng thiết kế. Biển chữ và một số xe/cảnh quan vẫn cần review chi tiết.

## Sửa sau khi có kết quả — chưa gọi provider lại

Phát hiện `propose_candidates` cộng rise theo elevation ngay cả khi pack đã khai báo
eye height, làm hero 2.6 m thành camera cao hàng chục mét. Policy source-only mới dùng
`respect_eye_height=True`; legacy không đổi. Search recipe `source-eye-height-v3` có
test giữ eye height cho hero. Job đã chọn/generate giữ nguyên camera/prompt v2, không
ghi đè artifacts hoặc làm mất lineage.

Prompt cho selection mới tách authority theo field: source quyết định massing/placement,
geometry evidence quyết định frame, anchor chỉ quyết định identity kiến trúc; không lấy
góc aerial của anchor cho shot ground. Sửa prompt là giả thuyết cần thử lại, **chưa có
bằng chứng ảnh mới đã hết lỗi camera/consistency**. Không chữa bằng cách khóa palette,
motif hay programme cho mọi nhà xưởng.

## Điều kiện trước khi hoàn tất các phase

1. Thử có budget riêng một shot office và một shot logistics với camera recipe v3,
   authority frame/identity đã tách. So trực tiếp output với geometry preview và anchor.
2. Nếu vẫn copy aerial anchor, cần geometry-compatible approved proxy/visible-face evidence
   và branch geometry-conditioned có khả năng kiểm soát thực, không retry prompt vô hạn.
   Không gọi image-reference là hard depth control.
3. Bổ sung facade master của cùng family và review compatibility/mặt khuất trước full set;
   programme source/client-approved mới được khóa. Không tái dùng proposal office độc lập.
4. Chỉ sau khi một bộ sáu ảnh đạt human review và fidelity theo scope mới chạy benchmark
   site/LOD thứ hai với budget chốt riêng và đối chứng chất lượng phù hợp, rồi xét default.

## Kiểm chứng phần mềm

Backend 257 tests passed; frontend 17 tests passed; kiểm tra Ruff, frontend lint/build.
Tests gồm lineage, stale anchor, reservations, checkpoint không gọi lại provider, fidelity
unknown, human approval gates, hai kích thước site tổng hợp và UI không auto approve.
Các tests này không chứng nhận chất lượng ảnh hoặc exit P4/P5.
