# V365 Customization & Multi-view Quality Redesign

## 1. Kết luận

Pipeline hiện tại chưa đủ an toàn để cho phép người dùng tự chọn năm màu rồi gửi thẳng năm
mã HEX cho mô hình sinh ảnh. Lỗi của bộ `R01-accc47258a92` không phải một sai số ngẫu nhiên đơn
lẻ mà đến từ ba tầng:

1. contract màu chưa phản ánh đúng cấu tạo công trình công nghiệp;
2. Design Master được chọn từ view ít thể hiện thiết kế và chưa được kiểm định trước khi lan truyền;
3. QA chỉ kiểm tra màu lạ, chưa kiểm tra màu bắt buộc và tính đồng nhất theo semantic role.

Hướng phù hợp là **controlled customization**: người dùng chọn ý đồ và màu thương hiệu, hệ thống
biên dịch thành một material system khả thi; render điều kiện phải thể hiện chính xác material
system đó; AI chỉ nâng độ chân thật, không tự thiết kế lại màu hoặc cấu kiện.

## 2. Bằng chứng từ bộ ảnh mới nhất

Input thực tế:

- facade/màu chính: `#A92828`;
- kết cấu/màu phụ: `#0A95F9`;
- kính: `#294B5B`;
- điểm nhấn: `#176B4D`;
- paving: `#74797A`.

Contract hiện tại dùng màu chính cho cả mái và tường, dùng màu phụ cho kết cấu, cửa, cổng và hàng
rào. Vì thế một lựa chọn đỏ–xanh bão hòa đã được khuếch đại lên hầu hết diện tích công trình. Hệ
thống đáng lẽ phải biến ý đồ này thành facade đỏ có kiểm soát, mái sáng trung tính, kết cấu trung
tính và màu thương hiệu chỉ nằm ở chi tiết nhỏ.

Đo trực tiếp vùng semantic của công trình chính trên sáu ảnh:

| View | Tỷ lệ pixel bão hòa | Pixel gần màu đỏ chính | Nhận xét |
|---|---:|---:|---|
| VIEW-01 | 3,3% | 0,0% | Design Master bỏ hoàn toàn palette, chuyển xưởng thành trắng |
| VIEW-02 | 74,5% | 18,0% | Mái đỏ nhưng thân nhà chủ yếu trung tính |
| VIEW-03 | 16,1% | 0,0% | Lại chuyển xưởng thành beige/trắng |
| VIEW-04 | 63,6% | 11,6% | Hầu hết bao che đỏ, khác VIEW-01/03 |
| VIEW-05 | 87,4% | 30,3% | Gần như toàn bộ khối đỏ |
| VIEW-06 | 97,0% | 73,5% | Mặt đứng đỏ đặc và cổng xanh tách rời kiến trúc |

`technical_qa.json` vẫn đánh dấu palette của cả sáu view là pass. Hàm hiện tại chỉ hỏi “có xuất
hiện hue ngoài danh sách cho phép hay không”; nó không hỏi “màu bắt buộc có xuất hiện đúng semantic
role hay không”, nên VIEW-01 và VIEW-03 trắng vẫn qua gate.

## 3. Lỗi triển khai đã xác định

Trong `GeminiConditioningMode.PHOTOREAL_BALANCED`, adapter từng lấy chuỗi từ marker
`VIEW PURPOSE` đến cuối. Toàn bộ phần trước marker — gồm color-role lock, facade grammar, luật
cổng, hàng rào và context — bị bỏ khỏi request gửi tới Gemini.

VIEW-01 sau đó được chọn làm Design Master chủ yếu vì role `overall`, mặc dù focus building chỉ
chiếm 12,9% ảnh. Design Master trắng sai này được gửi làm appearance reference cho năm view còn
lại, trong khi base RGB của chúng lại đỏ–xanh. Hai authority mâu thuẫn khiến kết quả drift.

## 4. Thiết kế lại input cho người dùng

### 4.1 Material system thay cho năm ColorPicker ngang quyền

Schema kế tiếp nên tách các vai trò:

- `roof_finish`: mái kim loại sáng, dải lựa chọn được giới hạn theo khả năng phản xạ nhiệt;
- `facade_body`: màu thân nhà chính;
- `facade_secondary`: mảng phụ, giới hạn tỷ lệ diện tích;
- `structure_trim`: cột, diềm, flashing và cửa;
- `brand_accent`: lối vào/biển hiệu, tối đa 3–8% facade;
- `glass`: chỉ áp vào vùng kính authored;
- `boundary`: hàng rào/cổng, mặc định neutral và không kế thừa brand accent;
- `paving`: đường và sân.

UI mặc định cung cấp 4–6 palette công nghiệp đã kiểm duyệt. Chế độ “Tùy chỉnh nâng cao” vẫn cho
đổi màu, nhưng hiển thị:

- tỷ lệ sử dụng dự kiến trên facade;
- cảnh báo độ bão hòa/chênh hue/độ sáng không phù hợp với vai trò;
- preview vật liệu theo ba lớp `base / body / top` và một đoạn cổng–hàng rào;
- nút “Tự cân bằng palette” để giữ hue thương hiệu nhưng giảm chroma hoặc chuyển nó sang accent.

