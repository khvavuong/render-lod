# V365 — Kế hoạch nghiên cứu và cải thiện chất lượng ảnh nhà xưởng

**Phiên bản:** 2.0 — đánh giá lại dựa trên code và tài liệu kỹ thuật gốc  
**Ngày nghiên cứu:** 2026-09-17  
**Trạng thái:** Kế hoạch nghiên cứu; chưa chứng minh phương án thắng bằng thí nghiệm mới  
**Phạm vi:** Camera, tự do thiết kế từ LOD100, photorealism, consistency và đánh giá chất lượng  
**Image editing tương tác:** Hoãn đến khi generation ổn định

## 1. Kết quả đánh giá kế hoạch phiên bản trước

Kế hoạch trước đúng ở việc tìm camera theo từng site, có preview, dùng scene chung và kiểm tra nhiều lớp. Tuy nhiên, nó chưa đủ chính xác để dùng trực tiếp làm thứ tự triển khai. Điểm thiếu quan trọng nhất là chưa xử lý yêu cầu “không khống chế model quá mức”: vẫn có xu hướng xem facade, cửa và chi tiết do pipeline tự tạo là thiết kế đã duyệt.

Cần thay đổi từ một chuỗi triển khai cố định sang một chương trình kiểm nghiệm có các quyết định dựa trên kết quả.

| Nội dung của bản trước | Đánh giá lại | Điều chỉnh |
|---|---|---|
| Giữ nguyên mọi facade/opening trong Base RGB | Quá chặt nếu đó là chi tiết pipeline tự đề xuất cho LOD100 | Phân biệt dữ liệu nguồn, đề xuất chưa duyệt và thiết kế đã duyệt |
| Nâng PBR rồi mới benchmark AI | Chưa có bằng chứng đây là thứ tự tối ưu | So sánh input tối giản, input hiện tại và PBR tăng cường quy mô nhỏ |
| Một Design Master làm identity anchor | Có ích nhưng không nhìn thấy hết site/facade và không bảo đảm consistency | Tận dụng cơ chế hai master hiện có, kiểm nghiệm chọn reference theo overlap |
| Bốn model hiện có làm development set | Hai model được báo cáo có phương án chồng lấn, chưa đủ điều kiện | Khởi đầu bằng hai model hợp lệ; sửa dữ liệu hoặc bổ sung model khác |
| Beauty pass có mask/control | Nhiều provider/adapter không thực thi giới hạn pixel như kế hoạch giả định | Phân biệt natural-language instruction, spatial conditioning và bảo vệ pixel |
| Camera pass là đủ để bắt đầu paid generation | Coverage gate chỉ loại lỗi lớn | Thêm ranking thị giác và duyệt shortlist |
| Sáu camera phải khác nhau | Khác tọa độ chưa chắc khác nội dung | Chọn cả bộ theo coverage của surface/semantic và độ đa dạng |
| Chỉ tạo lại khi candidate đầu fail | Tiết kiệm nhưng không đo được độ ổn định của model sinh ảnh | Screening ít lượt; kiểm nghiệm lại các cấu hình đứng đầu với nhiều lần chạy |

Đề xuất phù hợp nhất hiện tại: **tìm camera từ hình học thực tế; cho phép thiết kế facade trong phạm vi đã xác định; giữ dữ liệu site có chứng cứ; dùng master để hỗ trợ nhận diện; xác nhận chất lượng bằng benchmark mù.**

Đây là phương án ưu tiên để kiểm nghiệm, chưa phải kết luận rằng một provider hoặc một mức PBR đã tối ưu.

## 2. Phạm vi bằng chứng và giới hạn đánh giá

Đánh giá này dựa trên code trong checkout, tests liên quan, báo cáo thí nghiệm nội bộ và các nguồn sơ cấp ở mục 16.

Không tìm thấy ảnh benchmark lịch sử trong kiểm tra file ảnh ở thư mục `.artifacts` của checkout hiện tại. Vì vậy, các nhận xét thị giác và số liệu lịch sử được dẫn từ báo cáo nội bộ, chưa được tái chấm hoặc tái lập trong lần nghiên cứu này. Không suy ra rằng chất lượng hiện tại giống hệt chất lượng ở các báo cáo cũ.

Các unit test đã pass trong phiên đánh giá trước chứng minh một số công thức và contract hoạt động theo test; chúng không chứng minh camera đẹp, ảnh giống chụp thật hoặc provider giữ đúng hình học.

Không thực hiện generation trả phí, chỉnh pipeline, đổi renderer hoặc xây image editing trong lần cập nhật tài liệu này.

## 3. Hiện trạng repository và phần cần tận dụng

