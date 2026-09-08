# V365 ArchViz

Geometry-first pipeline tạo bộ ảnh diễn họa đa góc nhìn nhất quán từ Revit LOD100.

## Trạng thái

Foundation milestone hiện có:

- domain contracts cho Canonical Scene, Design DNA và View Set;
- validation cho IDs, references, surface frames và tham số façade;
- provider ports tách Autodesk extraction khỏi business workflow;
- RVT 2026 envelope inspector, SHA-256 version pinning và preview extraction;
- content-addressed artifact manifest;
- FastAPI control-plane skeleton và capability discovery;
- CLI, container không chạy bằng root, JSON Schema và automated tests.

Geometry extraction qua APS Model Derivative → IFC là milestone tiếp theo. Local RVT
inspector chỉ đọc metadata; nó không giả vờ parse proprietary Revit geometry.

## Thiết lập

Yêu cầu Python 3.10+.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

Không commit `.env`. Các API response và manifest không bao giờ chứa credentials hoặc
đường dẫn máy của tác giả RVT.

## Chạy kiểm nghiệm sample

```bash
v365-archviz inspect resource/model_lod100_sample.rvt
```

Sau khi cấu hình APS credentials:

```bash
v365-archviz extract-ifc resource/model_lod100_sample.rvt
v365-archviz canonicalize-ifc \
  resource/model_lod100_sample.rvt \
  .artifacts/extractions/480b5e6346f2877b/model_lod100_sample.ifc
```

Artifacts được ghi vào `.artifacts/inspections/<sha-prefix>/`:

```text
manifest.json
preview.png
```

Đổi file RVT sẽ đổi SHA và tạo revision artifact mới. Chạy lại cùng file là idempotent.

## API

```bash
uvicorn v365_archviz.api:app --reload
```

Các endpoint foundation:

- `GET /healthz`
- `GET /v1/system/capabilities`
- OpenAPI UI: `/docs`

## Quality gates

```bash
pytest
ruff check .
mypy
```

JSON Schemas được sinh từ Pydantic contracts:

```bash
python scripts/export_schemas.py
```

## Cấu trúc

```text
src/v365_archviz/
├── application/       # use cases, không phụ thuộc transport
├── domain/            # immutable validated contracts
├── providers/         # APS/Gemini/local adapter boundaries
├── api.py             # HTTP control plane
├── cli.py             # developer/worker entrypoint
├── config.py          # environment-backed settings
└── errors.py          # typed boundary-safe failures
```

Tài liệu:

- [Requirements](resource/V365_LOD100_MultiView_ArchViz_REQUIREMENTS.md)
- [Feasibility report](resource/V365_LOD100_MultiView_ArchViz_FEASIBILITY_REPORT.md)

## Nguyên tắc bất biến

Mọi thứ phải giống nhau giữa các góc nhìn phải tồn tại dưới dạng 3D/design entity
deterministic bên ngoài image generator. Gemini chỉ là provider refinement, không phải
geometry source of truth.
