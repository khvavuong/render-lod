# V365 — Đánh giá hiện trạng và kế hoạch đưa thử nghiệm vào luồng chính

Ngày: 2026-09-18. Trạng thái: kế hoạch trước triển khai; chưa sửa pipeline production.
Phạm vi: marketing/reference-led design. Không thay hành vi strict/tender, không triển khai editing.

## 1. Quyết định đề xuất

**Đưa reference-led design vào luồng chính theo pilot có version, không chỉ đổi style pack.**
Ưu tiên tái hiện chất lượng proposal đã được người dùng đánh giá tích cực trước; tiếp đó
mới hoàn thiện camera, tính nhất quán và các điều kiện bàn giao. Không chờ một giải pháp
geometry tuyệt đối mới cho người dùng thử chất lượng mới, cũng không gọi proposal là ảnh
đúng hồ sơ hoặc tự động marketing-ready.

Luồng đích:

`Source + brief + references → đề xuất kiến trúc → chọn/duyệt master family → chọn shot theo scene → generate các góc cùng thiết kế → review → bàn giao`

Source facts và client-approved requirements xuyên suốt các bước. Programme/kit do code
sinh không mặc nhiên trở thành source fact. Mục đích ảnh được giữ, không giữ một bộ tọa độ
camera, motif hoặc palette cố định cho mọi dự án.

## 2. Bằng chứng và giới hạn

Nguồn: [báo cáo 24 ảnh](V365_REFERENCE_FREEDOM_EXPERIMENT_RESULTS.md),
[config thử nghiệm](research/reference_freedom_v1.json).

- 24/24 ảnh generate thành công; bốn mức authority, hai mục đích ảnh, ba lần lặp mỗi ô.
- Người dùng đánh giá trực tiếp ảnh thử nghiệm rất tốt/có triển vọng. Đây là tín hiệu
  ưu tiên sản phẩm, chưa phải duyệt toàn bộ set hay yêu cầu công năng mới.
- VLM advisory: office R1 design/realism 5.00/5.00; R3 3.33/3.33, mỗi nhóm n=3.
  R2 office có hai mẫu có điểm, một lượt chấm unavailable. Aerial R2/R3 hòa design và
  realism trung bình; không kết luận mọi khóa programme đều làm chất lượng giảm.
- Source text có ca đổi quan hệ hai shed; registered camera bằng prompt chưa ổn định.
  Office/aerial hiện được generate độc lập, chưa chứng minh multi-view consistency.
- Judge có ca suy sai số lượng campus từ ảnh office cục bộ. Không tối ưu sản phẩm chỉ
  để tăng điểm judge hoặc biến unknown thành fail/pass tự động.
- Một site, không có seed kiểm soát; brief/palette/reference của vòng này khác các vòng
  cũ. Không quy toàn bộ cải thiện riêng cho reference hoặc một câu prompt.

## 3. Hiện trạng repo đã kiểm tra

Worktree sạch trước lượt đánh giá này. Đã chạy lại backend: **241 test qua**, có hai
deprecation warning từ Starlette/httpx, không có test thất bại. Đây là bằng chứng hồi quy
phần mềm, không phải chứng nhận chất ảnh. Chưa gọi thêm API trả phí trong lượt này.

### Nền tảng nên giữ

- Job/style snapshot, reference hash và output namespace đã có.
- Site Master → Facade Master đã tạo thành một identity chain, không phải hai generation
  hoàn toàn độc lập; có duyệt master và human review cuối set.
- Có conditioning preflight, manifest/correspondence, protection và validation.
- Đã có reference upload cho factory/context, quality baseline, chất lượng facade chuẩn.
- Đã có targeted repair trong workflow hiện tại. Giữ tương thích nhưng **không mở rộng
  repair/editing trong increment này** và không dùng repair để che lỗi thiết kế nền tảng.

### Các khoảng cách cụ thể so với thử nghiệm

