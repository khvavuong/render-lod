# V365 — trạng thái triển khai chất lượng render

Ngày: 2026-09-18. Theo `V365_RENDER_QUALITY_RESEARCH_PLAN.md`.

## Kết luận hiện tại

Đã triển khai lớp workflow, input trung gian và an toàn lựa chọn ảnh. Đã chạy Blender và hai ảnh
Gemini thực tế trên model B. **Chưa có bộ sáu ảnh đạt điều kiện bàn giao marketing**. Không suy ra
chất lượng thị giác từ việc test pass, và không coi verdict của vision judge là chứng nhận hình học.

## Thay đổi đã đưa vào code

- UI có lựa chọn **Marketing / thiết kế** riêng. Marketing dùng `marketing_hero` và pack
  `marketing_photoreal`; preview có thể phát triển thiết kế để duyệt master; hồ sơ thầu vẫn dùng
  `tender_final`, không bị chuyển ngầm sang thiết kế tự do.
- API nhận `style_pack_id` từ thư mục catalog, không nhận đường dẫn tùy ý từ client.
- Job lưu snapshot style pack và view set. Identity của job tính cả nội dung pack và nội dung/role
  reference. Job có style dùng view-set ID, thư mục render/generation và camera snapshot riêng:
  đổi brief không dùng lại master đã duyệt của một job khác. Job cũ vẫn đọc layout legacy.
- Prompt, request provider, site master, facade master, các view tiếp theo và repair cùng nhận
  `design_freedom`/context policy. Provider không ép lại facade grammar khi đang phát triển thiết kế.
- `resolve_proxies` yêu cầu nhà lân cận thật ở vị trí guide, không yêu cầu khối trong suốt và không
  composite placeholder lên ảnh đã hoàn thiện. Manifest ghi các policy có hiệu lực.
- Blender có `--facade-mode envelope_program`: giữ mái liên tục, khối nhà, gate và cửa chức năng;
  chỉ bỏ nhóm chi tiết mặt đứng procedural như stripe/fin/frame/clerestory. Đây không phải C0
  `--neutral-massing`, vốn xóa cả roof assembly. Đây cũng chưa phải C2 tăng cường PBR.
- Renderer chạy script đang checkout, thay vì bản COPY cũ trong Docker image; ghi hash script và
  mode vào manifest, kiểm tra lại cache. Sửa `os.getuid/getgid` cho Windows.
- Camera planner v40 tính clearance cho office theo ray thực tại vị trí chụp, thay vì lấy một nửa
  corridor gap cho mọi góc; cân đối lens/tilt với roofline. Có `output_path` để thử nghiệm mà không
  ghi đè camera của design đang sử dụng.
- Camera candidate solver dùng chiều dài/rộng thực và bearing; không dùng cube có cạnh bằng
  chiều cao. Search tool dùng focus buildings, target theo role từ analytic anchors, pool tối đa
  48 candidate với catalog sáu role hiện tại, kiểm tra camera nằm trong building AABB và tạo board
  semantic để duyệt. Corner prior dùng surface normal thay cho cân bằng trái/phải của silhouette.
- Selection không nhận `review/unverified` như pass, không phục hồi candidate đã bị QA loại,
  không xuất một bộ thiếu view, không ghi đè thư mục có artifact cũ. Audit cache kiểm tra hash
  base/output. Candidate khác Design Master không được trộn; có `--master-sha256` chọn lineage.
  Bộ đủ view vẫn mang trạng thái `requires_set_review`, không tự nhận đã đạt marketing.

## Kiểm chứng thị giác thực tế

Artifact mới nằm tại `.artifacts/quality_v4/`; không ghi đè bộ v3.