Không tự âm thầm đổi màu sau khi submit. Applied palette phải được preview và người dùng xác nhận.

### 4.2 Decor phải là cấu kiện có nghĩa

Một thanh `minimal/subtle/balanced/expressive` không đủ mô tả thiết kế. Decor nên được biên dịch
từ các kit độc lập, chỉ bật khi model có semantic evidence:

- facade rhythm: vertical bay, horizontal band hoặc mixed restrained;
- office entrance: recessed, framed hoặc canopy;
- loading frontage: dock canopy, bumper/door frame và service signage;
- plinth/top band: chiều cao và vật liệu khả thi;
- fence: vertical bar hoặc welded mesh;
- gate: sliding hoặc hinged theo bề rộng và khoảng lùi authored;
- landscape: tuyến cây, bụi thấp và khoảng nhìn an ninh tại cổng.

Số tầng không nên được dùng như một alias cho “nhịp facade”. Nếu LOD100 không chứng minh số tầng,
control này phải đổi tên hoặc bị khóa; nếu không AI sẽ phát sinh cửa sổ/sàn không có cơ sở.

## 5. Thiết kế lại pipeline sinh ảnh

### Gate A — Compile và kiểm tra intent, chưa gọi AI

1. Validate material-role compatibility.
2. Tạo applied material system và preview.
3. Validate decor kit dựa trên scene semantics.
4. Yêu cầu người dùng xác nhận nếu có cảnh báo mạnh.

### Gate B — Deterministic Design Identity Pack

Không dùng một ảnh drone đã AI hóa làm nguồn duy nhất cho thiết kế. Tạo deterministic identity
board gồm palette theo vai trò, crop facade/material-ID, roof finish, module facade, cổng và hàng
rào. Board là reference appearance không phụ thuộc camera.

### Gate C — Chỉ sinh Design Master

Sinh 2 candidate cho view thể hiện nhiều facade/entrance nhất. Chưa sinh năm ảnh còn lại. Chấm:

- semantic-role palette adherence;
- geometry/edge alignment;
- roof, gate và fence completeness;
- photographic realism;
- facade articulation.

Nếu không candidate nào đạt, dừng tại đây. Nếu đạt, người dùng duyệt một Design Master. Cách này
giảm chi phí lớn hơn việc sinh đủ sáu ảnh rồi mới phát hiện sai.

### Gate D — Multi-view propagation theo overlap

Sắp xếp view thành graph theo correspondence/camera overlap. Mỗi view nhận:

1. base RGB và control passes của chính nó;
2. deterministic identity board;
3. Design Master đã duyệt;
4. ảnh đã duyệt gần nhất có overlap cao.

Không dùng cùng một ảnh drone ít overlap làm reference duy nhất cho mọi góc. Google khuyến nghị
đưa ảnh đã sinh vào lượt tiếp theo để duy trì consistency; nghiên cứu multi-view cũng cho thấy
reference ít overlap làm giảm chất lượng, còn cross-view/3D-aware conditioning cải thiện coherence.

### Gate E — Role-aware QA và repair có mask

QA cần đo riêng trên semantic mask:

- roof so với `roof_finish`;
- primary facade so với `facade_body`;
- design detail so với `brand_accent` và giới hạn diện tích;
- site boundary so với `boundary`;
- cùng một role giữa các view bằng hue/chroma/lightness và texture embedding;
- fence continuity, gate connection và số lượng opening.

Nếu chỉ sai một role, repair bằng mask cho role đó; không regenerate toàn frame.

## 6. Thứ tự triển khai đề xuất

### P0 — Đã sửa ngay

- gửi toàn bộ approved refinement specification tới Gemini;
- xác lập base RGB là authority của vị trí các vùng màu chính;
- khi Design Master mâu thuẫn palette/base RGB thì palette và base RGB thắng;
- chọn master theo focus/circulation/context coverage thực đo thay vì ưu tiên cứng view overall;
- loại bỏ xung đột `authored_only`: vùng trống không còn được phép phát sinh nhà xưởng, đường,
  hàng rào hoặc plot ngoài model;
- bump prompt/grammar version để không reuse output cũ.

### P1 — Đã triển khai và kiểm thử tự động

- material system schema mới và curated presets;
- palette compatibility validator + applied-palette preview;
- semantic-role palette QA;
- Design Master-only generation/approval gate.

Hiện Gate C sinh một candidate ở 1K và dừng để duyệt. Biến thể hai candidate cùng scoring tự động
được giữ lại cho benchmark có phí, tránh tăng gấp đôi chi phí trước khi có dữ liệu chứng minh lợi ích.

### P2.1 — Đã triển khai: semantic design workflow

- endpoint phân tích capability từ `CanonicalScene`, trả evidence cho envelope, văn phòng/lối vào,
  logistics, hàng rào, cổng, cảnh quan, giao thông và mái;