| Thành phần | Hành vi hiện tại đọc từ code | Tác động / việc cần làm |
|---|---|---|
| `application/refinement_prompt.py` | `design_within_envelope` vẫn khóa frame và vehicular openings trong base; reference chỉ được hướng dẫn vocabulary/finish | Marketing cần contract theo trường có provenance, không khóa mọi opening đề xuất |
| `providers/gemini.py::_photoreal_balanced_input` | Base, structure guide, aerial semantic authority; reference bị cấm ảnh hưởng palette/facade motif, chủ yếu construction/finish | Thử nghiệm cho reference hướng dẫn kiến trúc thật; cần builder mới độc lập, không kế thừa lệnh cũ |
| `providers/gemini.py` | Balanced chỉ lấy `reference_images[:2]`; role đọc từ metadata/path | Input typed theo role và stage, không silent truncate hoặc suy role từ tên file |
| `application/run_generation_job.py` | Site Master nhận context reference; Facade Master nhận factory reference | Site Master chưa nhận đủ tín hiệu kiến trúc của thử nghiệm; cả hai cần architecture/material bundle thích hợp |
| `application/refine_viewset.py` | Shared identity vẫn giữ functional doors/site circulation; có thể thay reference thứ hai bằng context composition guide | Authority/reference được quyết định một lần rồi truyền xuyên tầng, tránh lệnh khóa và mất ref trở lại |
| `run_generation_job.py::_ensure_conditioning` | Freedom design dùng `envelope_program`, còn programme đề xuất trong render | Cần experimental envelope-only; vẫn giữ chức năng/source geometry thật có bằng chứng |
| `api.py::create_view_set` | Gọi `PlanStandardCameras` trước generation; camera search script chưa là orchestration của endpoint này | Không gọi camera planner hiện tại là góc hardcode hoàn toàn: đã có tính theo scene, nhưng còn thiếu candidate preview/ranking/reselection trong main flow |
| `api.py::_with_active_quality_baseline` | Tự bù role thiếu, không ghi đè role người dùng gửi | Giữ ưu tiên user input; hiển thị nguồn baseline được bù, snapshot/hash toàn bộ input đã resolve |
| Validation/certification | Có input preflight, integrity, edge/semantic/material/context screens và human review | Phân biệt input camera hợp lệ với output giữ camera; facade mới không được bị loại chỉ vì khác edge/material proposal cũ |

Không coi mọi pass/certification hiện có là phép đo chính xác hình học ảnh AI. Cần audit
ý nghĩa trạng thái/API/UI trước khi bật chế độ mới, tránh giữ nhãn chứng nhận cũ cho proposal.

## 4. Kiến trúc tích hợp

### 4.1 Policy có version, gắn với job

Thêm policy cho marketing reference-led, rollout flag chỉ quyết định **job mới**. Job cũ
và job resume giữ policy snapshot/version ban đầu; không đổi behavior theo environment
flag lúc resume. Strict/tender giữ builder/render/QA hiện tại.

Các stage nội bộ, không yêu cầu người dùng chọn giữa bốn arm thử nghiệm:

- `design_proposal`: gần R1 — brief + architecture/material refs + source envelope,
  camera/design được phát triển tự do; hiển thị đề xuất và vấn đề fidelity còn chưa rõ.
- `registered_view`: gần R2 nhưng dùng requirements đã duyệt, geometry evidence tối thiểu
  và camera của shot đã chọn. Không tái áp programme R3 chưa được duyệt.
- `reviewed_delivery`: master family/shot/output có review và lineage hợp lệ; không phải
  tên gọi của một model hay bảo đảm API rằng geometry đã chính xác.

R0 dùng làm control thẩm mỹ hoặc exploration được ghi rõ là concept; không mặc định dùng
làm master của source project. R3 chỉ phù hợp cho yêu cầu công năng thực sự đã được duyệt.

### 4.2 Authority theo trường

Contract gồm `value`, `provenance`, `evidence_ref`, `approval_ref`, `scope` cho mỗi yêu cầu:
footprint/height/placement, roofs, entrances/docks, roads/site, material identity.

