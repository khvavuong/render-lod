# Reference-led: trạng thái triển khai increment đầu

Trạng thái tiếp nối mới nhất:
[Registered pilot: triển khai P2–P4 và đánh giá sáu output](V365_REGISTERED_PILOT_OUTPUT_REVIEW.md).
Các mục bên dưới mô tả increment P0/P1; exit chất lượng P4/P5 vẫn chưa đạt.

Ngày cập nhật: 18/09/2026. Kế hoạch gốc:
[Production integration plan](V365_REFERENCE_LED_PRODUCTION_INTEGRATION_PLAN.md).

## Kết quả và phạm vi

Đã tích hợp pilot `reference-led-proposal-v1` vào API, job, Gemini provider và UI chính.
Đây là increment P0/P1, không phải hoàn tất P2–P5 hoặc bộ sáu ảnh bàn giao.
Legacy vẫn là mặc định; pilot phải bật riêng trong chế độ Marketing. Tender không
được chạy policy này. Không có editing/inpainting trong increment này.

Pilot gửi brief, mục đích ảnh, source envelope đo được và tất cả reference có vai trò
rõ ràng. Không gửi camera pose, conditioning passes, facade render, identity lock hoặc
programme chưa duyệt. Reference kiến trúc được phép hướng dẫn thiết kế; ảnh construction
hướng dẫn cấu tạo, vật liệu và tính chân thực. Không áp navy/white chung cho mọi dự án.

Mỗi job tạo tối đa hai proposal độc lập: tổng thể và văn phòng. Chúng không được gọi là
một bộ ảnh đồng nhất hoặc master family đã duyệt. Lưu lựa chọn chỉ ghi nhận hướng concept,
giữ trạng thái review và không tự sinh các góc còn lại.

## Đã triển khai

- Snapshot version, model, source/reference SHA-256, brief, reference instructions và prompt
  cho từng mục đích. Snapshot tham gia job identity; worker dùng prompt đã lưu.
- So khớp input trước khi gọi provider; manifest lưu input signature, output hash và request ID.
- Reservation độc quyền tồn tại qua crash; không tự gọi lại khi trạng thái gọi không chắc chắn.
  Hai ảnh hoàn tất có thể được dùng lại mà không trả tiền thêm. Thất bại không tự cấp retry budget.
- Pilot không dùng implicit baseline reference hoặc cắt danh sách reference còn hai ảnh.
- UI upload reference kiến trúc và construction/vật liệu, brief riêng, nhãn proposal/review,
  timeline đúng với các bước thực sự chạy và thao tác lưu lựa chọn.
- Kiểm tra hash hai output khi lưu/đọc lựa chọn; không chứng nhận geometry, consistency hoặc delivery.

Golden tests giữ BRIEF và hai photo intents của trial R1, kiểm tra authority/payload không
có legacy locks. Reference instructions đã được tổng quát hóa để không hardcode palette;
chưa có bằng chứng parity byte-for-byte của toàn bộ payload hoặc benchmark nhiều site.

## Chạy thật qua luồng chính

Script `scripts/run_reference_led_main_pilot.py` mặc định dry-run; `--execute` đi qua API
upload/create job rồi gọi worker thật, không tự duyệt. Diagnostic tắt background dispatch
trong tiến trình thử riêng để tránh hai worker cùng chạy. Snapshot/artifacts vẫn dùng cơ chế chính.

Job: `job-cabc3257a982fe39`.
View set: `a7d22ba36b4fa342-R01-30c3e1709447-standard-v40-cabc3257`.
Kết quả: `design_master_review`, `marketing_generative_review`, chưa chọn hoặc duyệt bàn giao.
Hai JPEG thực tế có kích thước 2752×1536, từ request 2K/16:9:

- [Proposal tổng thể](../.artifacts/generated/a7d22ba36b4fa342/R01-30c3e1709447/job-cabc3257a982fe39/view-01/refined.jpg).
- [Proposal văn phòng](../.artifacts/generated/a7d22ba36b4fa342/R01-30c3e1709447/job-cabc3257a982fe39/view-05/refined.jpg).
- [Diagnostic result](../.artifacts/reference_led_main_pilot/result.json).

Quan sát trực tiếp: vật liệu, ánh sáng và bố cục có triển vọng; ngôn ngữ văn phòng hai ảnh
khác nhau, layout source chưa được xác minh. Đây chỉ là một pilot hai ảnh, không phải
đánh giá thống kê, human approval hoặc bằng chứng sáu góc giữ nguyên thiết kế.

## Cách sử dụng

Chọn Marketing → bật “Marketing pilot” → upload reference kiến trúc/board và ảnh construction
→ nhập brief nếu có → tạo hai proposal → review và lưu lựa chọn. Backend/worker cần khởi động
lại bằng code mới; frontend cần bản build mới. Giữ pilot tắt để chạy workflow legacy.

## Kiểm chứng

- Backend: 249 tests passed; có hai deprecation warnings từ thư viện test.
- Frontend: 14 tests passed; lint và production build được kiểm tra.
- Có tests payload ba typed references, frozen model, không đọc conditioning,
  dừng đúng review, lưu lựa chọn không phát sinh delivery, output bị đổi,
  reference bị đổi, in-flight call và reservation còn lại sau crash.
- Test phần mềm không thay thế đánh giá chất lượng ảnh hoặc xác minh thiết kế.

## Các bước còn lại theo kế hoạch

P2 cần người dùng chọn hướng thiết kế, sau đó đăng ký master family và provenance từng
field/programme. Hiện chưa có điều khiển chọn riêng một ảnh để lập master family.
P3 cần camera/shot search theo scene và envelope-only conditioning; pilot hiện chỉ có
purpose slots và AI tự chọn camera, không được diễn giải thành registered source views.
P4 cần sinh các góc theo cùng thiết kế đã đăng ký, stage-aware QA, kiểm tra source và delivery gate.
P5 cần benchmark nhiều site, ổn định chi phí và rollout có kiểm soát trước khi đổi mặc định.

Không đưa hai proposal độc lập vào marketing delivery hoặc sửa lại bằng legacy hard locks
để che việc thiết kế/camera chưa được đăng ký. Quyết định thiết kế đã duyệt là đầu vào cần
thiết cho bước tiếp theo; không suy ra quyết định đó từ việc pilot chạy thành công.

## Bổ sung bối cảnh Việt Nam

Prompt mới có context revision `vietnam-industrial-v1` cho cả tổng thể và văn phòng:
xe tải/đầu kéo cab-over, xe con và xe máy có vị trí phù hợp; cổng/chốt bảo vệ, khoảng thông
xe tải; kết cấu thép, mái/vách tôn, che nắng mưa, thoát nước và sân công nghiệp. Đây là
hướng dẫn thiết kế theo vùng, không bắt buộc một loại cổng, màu sắc, dock hoặc số xe.
Không mặc định mọi nhà xưởng là trung tâm logistics. Brief dự án được ưu tiên hơn mặc định.
Reference ngoại quốc phải được thích nghi với bối cảnh Việt Nam thay vì sao chép nguyên xe/cổng.

Job mới lưu context trong frozen prompts và reference instructions nên thay đổi này tạo
job identity mới. Job/ảnh đã tạo giữ nguyên snapshot, không tự sinh lại hoặc phát sinh phí.
Chưa chạy ảnh provider mới cho thay đổi này; cần review ảnh mới để xác nhận hiệu quả thị giác.
Backend hiện 251 tests passed; lint frontend và build được kiểm tra lại.
