# V365 — Reference-led freedom: kết quả thử nghiệm

Ngày chạy: 2026-09-18. Đây là nghiên cứu tách biệt, chưa thay đổi pipeline production.

## 1. Kết luận từ ảnh thực tế

**Model hiện tại có khả năng tạo kiến trúc và vật liệu gần mục tiêu tham khảo hơn rõ rệt.
Nhưng bỏ khóa hoặc thêm lệnh khóa bằng prompt đều chưa bảo đảm ảnh đúng dự án.**

Không nên chọn giữa hai cực “khóa mọi chi tiết bản dựng” và “AI tự vẽ toàn bộ dự án”.
Hướng ưu tiên là reference-led design development, chọn camera theo site, rồi kiểm chứng
những dữ kiện thực sự có nguồn. Đây là hướng được bằng chứng hiện tại hỗ trợ, **chưa phải
phương án tối ưu đã được chứng minh trên nhiều site hoặc bộ sáu ảnh**.

## 2. Thiết kế thử nghiệm

- 24/24 ảnh hoàn thành, 0 lần generate thất bại; không tự retry.
- Một site/model B; hai mục đích ảnh: aerial và office; ba lần generate độc lập mỗi ô.
- Cùng model cấu hình `gemini-3-pro-image`, cùng brief, reference, yêu cầu 2K và 16:9.
  Không có seed được kiểm soát; ba lần lặp không phải ba seed tái lập được.
- Reference: `sample_image_4.png` là chính bảng ảnh người dùng cung cấp;
  `sample_image_3.png` bổ sung kiến trúc/vật liệu nhà xưởng.
- Cả bốn nhóm cùng hướng vật liệu navy/white từ reference. Không so điểm trực tiếp với
  benchmark cũ dùng palette khác để tuyên bố một mức cải thiện có quan hệ nhân quả.
- Source contract chỉ có hai envelope shed 125 × 60 × 15.1 m, song song, khoảng cách
  envelope 22 m. Bbox không thay thế mesh chính xác hay chứng minh roof đã được duyệt.
- Programme 2 entrance, 6 loading door, 2 roof assembly là **đề xuất của Design DNA**,
  không tự động là yêu cầu IFC/chủ đầu tư.

| Nhóm | Thay đổi ràng buộc | Mục đích |
|---|---|---|
| R0 | Reference + brief; không source envelope, camera tự do | Đo khả năng tạo concept đẹp; không phải ảnh đúng model B |
| R1 | R0 + bbox/quan hệ vị trí source bằng text; camera tự do | Kiểm tra liệu mô tả envelope đủ giữ dự án |
| R2 | R1 + ảnh dựng đăng ký camera/envelope; không khóa facade/openings đề xuất | Kiểm tra ảnh dựng có giữ hình học mà vẫn cho thiết kế tự do |
| R3 | R2 + khóa programme/openings đề xuất | Đo tác động của khóa thêm chương trình công năng |

R2 đồng thời thêm ảnh dựng và lệnh giữ camera; không dùng đối chiếu R1–R2 để tách riêng
tác động của camera khỏi tác động của ảnh conditioning.
Không có nhóm no-reference với brief mới, nên vòng này chứng minh khả năng của cấu hình
reference-led hiện tại, không đo riêng mức tăng do reference hay từng câu của brief.

Config: [reference_freedom_v1.json](research/reference_freedom_v1.json).
Hash config: `2163e075b9d91db3b877200b129fc9ae1090b02083a69fa8035674b6b6ab9979`.
Request, input hash, output hash và trạng thái từng lần gọi được lưu trong
`.artifacts/reference_freedom_v1/`; ảnh gốc không qua sửa hay làm đẹp hậu kỳ.

## 3. Quan sát trực tiếp

Đây là nhận xét của agent điều phối sau khi xem bảng ảnh và ảnh gốc đại diện,
**không phải hai người chấm mù độc lập**, cũng không phải đo geometry tự động.

