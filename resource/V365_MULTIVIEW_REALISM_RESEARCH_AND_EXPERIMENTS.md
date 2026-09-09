# V365 Multi-view Realism — nghiên cứu và kiểm nghiệm

Ngày đánh giá: 2026-09-09  
Model kiểm nghiệm: `resource/model_lod100_sample.rvt`

## Kết luận điều hành

Không thể đạt đồng thời độ đúng model, đồng nhất sáu góc và chất lượng ảnh chụp chỉ bằng cách
gửi sáu conditioning pack thành sáu yêu cầu image-to-image độc lập. Pipeline sản xuất nên là
**3D-first, style-locked, AI-bounded**:

1. Khóa hình khối, giao thông, cảnh quan, mái, facade grammar và vật liệu trong một scene 3D dùng
   chung.
2. Làm phần lớn độ chân thực bằng PBR, ánh sáng vật lý, asset cây/xe/người đúng tỷ lệ và camera
   deterministic.
3. Dùng một close hero view đã qua kiểm tra làm style anchor cho cả view-set.
4. Chỉ cho AI hoàn thiện vật liệu, vi sai bề mặt và khí quyển trong các semantic mask được phép;
   không cho AI thiết kế lại silhouette, đường hay cảnh quan.
5. Fail-closed bằng QA hình học, màu/vật liệu, cross-view và photorealism trước human review.

Giải pháp ảnh neo là bước ngắn hạn phù hợp với Gemini hiện có. Giải pháp bền vững hơn là bake
appearance về texture/material-space hoặc giữ hoàn toàn trong scene 3D, vì khi đó mọi camera cùng
nhìn một thiết kế thay vì sáu thiết kế ngẫu nhiên.

## Chẩn đoán pipeline trước thử nghiệm

### 1. “View-set” chưa thật sự là multi-view generation

Adapter Gemini gọi `generate()` tuần tự sáu lần nhưng mỗi lần là một interaction độc lập. Không có
shared latent, style image, previous interaction hay texture chung. Vì vậy VIEW-01 và VIEW-02 có
thể giữ massing nhưng thay đổi palette, facade motif, độ chi tiết và môi trường.