| Thành phần | Bằng chứng trong code | Ý nghĩa cho kế hoạch |
|---|---|---|
| Analytic framing | `application/camera_framing.py`, `application/plan_cameras.py` | Tận dụng làm điểm khởi tạo; không xây solver framing mới từ đầu |
| Photography pack | `domain/photography_pack.py`, `resource/photography_packs/` | Đã tách intent khỏi kích thước model; cần hỗ trợ khoảng lựa chọn thay vì chỉ một bộ thông số |
| Standard camera planner | `plan_cameras.py`, standard-v39 | Vẫn tạo bộ sáu camera bằng nhiều heuristic; chưa có tìm kiếm và đánh giá ảnh candidate đầy đủ |
| Camera preflight | `application/validate_conditioning.py` | Đã có semantic coverage gate; code mô tả ngưỡng cố ý rộng để loại lỗi lớn |
| Camera lock bằng landmark | `application/camera_lock.py` | Đã có projection và verdict; chưa thấy nối vào workflow và chưa có bộ định vị landmark trong ảnh AI |
| Design freedom | `domain/style_pack.py`, `application/refinement_prompt.py` | Đã có photoreal_only, detail_within_envelope, design_within_envelope |
| User intent | `domain/render_intent.py`, `application/compile_user_intent.py` | CreativeBudget và DesignFreedom là hai trục khác nhau; cần kiểm tra đường truyền intent thực tế |
| Master workflow | `refine_viewset.select_master_view_ids`, `run_generation_job.py` | Đã chọn site master và facade master; facade master nhận site master làm reference |
| PBR foundation | `assets/pbr-v1/asset_library_manifest.json`, `scripts/blender/render_conditioning.py` | Đã có texture sân/đường, HDRI và procedural materials; không lập lại việc “bổ sung PBR cơ bản” như chưa có gì |
| Correspondence index | `application/build_correspondence.py` | Có shared object visibility; chưa tương đương dense pixel/surface reprojection |
| Gemini adapter | `providers/gemini.py` | Khai báo multi-reference; các capability mask/control-scale/seed/multi-turn vẫn mặc định false |
| Structure challenger | `providers/stability.py` | Đã có adapter control image, control strength và seed; không có master-based multi-reference trong adapter này |
| Provider thay thế | `providers/openai_image.py` | Đã tích hợp và khai báo masked edit/multi-reference; capability khai báo không chứng minh workflow generation đang dùng mask |
| Geometry protection | `application/protect_refinement.py` | Có pixel restore và validation-only; job hiện gọi restore_locked_pixels=false |
| Certification | `create_certification_report.py`, `validate_viewset.py` | Có trạng thái review/certified và evidence thiếu; cần kiểm tra toàn đường publish/approval, không mặc định QA chưa tồn tại |
| Renderer runtime | `Dockerfile.renderer` | Cài Blender từ apt trên Ubuntu 24.04, chưa pin phiên bản exact; benchmark phải ghi runtime thật |

Báo cáo camera nội bộ ghi nhận 6/6 conditioning pass trên hai model khác tỷ lệ. Đây là bằng chứng framing đã tiến bộ, không phải bằng chứng đã tìm được góc tốt nhất. Cũng không nên lấy mốc công việc trong tài liệu cũ làm trạng thái code hiện tại: ví dụ module landmark camera lock nay đã tồn tại.

### 3.1. Các điểm cần audit trước khi thử nghiệm

Các điểm dưới đây được xác định từ code, chưa phải kết luận mọi request đều mắc cùng lỗi:

- `marketing_photoreal.json` không khai báo `design_freedom`, nên dùng default `photoreal_only`. Cần kiểm tra profile thực tế có chọn pack này không.
- Job có đường gọi `build_refinement_prompt(paths.design_dna)` không truyền StylePack. Hàm sử dụng prompt mặc định và freedom nghiêm ngặt; phải kiểm tra UI → job → prompt → provider có thật sự truyền ý đồ tự do thiết kế.
- Prompt có câu coi facade kit do Base RGB thể hiện là immutable/approved. Cần phân biệt phần nào do model nguồn, phần nào do procedural planner.
- Khi thiết kế trong envelope được cho phép, structure guide và adapter vẫn có chỉ thị giữ bay boundary, palette/material region hoặc opening proposal. Chúng có thể thu hẹp lại tự do vừa mở ở prompt.
- Prompt project contract nói context proxies được restored later, trong khi StylePack có nhiều ContextPolicy khác nhau. Job hiện cũng có đường composite_context_proxy=true. Cần xác định policy nào thực sự áp dụng ở từng entrypoint.
- Gemini adapter còn gắn aerial directives với view-01/view-04 và golden-hour exception với VIEW-06. Điều này ảnh hưởng mục tiêu camera theo role.
- Intent compiler chứa các giá trị roof slope 7°, eave 0,75 m, grouping gap 10 m, panel module 1,2 m. Đây là design defaults, không mặc nhiên là geometry đã có trong nguồn LOD.
- `CreativeBudget` không tự động đồng nghĩa với `DesignFreedom`; không nên giả định đổi control trên UI đã đổi contract của provider.

Deliverable nghiên cứu đầu tiên phải là một bảng authority có nguồn gốc và một bản request thực tế đã loại dữ liệu nhạy cảm, đủ để xem model đang bị ràng buộc ở đâu.

## 4. Kết quả nghiên cứu kỹ thuật và cách áp dụng

### 4.1. Camera đẹp cần kết hợp hình học và tín hiệu từ ảnh