| Nhóm | Thiết kế/chất ảnh quan sát được | Vấn đề |
|---|---|---|
| R0 | Office có phân cấp tốt, canopy, kính và cladding thuyết phục; góc chụp hấp dẫn | Aerial không mô tả source B; có bản tự sinh chữ/branding mặc dù brief cấm |
| R1 | Office được phát triển phong phú; aerial có vật liệu và cảnh quan khá tốt | Aerial rep-1/2 thể hiện khối giao nhau/thay quan hệ song song; rep-3 có hai shed song song nhưng chưa đo được footprint |
| R2 | Vẫn phát triển được office và vật liệu; không bị buộc về facade procedural | Cả ba aerial không giữ bố cục camera đăng ký: rep-1 đổi hướng mặt công năng; rep-2/3 chuyển sang bố cục nhìn thẳng trục giữa hai shed |
| R3 | Vật liệu tương đối thật; office giữ mặt công năng đơn giản hơn | Khóa thêm programme không đủ giữ aerial camera; office mất bớt phân cấp so với các nhóm tự do hơn |

Ví dụ phản chứng quan trọng: aerial R2 rep-1 khá đẹp, nhưng base nhìn vào hai mặt đầu
shed và một mặt dọc phía trong; output chuyển sang nhấn mặt dọc loading ở phía ngoài,
tạo office lớn và sân logistics khác. **Không được lấy “hai shed” làm bằng chứng “đúng camera”.**

Office là góc nhìn cục bộ: không thể suy từ một ảnh office rằng toàn campus đúng số lượng,
vị trí, footprint. Aerial và office được generate độc lập; chưa có Design Master chung,
không được ghép các ảnh đẹp nhất thành một bộ marketing rồi tuyên bố nhất quán.

Bảng ảnh để đối chiếu:

- [R0](../.artifacts/reference_freedom_v1/review/R0_reference_free_board.jpg)
- [R1](../.artifacts/reference_freedom_v1/review/R1_source_envelope_board.jpg)
- [R2](../.artifacts/reference_freedom_v1/review/R2_registered_camera_board.jpg)
- [R3](../.artifacts/reference_freedom_v1/review/R3_locked_programme_board.jpg)

## 4. Review bổ sung

Review đã bao phủ cả 24 mẫu: **42 lượt chấm riêng biệt**, 41 thành công, một lượt không
trả JSON hợp lệ. Chấm thẩm mỹ có điểm cho **23/24 ảnh**; R2 office rep-1 giữ unavailable,
không retry, không tính điểm 0. Source audit 18/18 có verdict; R0 không có source audit.
Review thẩm mỹ dùng mã ảnh opaque, không truyền tên nhóm cho judge. Audit source/camera/
programme chạy riêng; office thiếu bằng chứng phải được xem là chưa biết.

Điểm 1–5 dưới đây là **VLM advisory**, không phải điểm của hai người duyệt. Design và
realism ghi trung bình [min–max]; composition/material ghi trung bình. Mỗi ô có ba ảnh
generate, nhưng số mẫu có điểm được nêu riêng để không che lượt chấm lỗi.

### Office

| Nhóm | Có điểm | Composition | Design [range] | Realism [range] | Material/light | Shortlist thẩm mỹ |
|---|---|---|---|---|---|---|
| R0 | 3/3 | 4.67 | 4.33 [4–5] | 5.00 [5–5] | 5.00 | 3/3 |
| R1 | 3/3 | 4.67 | 5.00 [5–5] | 5.00 [5–5] | 5.00 | 3/3 |
| R2 | **2/3** | 4.00 | 4.50 [4–5] | 5.00 [5–5] | 5.00 | 2/2 có điểm; 1 unknown |
| R3 | 3/3 | 3.00 | 3.33 [3–4] | 3.33 [3–4] | 3.33 | 0/3 |