| Thử nghiệm | Kết quả | Quyết định |
| --- | --- | --- |
| Model B, overall, input envelope_program | Vật liệu và bối cảnh công nghiệp nhìn tự nhiên hơn; model thêm dock/ramp. Vision judge: viewpoint=same, placement=true, openings=false → review. Quan sát thủ công còn nghi ngờ đổi framing. | Không duyệt, không đưa vào bộ bàn giao. |
| Model B, office, camera v40, input envelope_program | Input không còn cây chắn giữa ô office lớn như góc v39. Ảnh proposal có facade tiết chế hơn, vật liệu và landscape đáng tin hơn. Vision judge: same/true/true → pass. | Chỉ là proposal độc lập. Chữ signage sai/ngụy tạo và palette vẫn cần kiểm duyệt; chưa được duyệt marketing. |

Ảnh xem thử:

- `.artifacts/quality_v4/generated_B/view-01/unbranded_refined.jpg`
- `.artifacts/quality_v4/office_proposal_B_v40/view-05/unbranded_refined.jpg`
- Input office mới: `.artifacts/quality_v4/office_B_v40/view-05/base_rgb.png`

Hai proposal được generate độc lập, **không phải hai góc của một thiết kế đã chứng minh nhất quán**.
Không có ablation lặp nhiều lần trong lần triển khai này; không tuyên bố tăng chất lượng theo tỷ lệ %.

## Kiểm chứng kỹ thuật

- Backend: **237 tests pass**, gồm test mới về snapshot/idempotency, namespace riêng, policy gửi
  provider, clearance office, corner prior và chặn fallback/mixing master.
- Frontend: **13 tests pass**, 4 test files; production build pass sau khi bổ sung option marketing.
- Ruff các module được chỉnh và `git diff --check` đã được kiểm tra. Có cảnh báo deprecation
  FastAPI/Starlette và bundle frontend lớn; không phải lỗi chất lượng ảnh.

## Phần chưa hoàn thành — không đánh dấu E1–E5 đã đạt

1. **Camera search chưa được tích hợp làm bước tự chọn mặc định trong background job.** Workflow
   mặc định vẫn dùng planner analytic v40 + conditioning preflight. Search là công cụ nghiên cứu;
   normal prior/crowding score chưa phải phép đo occlusion hoặc coverage bằng surface ID chính xác.
   Chưa chạy hết pool 48 ảnh và benchmark trên nhiều site sau các sửa này.
2. Cần tách programme proposal khỏi chứng cứ nguồn: số dock/office do grammar tự sinh không tự
   động trở thành yêu cầu của khách hàng. Hiện input trung gian vẫn giữ programme của Design DNA.
3. Cần chốt một site/facade master **cùng lineage**, rồi generate sáu view và kiểm tra các facade,
   office, dock, gate, roof, palette/context ở mức toàn set. Hash chung chỉ là điều kiện cần,
   không đủ để chứng minh cùng kiến trúc.
4. Cần gate thẩm mỹ tuyệt đối và proof chi tiết: signage/logos/chữ ngụy tạo, vật liệu, anatomy,
   scale, façade composition và độ sạch của ảnh. Không chọn ảnh chỉ vì đẹp nhất trong nhóm xấu.
5. C2 PBR/entourage chất lượng cao, tối thiểu ba lần lặp mỗi ô và hai người blind-review vẫn còn
   phải thực hiện theo kế hoạch gốc. Chưa có đủ bằng chứng để bỏ một nhánh nghiên cứu.

## Cách dùng increment hiện tại

Khởi động lại backend/worker với code mới và rebuild frontend. Trong UI chọn **Marketing / thiết
kế**; duyệt site/facade Design Master trước khi generate tiếp. Các job mới có style không dùng lại
artifact/master của job cũ. Không duyệt master có dock/ramp hay khối nhà được model tự thay đổi.

Điểm chốt bàn giao vẫn là: cả sáu view cùng thiết kế, đúng programme đã thống nhất, góc đẹp theo
site, không lỗi signage/placeholder, đủ chi tiết ảnh gốc và được kiểm duyệt toàn set. Pilot office
mới chứng minh hướng này có tiềm năng, **chưa chứng minh đã đạt toàn bộ điều kiện trên**.
