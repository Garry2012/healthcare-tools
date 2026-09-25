# healthcare-api

FastAPI implementation of `docs/frontdesk-api/openapi.yaml`. See `docs/handover/README-API.md`.

```bash
uv sync
uv run pytest tests/unit tests/contract          # hermetic
uv run healthcare-api migrate | serve | seed [--reset] | maintenance
```

`src/healthcare_api/domain/` is pure: the availability engine, resolver, dates, identity and
ids. It has no I/O, and the golden unit tests exercise it directly. `services/` holds the
application logic over SQLAlchemy; `routers/` has one module per OpenAPI tag.