### Aerial

| Nhóm | Có điểm | Composition | Design [range] | Realism [range] | Material/light | Shortlist thẩm mỹ |
|---|---|---|---|---|---|---|
| R0 | 3/3 | 4.00 | 4.33 [4–5] | 4.67 [4–5] | 4.67 | 3/3 |
| R1 | 3/3 | 4.67 | 4.00 [4–4] | 3.67 [3–4] | 4.00 | 2/3 |
| R2 | 3/3 | 4.33 | 4.67 [4–5] | 4.33 [4–5] | 4.33 | 2/3 |
| R3 | 3/3 | 4.67 | 4.67 [4–5] | 4.33 [3–5] | 4.33 | 2/3 |

17/23 ảnh có điểm vượt quy tắc shortlist: cả bốn trục chính ≥4 và không có critical
defect do judge ghi. Đây **không phải 17 ảnh đủ bàn giao**. Programme lock có xu hướng
bất lợi rõ ở office trong mẫu này, **không làm aerial xấu hơn trên mọi trục**: aerial
R2/R3 hòa design và realism trung bình. Không suy từ đó rằng mọi loại khóa đều xấu,
hay chọn R1 làm mặc định dự án chỉ vì điểm office cao.

### Audit camera/source: chỉ là các claim của VLM

| Nhóm / góc | Same | Shifted | Different |
|---|---|---|---|
| R2 aerial | 1/3 | 2/3 | 0/3 |
| R2 office | 1/3 | 2/3 | 0/3 |
| R3 aerial | 1/3 | 1/3 | 1/3 |
| R3 office | 2/3 | 0/3 | 1/3 |

Aerial R1: judge gọi layout plausible 1/3, R2 2/3, R3 3/3. Đây không phải tỷ lệ
geometry đạt theo phép đo: plausible chưa kiểm footprint/height chính xác. R3 aerial
programme retained chỉ 1/3 theo judge, nên thêm programme lock cũng chưa bảo đảm giữ
công năng. Không dùng field programme của R2 để đánh trượt vì R2 không khóa programme.
Không thống kê verdict layout của office thành tỷ lệ đạt/trượt toàn campus.

Raw dữ liệu: [results.json](../.artifacts/reference_freedom_v1/review/results.json).
CSV để hai người chấm độc lập:
[human_score_sheet.csv](../.artifacts/reference_freedom_v1/review/human_score_sheet.csv).

VLM cùng provider/model với generator chỉ dùng để triage, không phải người duyệt hay
chứng nhận geometry. Nhận xét như “cửa ngang nền không vận hành được” hoặc đọc vùng
office trong base thành loading door cần đối chiếu công năng thật; không mặc nhiên
chuyển thành lỗi bắt buộc. `quality_shortlist` không đồng nghĩa `marketing_approved`.

**Lỗi judge đã quan sát được:** R1 office rep-2/3 bị trả `source_layout_plausible=false`
vì ảnh chỉ thấy một công trình, trong khi source có hai shed. Đây là suy luận không hợp lệ
từ góc cục bộ, mặc dù prompt đã yêu cầu không suy toàn campus. Hai verdict này phải được
xử lý là **chưa đủ bằng chứng**, không phải hai ca source fail đã xác nhận. Giữ raw verdict
để truy vết, không sửa âm thầm thành pass. Tương tự, `camera_matches=same` chỉ là nhận
diện góc tương đối của judge, chưa chứng minh registration/perspective chính xác.
R1 aerial rep-3 còn bị judge liệt kê bảng trắng không chữ thành critical defect, trong
khi brief cho phép signage để trống. Đây là bất đồng rubric cần review, không phải bằng
chứng phải ép AI sinh thêm chữ để tăng điểm. Không tối ưu prompt chỉ để chiều bộ chấm.

## 5. Phương hướng triển khai được đề xuất

### A. Tách nguồn sự thật khỏi đề xuất thiết kế

