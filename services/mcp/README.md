# frontdesk-mcp

FastMCP 2.14.7 adapter exposing three tools over streamable HTTP at `/mcp/` (stateless):

| Tool | REST |
|---|---|
| `find_availability` | `POST /agent/availability-search` |
| `search_knowledge` | `POST /agent/knowledge-search` |
| `manage_booking(action=BOOK\|LIST\|CANCEL\|RESCHEDULE)` | `POST /agent/bookings`, `GET /agent/bookings`, `POST …/cancel`, `POST …/reschedule` |

`X-Call-Id` and `X-Caller-Number` are read from the incoming MCP HTTP request, forwarded by
ContextForge. They are never tool parameters. `Idempotency-Key` is
`sha256(callId|action|normalised customer name|target)`. The tool result is the REST body
unchanged. Transport failures, 429 and 5xx return
`{"outcome": "COULD_NOT_CHECK" | "COULD_NOT_RECORD", "retryAfterSeconds": n}`.

```bash
uv sync && uv run pytest tests      # set MCP_E2E_API_URL / MCP_E2E_API_TOKEN for the end-to-end test
uv run frontdesk-mcp serve
```

The words the model reads (server instructions, tool and parameter descriptions) come from
the domain pack `src/frontdesk_mcp/packs/$DOMAIN_PACK.json`. The tool schema is the same in
every domain.