- `source`: dữ kiện đo/đọc được; phân biệt measured bbox với semantic interpretation.
- `client_approved`: lựa chọn đã duyệt rõ, có revision.
- `design_proposal`: code/AI đề xuất, có thể thay đổi trước khi duyệt.
- `inferred`: giả định có lý do; không nâng thành source requirement.
- `unknown`: không bịa thêm default để làm hợp lệ contract.

Không thay count cửa/office bằng một constant khác. Kit/rhythm/palette vẫn có thể là lựa
chọn rõ của khách hàng, nhưng default của code không tương đương client approval.

### 4.3 Một input specification, không nhiều lớp prompt xung đột

Tách pure builder từ cơ chế thử nghiệm vào application/provider contract; không import
script research vào runtime. Builder nhận stage, brief, source facts, approved design,
shot và reference bundle; trả các block có role/instruction rõ.

Không nối thêm `geometry_contract`/legacy identity prompt rồi vô tình khóa facade trở lại.
Mọi input block có version/hash; manifest ghi input nào thực sự đã gửi, không chỉ file
conditioning được tạo. Depth/semantic/structure guide có trong thư mục không có nghĩa
provider đã dùng chúng hoặc coi chúng là khóa cứng.

Reference architecture được ảnh hưởng hierarchy, canopy/glazing, detailing/material
family theo brief; không sao chép exact campus/camera. Reference construction/material
được ảnh hưởng scale/realism. Context guide là spatial evidence riêng, không chiếm mất
slot architectural reference. Giữ cả hai reference thẩm mỹ của thử nghiệm trong pilot.
API/UI hiện chỉ có role factory/context. P0 cần chốt mở rộng role construction/material
hoặc mapping tương thích rõ trong bundle; không tự relabel reference cảnh quan người dùng
thành reference kiến trúc. File upload cũ vẫn đọc được, optional role mới có validation.

Không hardcode navy/white của vòng thử nghiệm vào mọi job. User brief/approved identity
có ưu tiên rõ; nếu palette user và reference khác, resolve/hiển thị thay vì gửi lệnh mâu thuẫn.
Không tự sinh ảnh crop/reference đã chỉnh trong increment đầu; factorial panel/board là
nghiên cứu riêng, không lén thay input đang được người dùng đánh giá tốt.

### 4.4 Master family và camera

Tận dụng Site → Facade chain hiện có; thêm common `master_family_id`, approved contract,
parent hashes và compatibility review. Không yêu cầu mọi góc có cùng image hash: Site và
Facade Master là hai ảnh khác nhưng phải thuộc một thiết kế đã duyệt. Facade Master không
được bổ sung công năng làm Site Master lỗi thời mà không yêu cầu duyệt lại.
Site Master vừa generate nhưng chưa được người dùng duyệt là draft anchor, không gọi là
approved design chỉ vì được truyền vào Facade Master; approval state và label phải đúng stage.

Một hero image không quyết định hết các mặt khuất. Thiếu bằng chứng cho mặt logistics/
reverse thì cần proposal/review bổ sung có budget, không suy topology toàn bộ từ một ảnh.

Camera search theo scene/thiết kế đã duyệt: sinh candidates thích ứng, render contact
sheet, kiểm visibility/collision/framing, xếp hạng và cho người dùng chọn/đề xuất góc mới.
AI có thể đề xuất góc nhưng phải render kiểm tra trước registered stage. Role là câu chuyện
ảnh, không phải tọa độ/lens cố định. Các preset/analytic score chỉ là soft prior.

Nếu proposal AI chọn góc khác render ban đầu, không mặc định đó là thiết kế xấu; chọn lại
shot hợp lệ trong scene nếu có thể. Không tự công nhận ảnh AI đã đăng ký camera chỉ vì
judge nói same. Nếu không thể đưa thiết kế về source footprint/camera, giữ concept hoặc
mở nhánh proxy 3D/geometry-conditioned khác, không retry prompt không giới hạn.