Giữ đúng site, footprint, cao độ và các dữ kiện có chứng cứ; không nâng office count,
dock count, palette, nhịp facade do code sinh thành yêu cầu bắt buộc. Mỗi trường cần
provenance `source / client-approved / design-proposal / inferred / unknown`.
Unknown không được tự động hardcode để “cho đủ thiết kế”.

### B. Cho AI phát triển thiết kế trước, không chỉ tô lại render

Reference thực sự hướng dẫn phân cấp kiến trúc, vật liệu và chất ảnh. Tạo vài đề xuất
trong envelope, duyệt một Design Master về kiến trúc/chương trình công năng trước khi
generate cả bộ. Không mặc định thiết kế tốt chỉ vì giống ảnh reference hoặc điểm VLM cao.
Nhóm R0 là thước đo khả năng thẩm mỹ; không dùng trực tiếp làm ảnh bàn giao của source B.

### C. Camera được chọn theo scene và câu chuyện ảnh

Sinh và so sánh candidate từ site/đặc trưng đã được duyệt: khả năng thấy chủ thể, che
khuất, mặt kiến trúc, sân hoạt động và ánh sáng. Mục đích ảnh là yêu cầu, azimuth/lens/
tọa độ không phải template cố định. Camera của shot được đăng ký **sau khi chọn**, không
hardcode một góc đẹp cho mọi nhà xưởng. AI tự chọn góc đẹp ở R0/R1 chưa đồng nghĩa góc
đó tồn tại hợp lệ trong scene thật.
AI/art director có thể xếp hạng contact sheet và đề xuất thêm góc để render kiểm tra;
không buộc chọn đúng một anchor hoặc lấy điểm analytic làm quyết định cuối cùng.

### D. Đừng coi thêm lệnh prompt là cơ chế bảo toàn hình học

Tách input geometry/camera khỏi kiến trúc tham khảo. Thử envelope-only không mang các
opening đề xuất; thêm bằng chứng mặt bằng/segmentation/depth có đăng ký thay vì chỉ bbox
bằng text. Với Gemini đây vẫn là image conditioning cần thực nghiệm, **không tự gọi là
ControlNet hay khóa depth cứng**. Nếu vẫn trôi camera/footprint, phải thử nhánh có cơ chế
điều khiển hình học khác hoặc phát triển/duyệt proxy thiết kế 3D; không lặp prompt vô hạn.

### E. Đánh giá theo thứ tự, không trộn thành một điểm tổng

1. Kiến trúc và realism: có tiềm năng đạt reference không?
2. Source fidelity: placement, silhouette, camera, các yêu cầu đã duyệt có giữ không?
3. Consistency: cùng một thiết kế giữa aerial, reverse, office và logistics không?
4. Human approval: chất ảnh/chi tiết đủ marketing chưa?

Chỉ export khi đủ bốn lớp. Tự do thiết kế và kiểm chứng dự án không phải hai mục tiêu
đối nghịch; điều cần bỏ là ràng buộc không có nguồn và thiết kế procedural bị áp thành luật.

### F. Điểm nối cụ thể trong repo cho increment tiếp theo

Đây là đề xuất triển khai, **chưa sửa production trong vòng thử nghiệm này**.

| Điểm nối | Việc cần thay đổi |
|---|---|
| `domain/render_intent.py` / Design DNA | Kit/rhythm và programme mặc định không được tự coi là client-approved; bổ sung provenance/approval theo trường |
| `application/refinement_prompt.py` | `design_within_envelope` hiện vẫn giữ vehicular openings trong base; contract mới chỉ khóa các trường có source/approval, reference được hướng dẫn kiến trúc thật |
| `scripts/blender/render_conditioning.py` | Thử thêm input envelope-only tách khỏi `envelope_program`, không xóa geometry/function thật có chứng cứ |
| `application/camera_candidates.py` / `plan_cameras.py` | Camera tìm theo scene và Design Master đã duyệt; kiểm tra visibility/framing bằng preview, không chỉ điểm analytic |
| `application/verify_views.py` | Programme QA từ contract được duyệt; phân biệt unknown với fail và broad viewpoint với registered camera; không gọi verdict VLM là phép đo |
| ViewSet workflow | Một master/lineage cho các góc; giữ approval/export gate, không chọn ảnh đẹp từ các thiết kế độc lập |

