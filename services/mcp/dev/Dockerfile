# Development stubs image (compose profile `stubs`). Never deployed: it contains the stubs and fixtures.
FROM python:3.13.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13.13-slim
RUN groupadd -g 10001 app && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin app
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY dev/frontdesk_stubs /app/dev/frontdesk_stubs
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/dev PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8200 8300
CMD ["python", "-m", "frontdesk_stubs", "--host", "0.0.0.0"]