## 5. Kế hoạch triển khai theo dependency

| Mốc | Công việc | Exit / bằng chứng |
|---|---|---|
| P0 — Chốt contract/input | Audit resolved inputs, stage authority, enum/schema version; lưu golden fixtures request từ trial và main | Có bảng diff đầy đủ, không còn reference/requirement mất ngầm; job cũ resume không thay đổi |
| P1 — Main-flow proposal pilot | Builder reference-led, typed refs, versioned policy; Site Master nhận architecture/material; UI hiển thị proposal và selection/review | Proposal tạo qua API/job/UI, không chạy research script thủ công; payload parity và human review cho chất lượng tương đương trial |
| P2 — Duyệt một thiết kế | Authority provenance, master family và approved programme/materials; reapproval khi thay đổi | Site/Facade cùng identity, requirements không lấy từ code default; chọn master thực tế rồi mới generate tiếp |
| P3 — Shot/conditioning | Nối candidate search/preview vào main; envelope-only experimental; registered evidence theo scope | Có góc đẹp theo site và input hợp lệ; fidelity review độc lập; không pretend image conditioning là hard depth control |
| P4 — Set và QA | Generate các góc từ approved family; QA stage-aware, unknown/review, partial views; audit certification/UI/export | Một set sáu góc được duyệt kiến trúc, realism, source requirements và consistency; không ghép winner khác thiết kế |
| P5 — Rollout | Kiểm thêm site/LOD khác, so legacy/pilot, telemetry và rollback | Chỉ đặt default marketing sau khi đạt gates; strict/tender không đổi, không đổi policy của job đang chạy |

**Thứ tự ưu tiên P0 → P1 trước.** P1 cho người dùng kiểm chất lượng ngay trong luồng chính;
không chờ P3/P4 mới có proposal. Programme provenance đầy đủ/P2 là điều kiện trước khi
khóa design và sinh bộ ảnh, không để P1 silently mặc định đã duyệt toàn bộ yêu cầu.

## 6. Kiểm chứng và ngân sách dự kiến

### Offline trước khi gọi API

- Golden normalized block fixtures: pure builder mới tái hiện trial input R1/R2 tương ứng,
  bỏ qua transport/request ID, không bỏ qua role/order/instruction/content hash.
- Assert proposal không có legacy fixed-camera/facade/programme locks không có source;
  registered view chỉ khóa requirements/shot đúng scope.
- Test reference không mất khi attach context guide; roles explicit, baseline chỉ bù thiếu;
  explicit refs/brief thắng default, conflict được báo.
- Idempotency/job/cache key gồm policy/builder version, resolved ref role/content/instruction,
  source contract, master family/revision, shot. Đổi input không dùng lại output/approval cũ.
- Resume/approve/reject/cancel/budget/in-flight, stale hash và malformed judge response.
- QA partial-office không suy campus count; facade mới không yêu cầu khớp mọi edge của
  facade proposal cũ; input-camera preflight không đồng nghĩa output-camera pass.
- Strict/tender regression, API/frontend integration và production build.

### Pilot có người duyệt, không chạy tự động trong lượt lập kế hoạch

1. Tối đa **12 ảnh mới** trên site B: legacy/main mới × aerial/office × ba lần lặp.
   Cùng model, quality request, refs/brief/palette đã resolve. Không claim equal geometry
   conditioning nếu hai stage có input khác; đánh giá aesthetic và source fidelity riêng.
   Golden parity là kiểm byte/spec offline, không hứa model không seed sẽ tạo cùng ảnh.
2. Chọn một thiết kế đạt review để chạy set. Ngân sách riêng dự kiến tối đa **12 lần
   generate**, gồm proposals/master và remaining views; persist số đã dùng, không phải
   thêm 12 lần sau mỗi lần reject. Dừng xin quyết định nếu không đạt trong cap.