- form hai bước: upload/phân tích model trước, sau đó mới mở các component kit có chứng cứ;
- thay control mơ hồ `style/decor/số tầng/số dock/mức sáng tạo` bằng design package, envelope,
  facade rhythm, office entrance, logistics, boundary, gate và accent coverage 3/5/8%;
- lựa chọn không được model hỗ trợ bị compiler chuyển về `preserve_model` và phát cảnh báo;
- logistics kit không tự phát sinh số lượng cửa dock từ một loading-zone footprint;
- preview token SHA-256 khóa model + project + normalized intent + catalog version; nếu form đổi sau
  preview thì UI bắt buộc kiểm tra lại;
- `preview_fast` và `marketing_hero` được điều khiển bằng mục tiêu chi phí/chất lượng trên form;
- Blender conditioning đọc kit facade/envelope/boundary/gate để tạo deterministic identity trước AI;
- prompt và identity pack chứa cùng factory design system và giới hạn màu nhận diện;
- Design Master vẫn là lượt AI đầu tiên; năm view còn lại chỉ chạy sau duyệt.

Contract API bổ sung:

- `GET /v1/models/{model_revision}/design-capabilities`;
- `POST /v1/models/{model_revision}/design-preview`;
- `POST /v1/projects/{project_id}/design-revisions` nhận `preview_token` để phát hiện drift.

### P2.2 — Chỉ kích hoạt sau benchmark có phí

- overlap graph và chained reference;
- masked repair theo semantic role;
- benchmark A/B trên cùng model, cùng camera, cùng palette.

Các mục P2.2 không nên mặc định bật trước khi benchmark chứng minh chúng cải thiện chất lượng đủ để
bù thêm chi phí API. Kiến trúc hiện tại giữ sẵn Gate D/E nhưng flow production dừng ở Design Master
để người dùng quyết định trước khi tiêu thêm năm lượt sinh ảnh.

## 9. Form production được chốt

Thứ tự thao tác bắt buộc:

1. Chọn RVT và **Phân tích cấu kiện có thể thiết kế**.
2. Kiểm tra badge evidence; control thiếu evidence sẽ bị khóa.
3. Chọn một design package và các kit cấu tạo có nghĩa.
4. Chọn palette theo semantic role và giới hạn accent 3%, 5% hoặc 8%.
5. Chọn bối cảnh vận hành, cảnh quan, thời điểm và mức chất lượng.
6. Bấm **Kiểm tra phương án**; đọc applied intent/cảnh báo, chưa gọi image AI.
7. Bấm **Tạo Design Master**; duyệt một ảnh trước khi chạy năm ảnh còn lại.

Mái, footprint, chiều cao, đường, cổng opening, hàng rào, vùng xanh và camera luôn thuộc geometry
authority của model. Form chỉ thay đổi vật liệu, nhịp chi tiết và mức hoàn thiện tại vùng có evidence.

## 7. Tiêu chí chấp nhận benchmark

- 6/6 view giữ cùng material roles; không view trắng, đỏ đặc hoặc đổi hệ màu ngoài ý đồ;
- roof/facade/boundary role đạt ngưỡng màu riêng, không chỉ “không có màu lạ”;
- cổng nối hàng rào, không floating frame; fence continuity đạt 100% đoạn authored nhìn thấy;
- facade detail chỉ xuất hiện tại vùng đủ semantic evidence;
- Design Master fail thì không phát sinh thêm 5 lượt gọi ảnh;
- hội đồng đánh giá mù ưu tiên output mới về realism và design coherence trên ít nhất 80% cặp A/B.

## 8. Nguồn tham khảo

- Google Gemini image generation: multiple reference images, iterative editing, consistency and
  prompting guidance: https://ai.google.dev/gemini-api/docs/generate-content/image-generation
- ControlNet, spatial conditioning with edges/depth/segmentation:
  https://openaccess.thecvf.com/content/ICCV2023/papers/Zhang_Adding_Conditional_Control_to_Text-to-Image_Diffusion_Models_ICCV_2023_paper.pdf
- ConsistNet, 3D-aware cross-view consistency:
  https://openaccess.thecvf.com/content/CVPR2024/papers/Yang_ConsistNet_Enforcing_3D_Consistency_for_Multi-view_Images_Diffusion_CVPR_2024_paper.pdf
- Auto-regressive multi-view generation and the low-overlap reference problem:
  https://openaccess.thecvf.com/content/ICCV2025/papers/Hu_Auto-Regressively_Generating_Multi-View_Consistent_Images_ICCV_2025_paper.pdf
- Multi-view architectural generation with style, structure and angle-alignment losses:
  https://arxiv.org/abs/2503.03068
- Kingspan roof/wall panel colour and coating ranges:
  https://www.kingspan.com/content/dam/kingspan/kip-west/kingspan-insulated-panels-colorbook-au-en.pdf
- Built factory references in Vietnam demonstrating restrained, constructible facade identity:
  https://www.archdaily.com/797465/katzden-architec-factory-nishizawaarchitects
  and https://www.archdaily.com/1025799/huy-hoang-lock-factory-baumschlager-eberle-architekten