Không nới toàn bộ pack strict/tender để chữa marketing. Luồng thiết kế marketing và luồng
tái hiện hồ sơ phải có intent/authority riêng; lựa chọn rõ của khách hàng vẫn là ràng buộc hợp lệ.

## 6. Thử nghiệm kế tiếp, chưa tự gọi thêm ảnh

- Conditioning factorial trên cùng aerial/camera: base hiện tại so với envelope-only
  không chứa facade/openings đề xuất; reference board so với các panel kiến trúc không
  mang caption/branding. 2 × 2 × 3 = 12 ảnh tối đa, cùng brief/model để tách nguyên nhân.
- Ground-truth camera QA: giữ camera, đổi azimuth, đổi focal length và dịch footprint có
  chủ ý. Đo false pass/false alarm trước khi tin judge. Không chỉ kiểm đếm khối.
- Với phương án vượt quality + source fidelity, mới thử một Design Master chung cho
  aerial/reverse/office/logistics. Mỗi mặt công năng phải được duyệt, không suy chi tiết
  khuất từ một hero image. Sau đó kiểm chứng trên thêm site/LOD khác.
- Không triển khai editing/inpainting để che lỗi nền tảng trong vòng này.

Exit hiện tại: xác nhận được khả năng thẩm mỹ và rủi ro của các mức khóa; **chưa đạt exit
marketing delivery, chưa chứng minh phương án giữ hình học/camera ổn định**.

## 7. Nguồn kỹ thuật và tái chạy

Google mô tả image generation với reference images và cấu hình aspect/size; đây không
phải bằng chứng đảm bảo camera/footprint theo phép đo. Suy luận cần kiểm chứng bằng
thử nghiệm là “reference có thể nâng chất thiết kế nhưng không thay thế nguồn geometry”.
[Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation).

Nghiên cứu kiến trúc multi-view dùng shoebox, ControlNet, loss cho style/structure/angle
và depth-aware 3D attention để xử lý consistency. Đây là bằng chứng rằng bài toán cần
liên kết cấu trúc giữa các view; không chứng minh chỉ truyền nhiều reference cho Gemini
là đủ. Cũng không mặc định phải triển khai framework nghiên cứu này ngay trong repo.
[Multi-View Depth Consistent Image Generation, CAADRIA 2025](https://arxiv.org/abs/2503.03068).

Các provider khác có multi-reference editing cũng chỉ là ứng viên benchmark, chưa phải
giải pháp đã thắng trong repo này. Không đề xuất đổi provider chỉ từ quảng cáo khả năng.
[BFL multi-reference guide](https://docs.bfl.ml/guides/prompting_editing_multi_reference).

```powershell
.venv\Scripts\python.exe scripts/run_reference_freedom_experiment.py resource/research/reference_freedom_v1.json
# Chỉ prepare; muốn gọi API phải thêm --execute. Cap 24, không tự retry lỗi/uncertain.
.venv\Scripts\python.exe scripts/review_reference_freedom_experiment.py resource/research/reference_freedom_v1.json
# Chỉ tạo bảng/CSV review; --execute cho phép tối đa 42 lần chấm, dùng cache đã hoàn thành.
.venv\Scripts\python.exe -m pytest -q
```

241 test qua; Ruff cho hai script và test mới qua. Không sửa các thay đổi production
có sẵn trong vòng nghiên cứu này. CSV human review để trống, chờ người chấm thật.