3. Trước default, kiểm trên ít nhất một site/LOD khác với ngân sách riêng được chốt.
   VLM review calls có cap riêng; không giấu chúng trong ngân sách image generation.

Ngưỡng chất lượng: dùng bảng trial làm baseline thị giác và review của người dùng/
người duyệt thứ hai; VLM chỉ shortlist/advisory. Điểm ≥4 không tự export. Ngưỡng geometry
phải theo scope/evidence và calibration, không bịa một tỷ lệ pixel duy nhất cho mọi LOD.

Marketing proposal có thể cho xem/tải bản ghi rõ “đề xuất thiết kế, chưa xác nhận theo hồ sơ”.
Bản bàn giao theo dự án chỉ mở khi các điều kiện review/requirements/lineage tương ứng đạt;
không đánh tráo human visual approval thành chứng nhận kích thước 3D chính xác.

## 7. Rollout, rủi ro và điều kiện dừng

- Pilot opt-in trước, quan sát payload version, input refs thực tế, stage/approval lineage,
  số gọi/cost/latency, tỷ lệ reject theo nguyên nhân. Không auto-regenerate khi quality thấp.
- Rollback chỉ đổi policy cho job mới; không xóa artifacts/master đã duyệt, không resume
  job reference-led bằng legacy builder giữa chừng.
- Nếu P1 đẹp nhưng trôi layout: vẫn giữ proposal pilot, chưa bật default delivery; xử lý
  P3 geometry/shot. Không chữa bằng cách thêm lại toàn bộ R3 locks.
- Nếu cùng master nhưng các góc đổi thiết kế: dừng set, bổ sung evidence cho mặt thiếu;
  không lẫn các master độc lập hoặc dùng editing để che mâu thuẫn.
- Nếu QA loại thiết kế hợp lệ hoặc cho pass ảnh sai: giữ review/unknown, hiệu chỉnh bằng
  ground-truth camera/layout cases; không tùy tiện hạ threshold để tăng tỷ lệ pass.
- Branding/signage từ reference và bối cảnh tự tưởng tượng là rủi ro riêng. Không chấp
  nhận sai brand/site chỉ vì chất ảnh đẹp; xử lý trong input/review trước editing.

## 8. Phạm vi bàn giao increment đầu

Một job marketing mới có thể nhận refs/brief, tạo proposal chất lượng theo hướng trial,
cho xem/chọn/duyệt master trong UI và lưu đầy đủ policy/input/lineage. Các nhãn concept/
reviewed output không gây hiểu nhầm; job cũ và tender chạy nguyên hành vi. Có tests,
manifest diff và bộ ảnh pilot để người dùng đánh giá. **Chưa cam kết sáu ảnh bàn giao từ
increment P1; đó là exit P4, không phải lợi ích được suy từ 24 ảnh độc lập.**

Tài liệu này thay việc áp dụng nguyên xi arm thử nghiệm bằng một kế hoạch stage-aware;
[research plan](V365_RENDER_QUALITY_RESEARCH_PLAN.md) và báo cáo trial vẫn giữ vai trò
nguồn bằng chứng, không phải cấu hình mặc định production.

## 9. Trạng thái triển khai 18/09/2026

Đã tích hợp increment P0/P1 opt-in và chạy hai ảnh thật qua worker chính.
P2–P5 chưa hoàn tất; chưa bật marketing delivery mặc định.
Chi tiết, ảnh pilot, kiểm chứng và giới hạn ở
[Implementation status](V365_REFERENCE_LED_IMPLEMENTATION_STATUS.md).

Tiếp nối: đã bổ sung đăng ký design, camera search/source-only previews, sáu ảnh và
human review gates. Pilot chạy đủ sáu ảnh nhưng chưa đạt camera/identity để bàn giao;
không bật default hoặc tuyên bố hoàn tất P4/P5. Xem
[Registered pilot output review](V365_REGISTERED_PILOT_OUTPUT_REVIEW.md).
