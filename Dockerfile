FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    V365_ENV=production \
    V365_ARTIFACT_DIR=/var/lib/v365/artifacts

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 v365 \
    && mkdir -p /var/lib/v365/artifacts \
    && chown -R v365:v365 /var/lib/v365

USER v365
EXPOSE 8000

CMD ["uvicorn", "v365_archviz.api:app", "--host", "0.0.0.0", "--port", "8000"]