Tài liệu Gemini chính thức khuyến nghị đưa ảnh đã sinh trước đó vào các prompt sau để giữ tính nhất
quán, đồng thời Gemini 3.1 Flash Image hỗ trợ nhiều ảnh tham chiếu. Đây là cơ sở của thử nghiệm
style-anchor, không phải chỉ là prompt tuning:
[Gemini image generation](https://ai.google.dev/gemini-api/docs/image-generation).

### 2. Camera cũ không đúng vai trò

- VIEW-01/02 có cao độ, lens và bố cục tổng thể quá gần nhau về cảm nhận.
- VIEW-06 ở cao độ khoảng 138 m, trong khi yêu cầu là góc nhìn người trong bối cảnh.
- VIEW-04/05 nhìn xuyên qua một khối dài nên bị mái tiền cảnh chiếm diện tích lớn.
- Camera chỉ dùng bounding box tổng, chưa dùng trục dài xưởng và hành lang giữa hai roof assembly.

### 3. Photorealism đang được giao quá nhiều cho AI

Base render cũ dùng nền tối phẳng, vật liệu màu đồng nhất, cây và môi trường chủ yếu phải được AI
suy diễn. Khi tín hiệu 3D không đủ, mô hình có xu hướng tạo nền sạch kiểu CGI, cây lặp, đường không
có hạt vật liệu và tự phát minh facade/context. Đây là nguyên nhân ảnh có vẻ “đẹp” nhưng chưa giống
ảnh chụp công trình vận hành.

### 4. QA mới kiểm tra artifact, chưa kiểm tra chất lượng hình ảnh

`technical_qa.json` hiện bắt tốt file thiếu, provenance và cấu trúc view-set, nhưng các gate geometry,
semantic, cross-view appearance và aesthetic vẫn trả `evidence_not_available`. Do đó “0 technical
errors” chưa đồng nghĩa với bộ ảnh đạt yêu cầu thị giác.

## Bài học từ các phương pháp đã công bố

- [ControlNet](https://arxiv.org/abs/2302.05543) chứng minh depth, edge và segmentation có thể điều
  khiển diffusion bằng ràng buộc không gian. Hướng phù hợp với conditioning pack hiện tại, nhưng
  bản thân ControlNet từng view không giải quyết hoàn toàn cross-view consistency.
- [IP-Adapter](https://arxiv.org/abs/2308.06721) tách image prompt khỏi text prompt, phù hợp để khóa
  material/style từ một ảnh hero trong khi vẫn kết hợp spatial control.
- [MVDiffusion](https://arxiv.org/abs/2307.01097) sinh các view đồng thời và trao đổi thông tin qua
  correspondence-aware attention. Kết luận quan trọng: muốn nhất quán thật, các view phải chia sẻ
  thông tin trong quá trình sinh, không chỉ dùng cùng câu prompt.
- [TEXTure](https://arxiv.org/abs/2302.01721) và
  [Text2Tex](https://arxiv.org/abs/2303.11396) chiếu kết quả về texture của mesh, dùng mask trạng thái
  và chọn next-best-view để hạn chế đường nối và tích lũy sai khác. Đây là hướng gần nhất với yêu
  cầu “một thiết kế, nhiều camera” của dự án.
- Blender khuyến nghị scene-linear workflow; AgX có dải động 16,5 stops và highlight roll-off tự
  nhiên hơn cho photorealism:
  [Blender Color Management](https://docs.blender.org/manual/en/4.5/render/color_management.html).

## Ba phương án đã/đang kiểm nghiệm

| Phương án | Đúng hình học | Đồng nhất | Chân thực | Nhận định |
|---|---:|---:|---:|---|
| A. Sáu yêu cầu Gemini độc lập | Trung bình | Thấp | Trung bình–cao từng ảnh | Loại khỏi production; chính là lỗi hiện tại |
| B. VIEW-03 style anchor + 5 view được khóa | Trung bình–khá | Khá | Khá | Dùng được làm cầu nối ngắn hạn, phải có QA |
| C. 3D/PBR chung + neutral semantic + style anchor + AI masked | Cao | Khá–cao | Khá–cao | Phương án triển khai ngay được chọn |
| D. Texture-space/multi-view diffusion | Rất cao | Rất cao | Cao | Hướng R&D production dài hạn, cần GPU/model riêng |

Phương án “generate nguyên contact sheet sáu ô trong một lần” không được chọn: style có thể đồng
nhất hơn nhưng độ phân giải từng view thấp, mô hình dễ trộn ranh giới các ô và khó kiểm chứng camera,
depth, instance correspondence.

### Kết quả trên model mẫu

- Baseline độc lập trước đó giữ được tỷ lệ lớn nhưng VIEW-01/02 thay đổi facade style và semantic
  color có thể rò vào vật liệu.
- Style-anchor v8 làm sáu ảnh gần nhau rõ rệt về cladding, glazing, landscape, daylight và mức chi
  tiết. Tuy vậy VIEW-01 còn `0,374%` pixel đỏ bão hòa dù đỏ không thuộc palette.
- Style-anchor + neutral semantic v9 giảm tỷ lệ đỏ trung bình từ `0,062%` xuống `0,001%`; không còn
  mảng đỏ kiến trúc quan sát được. VIEW-03/06 đúng close/human role và sáu ảnh dùng một họ vật liệu.
- v9 vẫn chưa đạt hoàn toàn mức ảnh tham khảo: bề mặt còn sạch, cây còn có nhịp lặp, context xa còn
  nghèo và cảnh vận hành chưa đủ. Kết quả chứng minh khóa style/semantic có tác dụng, đồng thời xác
  nhận phần photorealism tiếp theo phải được đưa vào scene PBR/asset library thay vì tiếp tục kéo
  dài prompt.
- Thử riêng VIEW-03 với `resource/sample_image.png` làm realism reference cho cây dày hơn, asphalt
  có texture và kính chi tiết hơn; đồng thời nó cũng tự tăng diện tích kính, thay facade rhythm và
  thêm tim đường. Vì vậy reference ảnh toàn cảnh **không được chọn làm design/style authority**.
  Production chỉ nên dùng crop/material board đã loại logo, bố cục, motif và camera, hoặc dùng làm
  realism scorer; geometry/Design DNA vẫn là nguồn đúng duy nhất.

Artifact thử nghiệm:

- `camera-v3-realistic/base_viewset_board.jpg`: board hình học/PBR trước AI.
- `camera-v3-realistic/anchor-generated/viewset_board.jpg`: style anchor với semantic màu.
- `camera-v3-realistic/anchor-neutral-generated/viewset_board.jpg`: phương án v9 được chọn.
- `camera-v3-realistic/reference-single/view-03/refined.jpg`: thử nghiệm realism reference một view.

## Camera set v3 sau hai vòng kiểm nghiệm

- **VIEW-01 — overall aerial:** tổng thể chéo từ đầu thứ nhất, đọc được hai roof assembly, sân và
  đường bao.
- **VIEW-02 — reverse/context aerial:** phía đối diện và azimuth khác VIEW-01; ưu tiên quan hệ với
  context, không dùng bố cục đối xứng giả như một bản sao.
- **VIEW-03 — close elevated courtyard hero:** cao độ 14 m, lens 42 mm, nhìn dọc hành lang giữa hai
  xưởng; gần với cách quan sát trong ảnh tham khảo sân logistics.
- **VIEW-04 — low oblique exterior:** góc chéo ở đầu dải xưởng thứ nhất để đọc mái, facade dài,
  khoảng lùi và đường ngoài.
- **VIEW-05 — reverse low oblique exterior:** góc đối ứng ở đầu còn lại, kiểm tra mặt sau/cạnh và
  tính nhất quán vật liệu.
- **VIEW-06 — human-eye courtyard:** cao độ 1,65 m, lens 32 mm, nằm trong hành lang thật giữa hai
  roof assembly; dùng để kiểm tra tỷ lệ cửa, canopy, cây, xe, người và trải nghiệm không gian.

Camera không gắn với tọa độ model mẫu. Planner xác định trục dài theo focus bounds và tìm hành lang
lớn nhất giữa các roof assembly song song.

## Tiêu chuẩn photorealism mục tiêu

### Công trình

- Cladding có module, joint, flashing, ridge cap, gutter, downpipe, plinth và micro-roughness đúng
  tỷ lệ; không dùng noise lớn để giả vật liệu.
- Kính phản xạ bầu trời/cảnh quan có Fresnel hợp lý, không là mảng xanh phát sáng.
- Contact shadow phải tồn tại tại chân tường, canopy, xe và cây; không có vật thể “nổi”.
- Một facade grammar, palette, độ bóng và mức chi tiết được dùng lại ở mọi view.

### Đường và sân

- Hình học đường, bề rộng, bán kính rẽ, cổng và lối cứu hỏa lấy từ canonical scene, không để AI
  thiết kế lại.
- Hạt asphalt/concrete, khe co giãn, curb, rãnh thoát nước, vạch sơn và biến thiên sử dụng được tạo
  bằng PBR/decal deterministic.
- Hao mòn rất nhẹ theo luồng xe; tránh cả hai cực “sạch như mô hình” và “cũ bẩn”.

### Cây xanh và context

- Chỉ scatter cây trong landscape polygon; dùng seed theo model/design revision để sáu view thấy
  cùng một cây tại cùng tọa độ.
- Trộn 3–5 loại cây/bụi phù hợp khí hậu, biến thiên có giới hạn về chiều cao/crown/rotation; không
  lặp cùng một asset theo hàng máy móc.
- Context building phải bắt nguồn từ geometry/mask; render khối pale/translucent và không có facade
  detail. Xa dần có atmospheric haze và giảm tương phản, không tự mọc thêm công trình.

Muốn bối cảnh ngoài ranh dự án vừa giống ảnh chụp vừa **đúng địa điểm**, RVT phải có georeference
hoặc pipeline cần một `ContextPack` tùy chọn gồm footprint/road GIS, orthophoto và cao độ/DEM. Nếu
không có dữ liệu đó, hệ thống chỉ được phép chọn `translucent_massing`/tree belt trung tính. Cho AI
tự dựng ruộng, kênh, đường và nhà xung quanh sẽ tăng độ đẹp nhưng không thể gọi là chính xác.

### Camera và image science

- Dùng cùng sun azimuth/elevation, white balance, exposure family và color transform cho cả bộ.
- Scene-linear + AgX; lens theo full-frame thực tế, không tilt-shift/miniature trừ khi brief yêu cầu.
- Aerial cần atmospheric perspective; ground view cần eye-height, verticals hợp lý và foreground
  không chắn sản phẩm.

## QA bắt buộc trước khi duyệt

1. **Geometry gate:** silhouette/edge distance giữa generated và base; bảo vệ roof ridge, footprint,
   road/landscape boundary bằng mask.
2. **Semantic gate:** segmentation IoU cho building, road, landscape và context; phát hiện mất/thêm
   khối hoặc cây tràn lên đường.
3. **Palette/material gate:** đo Lab/HSV theo projected material region; cấm semantic red/cyan/purple
   nếu không thuộc Design DNA.
4. **Cross-view gate:** dùng correspondence map để so cùng surface qua nhiều view; màu trung vị,
   material embedding và facade rhythm phải nằm trong ngưỡng.
5. **Photorealism gate:** chấm riêng contact shadow, material response, scale entourage, repetition,
   atmospheric depth và CGI artifacts; không gộp với aesthetic preference.
6. **Camera gate:** đủ coverage, occupancy hợp lý, không occlusion lớn, VIEW-03/06 đúng khoảng cách
   và VIEW-06 nằm trong dải eye-height.

Các feature thị giác tổng quát như [DINOv2](https://arxiv.org/abs/2304.07193) có thể hỗ trợ đo
appearance/identity, nhưng không thay thế các mask và correspondence hình học có sẵn của dự án.

## Lộ trình đề xuất

### P0 — áp dụng ngay

- Camera planner v3 theo trục xưởng/hành lang.
- Nishita daylight + scene-linear AgX cho base render.
- Neutral-grayscale semantic input để tránh rò màu annotation.
- Marketing profile sinh VIEW-03 trước và dùng output làm style anchor.
- Bổ sung cross-view palette/edge/semantic QA; fail nếu không có evidence thay vì chỉ `review`.

### P1 — nâng photorealism có kiểm soát

- Asset library có version: PBR metal/concrete/asphalt, curb/drain, 3–5 nhóm vegetation, xe tải/xe
  con/người đúng scale.
- Deterministic scatter từ landscape/parking/loading semantic geometry.
- Decal và surface variation theo material-space, không sinh ngẫu nhiên từng ảnh.
- Render Cycles/denoising cho profile final; EEVEE chỉ preview.

### P2 — multi-view production

- Bake facade/material identity vào UV/triplanar texture atlas hoặc material graph dùng chung.
- Thử ControlNet depth/edge + IP-Adapter cho local masked refinement, sau đó khảo sát
  TEXTure/Text2Tex/texture-space diffusion trên GPU riêng.
- Dataset eval gồm nhiều model LOD100 khác hình dạng; tuyệt đối không tối ưu chỉ cho model mẫu.

## Tiêu chí chấp nhận

- Không đổi footprint, số khối, ridge direction, đường, cổng và landscape polygon.
- Không có hai view dùng facade language/palette khác nhau.
- Sáu camera có vai trò khác nhau; VIEW-03 là close elevated, VIEW-06 là human-eye.
- Không có semantic-color leakage hoặc material ngoài palette.
- Không có cây/xe che phần thiết kế chính; context không cạnh tranh thị giác.
- Human review đánh giá ảnh giống ảnh chụp công nghiệp thuyết phục, đồng thời các gate định lượng đều
  có evidence và đạt ngưỡng.
