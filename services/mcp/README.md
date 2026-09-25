# healthcare-mcp

FastMCP 2.14.7 adapter exposing two tools over streamable HTTP at `/mcp/` (stateless):

| Tool | REST |
|---|---|
| `find_availability` | `POST /agent/availability-search` |
| `manage_appointment(action=BOOK\|LIST\|CANCEL\|RESCHEDULE)` | `POST /agent/appointments`, `GET /agent/appointments`, `POST …/cancel`, `POST …/reschedule` |

`X-Call-Id` and `X-Caller-Number` are read from the incoming MCP HTTP request, forwarded by
ContextForge. They are never tool parameters. `Idempotency-Key` is
`sha256(callId|action|normalised patient name|target)`. The tool result is the REST body
unchanged. Transport failures, 429 and 5xx return
`{"outcome": "COULD_NOT_CHECK" | "COULD_NOT_RECORD", "retryAfterSeconds": n}`.

```bash
uv sync && uv run pytest tests      # set MCP_E2E_API_URL / MCP_E2E_API_TOKEN for the end-to-end test
uv run healthcare-mcp serve
```
