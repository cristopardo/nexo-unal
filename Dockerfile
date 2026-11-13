FROM python:3.12-slim
WORKDIR /srv/nexo
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080 SQLITE_PATH=/tmp/nexo.sqlite3
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY knowledge ./knowledge
COPY web ./web
RUN useradd --uid 10001 --create-home nexo
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --no-access-log"]