Nghiên cứu về chụp kiến trúc cho thấy việc kết hợp đặc trưng 2D và 3D có thể đánh giá viewpoint tốt hơn khi chỉ dùng một loại. Vì vậy coverage hoặc projected bounding box là điều kiện cần, chưa đủ để chấm composition. [Viewpoint Selection for Photographing Architectures](https://arxiv.org/abs/1703.01702)

Áp dụng cho V365: dùng hình học để lọc camera không khả thi; dùng preview để đo visibility, nền, chiều sâu và bố cục; dùng reviewer để hiệu chỉnh ranking. Không giả định entropy lớn hoặc nhiều cạnh là đẹp: mái và facade lặp của nhà xưởng có thể làm các chỉ số này cao mà ảnh vẫn nghèo ý đồ. Nhận xét áp dụng này là suy luận cho bài toán của repo.

### 4.2. Spatial control không phải bảo đảm hình học tuyệt đối

ControlNet bổ sung conditioning bằng edge, depth, segmentation và các tín hiệu không gian. Đây là cơ sở để nghiên cứu provider có control thực sự, nhưng không phải chứng minh mọi pixel hay topology luôn được giữ. [ControlNet, ICCV 2023](https://arxiv.org/abs/2302.05543)

Áp dụng: benchmark đường cong chất lượng theo mức control; không mặc định control mạnh nhất là tốt nhất. Mask ghi ra đĩa hoặc nhãn “structure authority” trong prompt chưa tương đương provider sử dụng mask/control đã được huấn luyện.

### 4.3. Master/reference hỗ trợ identity nhưng không giải quyết hình học đa view

Google hướng dẫn image input, conversational iteration và multi-reference. Các chức năng đó là công cụ điều kiện hóa generation, không phải contract giữ camera hoặc correspondence 3D. Adapter Gemini của repo hiện cũng chưa khai báo multi-turn state. [Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation)

Áp dụng: tiếp tục thử master của chính project; chọn reference có surface overlap; kiểm tra từng view và cả set. Không dùng “model có consistency” như bằng chứng set đã consistent.

### 4.4. Multi-view diffusion chuyên dụng có cơ chế khác với sequential API calls

MVDiffusion dùng correspondence-aware attention và sinh các view với tương tác giữa nhánh. Phần depth-to-image được nghiên cứu trên ScanNet indoor; không thể suy ra kết quả cho site nhà xưởng ngoài trời quy mô lớn. [MVDiffusion — paper và phần thí nghiệm](https://arxiv.org/html/2307.01097v7)

Áp dụng: học nguyên tắc correspondence và tránh chuỗi phụ thuộc ảnh trước tích lũy lỗi; không đưa việc train/custom multi-view diffusion vào critical path trước khi thử pipeline hiện có.

### 4.5. Texture-space phù hợp với texture, không tự thiết kế kiến trúc

GenesisTex sinh texture cho geometry có sẵn, dùng style consistency và dynamic alignment. Paper nêu hạn chế bộ nhớ do cross-view attention và cần refinement bổ sung. [GenesisTex — conclusion and limitations](https://arxiv.org/html/2403.17782v1#S5)

Áp dụng: xem đây là hướng R&D khi vật liệu cần nhất quán; không dùng nó như lời giải cho canopy, cửa sổ hoặc articulation mới chưa có geometry.

### 4.6. Color management và render pass hỗ trợ tính đúng của input

Blender mô tả AgX xử lý dải sáng và giảm saturation ở exposure cao. Điều đó giúp image science, nhưng không biến asset proxy thành ảnh thật. [Blender 4.5 — color management](https://docs.blender.org/manual/es/4.5/render/color_management.html)

Render passes cung cấp dữ liệu trung gian phục vụ phân tích và mask. Cần kiểm tra engine/version thật vì không thể mặc định mọi pass đều sẵn có trong mọi profile. [Blender — render passes](https://docs.blender.org/manual/en/latest/render/layers/passes.html)

Áp dụng: lưu engine, version, transform, exposure và đơn vị; dùng đúng data pass cho QA, tách khỏi ảnh beauty đã tone-map.

## 5. Authority phù hợp với LOD100 và yêu cầu tự do thiết kế

Không khóa toàn bộ Base RGB như một thiết kế hoàn thiện. Mỗi object/surface cần có provenance, trạng thái duyệt và mức độ chắc chắn.

| Nhóm dữ liệu | Cách xử lý trước duyệt | Cách xử lý sau duyệt |
|---|---|---|
| Footprint, vị trí, số khối, height envelope có trong model nguồn | Giữ theo chứng cứ nguồn; báo lỗi nếu dữ liệu mâu thuẫn | Giữ |
| Roof topology hoặc openings thật có trong model | Giữ nếu đã được xác nhận | Giữ |
| Road, gate opening, circulation, landscape boundary có chứng cứ | Giữ boundary; appearance được hoàn thiện | Giữ layout, cho thay finish hợp lý |
| Facade bay, stripe, glazing, canopy do pipeline tự đề xuất | Có thể thiết kế lại trong envelope và brief | Giữ ngôn ngữ/tỷ lệ/vị trí đã được duyệt |
| Mái do rule mặc định suy ra từ massing phẳng | Ghi rõ là đề xuất; có thể xét biến thể trong height envelope | Khóa phương án được duyệt |
| Fence/gate chưa có trong source | Không yêu cầu “preserve” thứ không tồn tại; nếu cần thì đề xuất layout dùng chung | Giữ layout và opening đã duyệt |
| Context authored | Giữ vị trí/scale, appearance theo policy | Giữ policy nhất quán |
| Context generated/conceptual | Cho hoàn thiện có giới hạn; ghi là conceptual | Dùng chung layout khi xuất nhiều góc |
| Camera | Tự do tìm kiếm và refine trong giai đoạn chọn góc | Giữ camera đã chọn trong từng request generation |

Khóa camera sau duyệt là cần để kiểm tra fidelity. Nó không có nghĩa góc camera bị hardcode từ đầu.

Ba mức freedom có sẵn được dùng làm trục thử nghiệm:

- `photoreal_only`: đối chứng để đo tác động của khóa chặt.
- `detail_within_envelope`: hoàn thiện kiến trúc nhưng giữ các opening/roof có authority.
- `design_within_envelope`: thử nghiệm ưu tiên cho massing chưa thiết kế; cho phép thay facade proposal, kiểm tra không vượt envelope và không phá layout vận hành.

Không cho phép freedom rộng tạo ra những thay đổi khác nhau ở mỗi view rồi gọi đó là một thiết kế. Nếu facade được phát triển bằng ảnh, phải có bước chuyển quyết định thiết kế vào state dùng chung hoặc thừa nhận đây là marketing concept cần review.

## 6. Camera search: thuật toán và ngân sách cụ thể

### 6.1. Tận dụng framing hiện có

Giữ analytic framing làm seed. Thay các bearing/offset đã tune bằng candidate generator dựa trên facade normal, entrance axis, khoảng trống site và vùng đứng khả thi.

Dùng actual surface/mesh khi có; bounding box chỉ để khởi tạo và broad-phase collision. Không mặc định building song song trục X/Y. Site xoay, L-shape, nhiều khối khác hướng phải được đưa vào validation.

### 6.2. Tìm kiếm hai bước

Bước rẻ: sinh và lọc bằng camera frustum, envelope, collision/BVH và line-of-sight tới các điểm quan trọng.

Bước preview: render các candidate còn lại trong cùng scene/session Blender; đo object/surface visibility, coverage và composition. Không rebuild toàn scene cho từng camera.

Ngân sách đầu tiên để đo feasibility, chưa phải hằng số production:

- 24–48 candidate trên một site, dùng pool chung cho các role.
- Khoảng 512×288 cho preview; chỉ tăng nếu feature quan trọng không đọc được.
- Refine cục bộ quanh 3–5 candidate tốt: azimuth, elevation, focal length, target và distance.
- Chỉ lấy pass cần cho ranking: RGB và object/semantic ID; thêm depth khi đo occlusion cần nó.
- Render full control pack ở các camera được chọn.

Ghi actual build time, preview time/candidate, RAM peak và cache reuse. Điều chỉnh ngân sách bằng đo đạc thay vì mặc định mọi preview đều rẻ.

### 6.3. Hard constraints và preferences

Hard constraints: không nằm trong công trình; không nhìn xuyên khối; không crop feature bắt buộc của role; có sightline tới target; không ra ngoài envelope khả thi đã xác định.

Preferences: subject size, foreground/sky balance, facade depth, leading lines, silhouette separation và lighting readability. Chúng là khoảng mong muốn theo mục tiêu ảnh; không phải một con số bắt buộc cho mọi nhà xưởng.

Không bắt mọi view phải nhìn thấy mọi hạng mục. Góc hero có thể chọn lọc; overall cần hiểu site; detail có thể crop phần khác nhưng giữ target chính.

### 6.4. Chọn cả bộ, không chọn sáu cực đại độc lập

Một camera tốt riêng lẻ có thể gần như trùng nội dung với camera khác. Chọn bộ bằng greedy selection có penalty hoặc bài toán coverage nhỏ:

```text
Set score = chất lượng từng view
          + coverage các surface/semantic cần kể
          - trùng nội dung
          - critical visibility failures
```

Đo overlap theo visible surface khi có; cùng nhìn thấy một building ID không đủ để chứng minh thấy cùng facade.

Số ảnh bàn giao có thể vẫn là sáu để tương thích workflow hiện tại. Mục tiêu của từng slot được chọn theo capability thực tế: site không có office thì không ép slot office phải giả tạo văn phòng.

Deliverable: contact sheet shortlist toàn site, camera ranking có giải thích, selected view set và lý do từng góc được chọn.

## 7. Thiết kế đẹp và giữ thiết kế qua các góc

Thay đổi texture không thể chữa một facade thiếu ý đồ. Camera tốt cũng không đủ nếu brief vẫn ép mọi xưởng thành một kit.

Nghiên cứu thiết kế cần một brief ngắn với hierarchy rõ:

- Loại nhà xưởng và hình ảnh mong muốn.
- Phần nào có trong model, phần nào chưa thiết kế.
- Ưu tiên ở entrance, office, shed và operational yard.
- Material family và palette direction.
- Climate/buildability cues; tránh áp motif trang trí không liên quan.
- Danh sách thay đổi bị cấm có căn cứ.

Ưu tiên xem site master và facade master như hai góc của cùng một phương án. Một master bao quát site chưa chắc đủ đọc facade; facade master nhận identity từ master trước, không tạo một thiết kế độc lập.

Nếu AI tạo articulation/cửa sổ/canopy mới, chọn một trong hai cách:

1. Ánh xạ được về shared design state/geometry: lưu facade zones, opening layout, material family và quy tắc tỷ lệ rồi cập nhật scene để render các góc còn lại.
2. Chưa ánh xạ được: dùng ảnh làm concept reference và chấm inconsistency thủ công; không tuyên bố geometry certified cho chi tiết mới.

Cách 1 là một việc cần chứng minh khả thi, không phải chức năng đã có trong repo. Khi thiết kế làm thay đổi hierarchy thị giác, cho phép một lần xem lại camera shortlist trước khi chốt set final.

## 8. Control render: cải thiện có chọn lọc và kiểm nghiệm

Không đặt mục tiêu toàn bộ photorealism phải do Blender tạo ra. Cũng không giả định một massing render nghèo tín hiệu sẽ luôn được AI giải đúng.

So sánh ba input trên cùng camera và cùng mức freedom:

| Input | Nội dung | Câu hỏi cần trả lời |
|---|---|---|
| C0 — massing trung tính | Geometry/source evidence, bề mặt trung tính, ít facade proposal | Có giúp AI thiết kế tốt hơn và giảm sao chép facade kém không? |
| C1 — control render hiện tại | Pipeline và asset foundation hiện có | Baseline thật của repo |
| C2 — PBR tăng cường nhỏ | Chỉ nâng các vùng chiếm pixel quan trọng: facade/roof response, ground contact, một ít asset thật | Quality gain có đáng chi phí scene/asset/render không? |

Tách geometry control khỏi appearance input. Không gửi mọi pass như các ảnh “reference” ngang quyền. Mỗi block phải nói rõ nó xác nhận layout, hay hướng dẫn finish, hay chỉ dùng để QA nội bộ.

PBR work ưu tiên theo screen-space:

- Aerial: roof response, site surface differentiation, roof-edge shadow, industrial context và haze.
- Hero: facade proportion, glazing/reflection, canopy depth, ground contact.
- Human/detail: construction scale, joint/roughness, asphalt/concrete, asset xe/cây ở gần.

Microdetail dưới một pixel ở độ phân giải output thường không phải việc ưu tiên; cần kiểm tra ảnh thực tế thay vì thêm chi tiết theo checklist.

Context phải có policy nhất quán. Translucent massing phù hợp một số ảnh thuyết minh nhưng có thể làm giảm cảm giác ảnh chụp; thử resolve_proxies trên context có chứng cứ khi mục tiêu là photoreal marketing. GENERATED_SURROUNDINGS chỉ mang tính conceptual, không được chấm là context chính xác.

Pin runtime renderer và ghi color management trước khi so kết quả. Việc đổi sang Cycles/Unreal hoặc asset farm chỉ được chọn khi thí nghiệm nhỏ chứng minh lợi ích.

## 9. Chương trình benchmark theo thứ tự quyết định

Các con số dưới đây là ngân sách gợi ý để lập kế hoạch, chưa là acceptance threshold đã được hiệu chỉnh. Paid runs thuộc giai đoạn triển khai sau.

### E0 — Audit request và dữ liệu, không gọi image provider

- Xuất provenance/authority cho source geometry, procedural proposal và approved design.
- Kiểm tra UI/CLI/job có truyền đúng DesignFreedom và ContextPolicy.
- Rà prompt conflict ở Base RGB, structure guide, palette, context composite và golden-hour exception.
- Xác nhận hai model source sạch và lưu extracted scene/version.
- Đóng băng baseline prompt, input, camera và runtime để có đối chứng.

**Exit:** cùng một yêu cầu có một authority nhất quán, không gọi proposal chưa duyệt là approved.

### E1 — Camera, không gọi image provider

So sánh camera planner hiện tại với candidate search trên cùng scene. Review ngẫu nhiên vị trí A/B và ẩn tên thuật toán.

Đo role accept rate, reviewer preference, unique visible surfaces, duplicate views, occlusion và runtime. Thu thập thêm tình huống site xoay, hẹp và nhiều khối khác hướng.

**Exit:** reviewer chọn được bộ góc tốt hơn; framing không giảm; tham số không tune riêng từng model.

### E2 — Freedom, thử nghiệm nhỏ trên camera cố định

Khởi đầu hai model hợp lệ × hai góc (site, facade) × ba mức freedom = 12 ảnh screening với cùng provider/configuration. Dùng input hiện tại và không external reference để tách tác động freedom.

Chấm riêng **design quality**, **photographic realism** và **source geometry retention**. Chọn một hoặc hai cấu hình trên Pareto frontier; không cho điểm đẹp bù lỗi source layout.

**Exit:** có bằng chứng mức mở thiết kế phù hợp hơn strict hoặc xác định strict vẫn cần thiết cho trường hợp nào. Một sample mỗi ô chưa đủ để kết luận độ ổn định.

### E3 — Conditioning và PBR ablation

Giữ camera/freedom/provider đã chọn; so C0/C1/C2 ở một aerial và một facade. Giữ geometry constraints tương đương; ghi rõ feature bị thay đổi do input khác.

Sau đó thử tối đa một appearance reference dạng crop/material board nếu cấu hình không reference chưa đạt. Không đồng thời đổi provider, prompt, camera và input.

**Exit:** xác định mức input tối thiểu đạt quality/fidelity; PBR mở rộng chỉ dựa trên lợi ích quan sát được.

### E4 — Provider challenger khi cần

Chỉ mở khi provider hiện tại không đạt cân bằng quality/fidelity. Tận dụng adapter đã có; kiểm tra credential/capability ngoài tài liệu trước khi gọi.

- Gemini: baseline multi-reference, thử project master.
- Stability Structure: spatial-control challenger; sweep thấp/vừa/cao để đo trade-off. Không so như thể adapter này cũng nhận Design Master.
- Adapter thay thế đã tích hợp: thử khi có access và phù hợp operation.

So cùng geometry authority, output resolution và review rubric. Không ép cùng prompt byte-for-byte nếu API khác; lưu prompt tương đương về mục tiêu. Không gọi seed bằng nhau giữa hai provider là phép thử ngẫu nhiên tương đương.

**Exit:** chọn theo quality, critical failure rate, cost/accepted view và latency; không mặc định model đắt hơn thắng.

### E5 — Multi-view pilot và validation

So hai chiến lược:

- M0: master strategy hiện tại.
- M1: primary + complementary master có cùng identity, reference chọn theo surface overlap; không tạo chain chỉ bám ảnh cuối.

Giữ một daylight thống nhất trong pilot đầu. Golden-hour variant tách thành thử nghiệm riêng để tránh nhiễu vật liệu/white balance.

Lặp lại các cấu hình thắng E2–E4 ít nhất ba lần chạy ở các góc đại diện để đo biến thiên. Với set sáu ảnh, ghi pass rate cả set, không chỉ trung bình từng ảnh.

**Exit:** không có critical geometry/design contradiction ở các set được bàn giao, realism đạt review, chi phí retry được ghi.

Dùng model chưa tham gia tuning để đánh giá khả năng tổng quát. Nếu mới có hai model development, kết quả chỉ là feasibility pilot; chưa tuyên bố generalization.

## 10. Dataset khả dụng và dữ liệu phải bổ sung

Theo báo cáo camera nội bộ:

- sample 1: bounds khoảng 352×166×11 m.
- sample 2: bounds khoảng 125×142×15 m.
- sample 3/4: canonicalizer từ chối vì focus-building alternatives chồng lấn; cần chọn coherent option/export view hoặc dữ liệu thay thế.

Không đưa sample 3/4 vào benchmark như model đã sạch; cũng không nới guard để tạo camera trên scene mâu thuẫn.

Hai model đầu đủ để phát hiện một số lỗi tỷ lệ, chưa bao phủ site irregular, nhiều hướng building, office thiếu, gate thiếu hoặc transport geometry phức tạp.

Validation nên bổ sung ít nhất các nhóm sau:

- Xưởng dài trên site rộng.
- Site hẹp, khoảng lùi thấp.
- Nhiều xưởng và office tách khối.
- Building xoay hoặc các khối không cùng phương.
- Site thiếu office/gate/boundary evidence.
- Site irregular hoặc nhiều khối phụ che facade.

Mục tiêu ban đầu có thể là thêm 4–6 model độc lập. Đây là nhu cầu bổ sung dữ liệu, không phải dataset hiện đã tồn tại. Synthetic rotation/scale fixtures hữu ích để kiểm tra solver, nhưng không thay thế model validation mới.

## 11. Đánh giá fidelity và realism đúng mức

### 11.1. Camera lock

Tận dụng module camera_lock, nhưng bổ sung bước quan sát landmark trong ảnh generated. ID/depth của base chỉ cho vị trí kỳ vọng, không tự cho vị trí landmark trong ảnh AI.

Dùng landmark gắn với geometry nguồn: góc footprint, mép mái quan trọng và intersection đường có chứng cứ. Loại các chi tiết facade đang được phép thiết kế lại.

Để bắt scale/rotation/crop, cần phân bố landmark đủ rộng và kiểm tra affine/pose residual; median offset một mình không đủ. Ngưỡng chuẩn hóa theo kích thước ảnh. Landmark thiếu/không đáng tin → unverifiable/review.

### 11.2. Geometry và semantics

Silhouette/critical edge distance hữu ích trên vùng nguồn được khóa. Không dùng edge F1 toàn ảnh để phạt panel joint hoặc window mới đã được phép.

Phát hiện missing/extra object và sai boundary theo critical source objects. Segmentation trong ảnh AI là ước lượng, cần hiệu chỉnh bằng annotation/reviewer; mask source không chứng minh ảnh AI còn đúng semantic.

Pixel restore chỉ chứng minh pixel nguồn được dán lại ở mask, không chứng minh toàn ảnh có geometry đúng hoặc lighting coherent. Nó có thể tạo seam, double edge và mảng CGI. Giữ như một variant/fallback được review, không đặt làm mặc định photoreal.

### 11.3. Cross-view

Dùng camera matrices, metric depth, surface ID và visibility/occlusion check cho source surfaces. Correspondence index theo object hiện tại là nền tảng, chưa là dense reprojection.

Với reflective glass, shadow và góc sáng khác, so material identity/features và layout; không đòi pixel RGB bằng nhau.

Với facade mới do AI tạo, base surface ID không mô tả hết chi tiết. Phải cập nhật approved design state hoặc dùng manual consistency review cho chi tiết đó.

### 11.4. Review mù

Dùng ít nhất hai reviewer nếu có thể: một người kiểm source/design, một người kiểm cảm giác ảnh chụp. Khi chỉ có một reviewer, ghi rõ hạn chế.

Rubric 1–5, chấm riêng:

- Composition và câu chuyện của bộ ảnh.
- Industrial design/buildability plausibility.
- Photographic realism.
- Material/lighting/asset scale.
- Source geometry retention.
- Cross-view design consistency.

Lưu win/tie/loss theo cặp, lý do reject, model và role. Báo số mẫu và biến thiên; không chỉ báo “thắng 80%” từ vài cặp. Không dùng FID cho pilot nhỏ như một chứng nhận realism.

Một VLM có thể hỗ trợ shortlist/triage, nhưng phải so với reviewer và không là authority duy nhất.

## 12. Acceptance và quy tắc dừng

Các ngưỡng điểm được hiệu chỉnh sau development set. Gợi ý dùng điểm ≥4/5 cho realism và design ở ảnh bàn giao, nhưng đây là target ban đầu.

Điều kiện bàn giao một set:

- Không có critical source geometry change hoặc critical design contradiction.
- Mọi slot được chọn có mục tiêu hợp lý theo capability của site.
- Không có view bị nhân đôi nội dung chỉ để đủ số lượng.
- Mỗi ảnh bàn giao đạt review realism/composition; ảnh yếu phải được thay hoặc bỏ theo yêu cầu deliverable.
- Geometry evidence tự động hoặc manual review được ghi rõ; không đánh đồng marketing approval với machine geometry certification.
- Model/source revision, camera, prompt, input hash, output và approval có lineage.

Loại bỏ điều kiện cũ “5/6 ảnh đạt là sẵn sàng bàn giao”. Mức đó có thể dùng như mốc cải thiện nội bộ, nhưng một bộ giao đủ sáu ảnh phải review đủ sáu ảnh.

Dừng thử lại cùng cấu hình khi lỗi có hệ thống về camera, authority, source export hoặc context policy. Retry không sửa được nguyên nhân đó.

Nếu freedom rộng thắng về design nhưng consistency giảm: tăng shared design state/master coverage trước khi siết lại toàn facade. Nếu input PBR làm model giữ thiết kế kém: giảm authority của proposal và thử neutral massing. Nếu camera score không khớp reviewer: chỉnh ranking/rubric, không tune tọa độ từng model.

## 13. Kế hoạch triển khai đề xuất sau khi nghiên cứu được duyệt

| Mốc | Phạm vi tối thiểu | Artifact cần có | Điều kiện tiếp tục |
|---|---|---|---|
| R0 — authority audit | Source/proposal/approved provenance và request conflict | authority report, baseline manifest | Request thể hiện đúng freedom/context |
| R1 — camera prototype | Pool candidates, analytic/BVH filter, preview, shortlist | contact sheets, camera metrics, runtime | Bộ góc thắng baseline trên development |
| R2 — design freedom spike | E2, rồi conditioning ablation nhỏ E3 | blind review, failure taxonomy | Cấu hình đẹp hơn vẫn giữ source geometry |
| R3 — consistency pilot | Tận dụng dual masters, reference overlap, review | six-view boards, design state/limitations | Mọi ảnh bàn giao và cả set đạt review |
| R4 — validation | Model mới, repeated runs, cost/accepted set | validation report, Go/No-Go | Có evidence tổng quát hóa |
| R5 — editing | Chỉ lập scope khi R4 đạt | Kế hoạch editing riêng | Generation ổn định và grounding đã kiểm chứng |

Không cam kết engineering days hoặc chi phí generation trước khi đo E0/E1. Khi có số liệu, tách scene build, preview/render, API, review và retry.

Nâng asset library chỉ ở những vùng được E3 xác nhận là blocker. Provider migration, custom diffusion, texture-space generation và đổi renderer không thuộc việc phải làm ngay.

## 14. Ranh giới đối với editing

Generation refinement từ control image là phần đang có của pipeline. Nó không đồng nghĩa bắt đầu UI editing, selection, brush, lasso hoặc sửa thiết kế tương tác.

Chưa triển khai image editing trong các mốc R0–R4.

Sau đó mới đánh giá:

- Mask có tương ứng với ảnh bàn giao hay không.
- Camera/geometry drift có làm click-to-object sai không.
- Provider thực sự dùng mask và có giữ ngoài vùng được chọn không.
- Cách lưu history và cập nhật approved design state.
- Local appearance change có lan truyền sang view khác như thế nào.

Không để editing trở thành cách chữa ảnh generation thiếu camera tốt hoặc thiếu consistency.

## 15. Những điều chưa biết và cần kiểm nghiệm

1. Profile/UI hiện dùng freedom nào ở request thật?
2. Mở freedom có cải thiện design/realism đủ lớn trên hai model sạch không?
3. Neutral massing hay control render có chi tiết cho kết quả tốt hơn?
4. Một vài nâng cấp PBR có giảm critical fail hay chỉ tăng runtime?
5. Hai master hiện tại nhìn thấy đủ các surface quan trọng chưa?
6. Design decisions từ ảnh có thể ánh xạ về shared state ở mức nào?
7. Camera search có chạy nhanh trong runtime/container hiện tại không?
8. Ranking tự động có cùng preference với reviewer không?
9. Context translucent hay resolved phù hợp từng deliverable?
10. Failure rate của cả set trên model validation và repeated runs là bao nhiêu?

Chỉ sau khi các câu hỏi này có số liệu mới chọn cấu hình production. Hiện có cơ sở để ưu tiên authority audit, camera search và freedom/conditioning ablation; chưa có cơ sở để tuyên bố đã tìm được phương án tối ưu cuối cùng.

## 16. Nguồn nghiên cứu và tài liệu đối chiếu

Nguồn sơ cấp được kiểm tra trong lần nghiên cứu này; khả năng/model/API có thể thay đổi, phải xác nhận lại trước khi chạy paid benchmark.

- [Viewpoint Selection for Photographing Architectures](https://arxiv.org/abs/1703.01702) — kết hợp tín hiệu ảnh và hình học cho viewpoint recommendation; không cung cấp một preset góc phổ quát cho mọi site.
- [ControlNet, ICCV 2023](https://arxiv.org/abs/2302.05543) — spatial conditioning bằng edge/depth/segmentation; nền tảng control, không phải bảo đảm topology tuyệt đối.
- [Gemini image generation documentation](https://ai.google.dev/gemini-api/docs/image-generation) — image input, multi-reference, conversational iteration và giới hạn; không suy từ tài liệu thành capability adapter đã triển khai.
- [MVDiffusion, NeurIPS 2023](https://arxiv.org/html/2307.01097v7) — correspondence-aware generation; kiểm tra phần depth-to-image/ScanNet và giới hạn chuyển domain.
- [GenesisTex](https://arxiv.org/html/2403.17782v1) — texture-space consistency và hạn chế memory; khác với thiết kế geometry mới.
- [Blender 4.5 LTS — color management](https://docs.blender.org/manual/es/4.5/render/color_management.html) — nguồn chính thức cho AgX; trang tiếng Anh không đọc được qua công cụ ở lần này.
- [Blender — render passes](https://docs.blender.org/manual/en/latest/render/layers/passes.html) — data passes; phải đối chiếu đúng engine/version đang chạy.
- [Stability developer API reference](https://platform.stability.ai/docs/api-reference) — endpoint reference; trang động không trả nội dung chi tiết qua công cụ. Không dựa riêng vào trang này để xác nhận parameter hiện hành; đối chiếu adapter và kiểm tra endpoint trước paid run.

Tài liệu nội bộ:

- [Model-agnostic camera planning](V365_MODEL_AGNOSTIC_CAMERA_PLANNING_PLAN.md) — framing, hai model dùng được và blocker sample 3/4.
- [Photoreal experiment report](V365_PHOTOREAL_IMAGE_AND_EDITING_EXPERIMENT_REPORT.md) — ablation reference/provider và giới hạn QA lịch sử.
- [Multi-view realism research](V365_MULTIVIEW_REALISM_RESEARCH_AND_EXPERIMENTS.md) — style-anchor experiments và thiếu richness của scene.
- [Controlled realism readiness](V365_CONTROLLED_REALISM_IMPLEMENTATION_READINESS_REPORT.md) — PBR/control/protection research và kết quả spike.
- [Customization redesign](V365_CUSTOMIZATION_MULTIVIEW_QUALITY_REDESIGN.md) — semantic intent, master workflow và các giới hạn consistency.

Các báo cáo nội bộ phản ánh thời điểm riêng. Khi khác trạng thái code, ưu tiên kiểm tra implementation và request runtime hiện tại.

---

## 17. Trạng thái thực hiện — 2026-09-18

### Đã xong

| Mốc | Kết quả | Báo cáo |
|---|---|---|
| E0 authority audit | Đạt exit. Ba lỗi chặn đã sửa, có test hồi quy. | [E0](V365_E0_AUTHORITY_AUDIT.md) |
| E1 camera | Bearing suy từ chứng cứ site. Model B **4/6 → 6/6**. Vòng tự sửa đã có, **chưa chạy được ca thật**. | mục 14 của [camera plan](V365_MODEL_AGNOSTIC_CAMERA_PLANNING_PLAN.md) |
| E2 freedom | 12 ảnh. `design_within_envelope` thắng **17.00/20** khi chấm mù. | [E2](V365_E2_FREEDOM_ABLATION.md) |
| E3 conditioning | 8 ảnh. C0 khối trắng chỉ hơn **+1.25**, trong nhiễu, và **massing 2/4 trượt**. | [E3](V365_E3_CONDITIONING_ABLATION.md) |
| Review mù | 20 ảnh. Sửa lại một kết luận, củng cố một kết luận. | [blind](V365_BLIND_REVIEW_RESULTS.md) |

### Quyết định đã chốt bằng bằng chứng

`design_within_envelope` là **mặc định** cho pack marketing. Chấm mù: 17.00 so với 12.75
(`photoreal_only`) và 11.50 (`detail_within_envelope`), dẫn trước ở **cả** design lẫn realism.
`marketing_detail.json` đã gỡ khỏi catalog vì bị lấn át trên mọi trục.

Đòn bẩy nằm ở **lời văn prompt**, không ở chi tiết bản nháp: nới freedom được +4.25 đến +5.50 và
không cần đổi renderer; tước facade khỏi bản nháp chỉ được +1.25 và mất luôn ràng buộc số mái.

### Sửa lại hai tuyên bố trước đó

**"Cổng edge sai 10/11 lần" — không đáng tin.** Con số đó suy "camera giữ nguyên" từ "massing đạt",
mà điều đó không suy ra được: massing chỉ đếm khối, nó không thấy camera dịch. Kiểm lại A1 view-03
bằng mắt cho thấy camera **thật sự bị dựng lại** — cổng edge đúng, tôi gọi nhầm là báo động giả.
Tỉ lệ báo động giả thật của cổng edge hiện **chưa biết**.

**"C0 đẹp hơn rõ rệt" — sai một nửa.** Chấm mù: C0 hơn về design (4.00 so với 3.00) nhưng **hoà về
realism** (3.75 cả hai). Khi chấm không mù tôi đã gộp "kiến trúc tốt hơn" thành "chân thật hơn".

### Lưới an toàn thay thế

`GeminiViewJudge` + `verify-views`: hỏi viewpoint, placement và openings bằng chính cơ chế
vision-judge mà cổng massing đã chứng minh hoạt động. Kiểm định trên 4 ca có đáp án: **3/4 đúng**,
và nó bắt được đúng ca camera bị dựng lại mà tôi đã bỏ sót.

### Còn nợ

- **C2 (PBR tăng cường) chưa chạy** — chưa có chế độ render, E3 mới trả lời nửa câu hỏi.
- **Chưa lặp lần nào.** E2/E3 đều n=1 mỗi ô; kế hoạch yêu cầu ≥3.
- **Một người chấm mù.** Kế hoạch yêu cầu hai.
- **n=2 model.** Bearing, vòng tự sửa và trọng số access đều chỉ đứng trên hai model.

## 18. Increment triển khai và kiểm chứng — 2026-09-18

Trạng thái chi tiết: [V365_RENDER_QUALITY_IMPLEMENTATION_STATUS.md](V365_RENDER_QUALITY_IMPLEMENTATION_STATUS.md).

Đã nối style/context xuyên workflow và UI marketing, snapshot/isolate job, thêm input giữ
envelope + programme nhưng bỏ facade procedural, sửa solver camera và office clearance,
chặn xuất ảnh fail/review/unverified và trộn các Design Master độc lập. Đã chạy Blender và
hai proposal Gemini trên model B, có một office proposal qua vision QA; overall proposal vẫn
review vì tự thêm dock/ramp. **Chưa có bộ sáu ảnh đạt bàn giao marketing**; không đánh dấu
camera search mặc định, C2, benchmark lặp hoặc consistency toàn set đã hoàn thành.

## 19. Reference-led freedom: benchmark lặp — 2026-09-18

Bằng chứng và đề xuất chi tiết:
[V365_REFERENCE_FREEDOM_EXPERIMENT_RESULTS.md](V365_REFERENCE_FREEDOM_EXPERIMENT_RESULTS.md).

Đã generate **24/24 ảnh**, một site B, hai mục đích aerial/office, ba lần lặp độc lập
mỗi mức: reference-only → text envelope → registered camera/render → programme lock.
Cùng model/brief/reference/resolution trong vòng này; không so điểm nhân quả với các
vòng cũ khác palette. Review VLM là advisory, không thay hai người chấm thật.
Đã thực hiện 42 lượt chấm: 41 thành công, một unavailable không retry; quality có điểm
23/24 ảnh. Office R1 design/realism 5.00/5.00, R3 3.33/3.33 (mỗi nhóm n=3);
R2 office chỉ n=2 có điểm. Aerial R2/R3 hòa design/realism trung bình, nên không kết luận
khóa programme làm mọi góc xấu hơn. Bảng điểm/range và dữ liệu raw nằm trong báo cáo.

Ảnh thực tế cho thấy model có khả năng phát triển office, canopy và vật liệu tốt hơn
bản procedural, nhưng text envelope có thể đổi quan hệ công trình; thêm camera/programme
lock bằng prompt cũng không đủ giữ camera. **Không bỏ source fidelity để đổi lấy ảnh đẹp,
không tăng khóa facade/openings không có nguồn để chữa lỗi camera.**

Ưu tiên tiếp theo là tách source/client-approved khỏi design-proposal, cho AI phát triển
Design Master theo reference, tìm camera theo scene thay vì template, rồi benchmark input
geometry/camera độc lập với kiến trúc tham khảo. Dùng conditioning factorial và ground-truth
camera QA trước khi thử cả set chung master và nhiều site. `design_within_envelope` vẫn
là ứng viên có triển vọng, không được gọi là phương án tối ưu hoặc marketing-ready chỉ
từ benchmark một site hay điểm VLM. Vòng này chưa làm editing/inpainting.

Judge đã có phản ví dụ: đọc một ảnh office cục bộ thành vi phạm số lượng toàn campus
(R1 office rep-2/3). Do đó kết quả QA cũ 3/4 không đủ chứng minh judge đáng tin tổng quát.
Các ca thiếu chứng cứ phải đi vào review/unknown; cần calibration có ground truth và
phân biệt semantic viewpoint với camera registration trước khi dùng làm gate tự động.

## 20. Kế hoạch tích hợp reference-led vào luồng chính

Sau phản hồi tích cực của người dùng về ảnh thử nghiệm, đã đánh giá lại code hiện tại
và lập [kế hoạch production integration](V365_REFERENCE_LED_PRODUCTION_INTEGRATION_PLAN.md).
Luồng chính đã có Site → Facade identity chain và approval; khác biệt còn nằm ở reference
finish-only, routing reference vào master, programme authority và camera orchestration.

Ưu tiên P0/P1: policy/builder có version, typed reference bundle và proposal pilot trong
API/job/UI, để kiểm chất lượng mới trước khi chờ hoàn thiện hình học toàn set. P2/P3 duyệt
master family/requirements và chọn shot theo scene; P4/P5 kiểm set và rollout marketing.
Giữ strict/tender và policy của job cũ. Không mở rộng editing, không đổi production code
trong lượt lập kế hoạch, không gọi thêm API trả phí. Backend hiện tại 241 test qua.
