# Latency results (1 October 2026)

**Status: no real voice-path or live owner-service measurement exists yet.** The tool round trip was
measured against the in-process development stubs (labelled *stub*) and against Manoj's public *contract
mock* in Central India from a developer laptop outside Azure (labelled *mock*). Manoj's live backend
(`healthcare-api`) is deployed but rejects unregistered clients, so no authenticated live timing was
possible. Stub and mock timings are **not production timings**; they prove the adapter's own overhead and
the composition shape. Caller-audio latency (end of speech → first useful audible result) was not
measured: no voice-platform access. Updated after the architect's review: AR-06 (budget-derived
deadlines) and AR-07 (benchmark counts only verified successful owner operations).

## Method and commands

`services/mcp/dev/bench.py` starts the adapter (uvicorn, streamable HTTP, stateless) on a local TCP
port, warms one session, then for each scenario opens an MCP client session per sample (the way a
voice agent's per-call session behaves) and times `call_tool` end to end at the client. A sample is
a failure when the result is a tool error or a `COULD_NOT_CHECK`/`ROUTING_UNAVAILABLE` outcome;
failures are reported separately and excluded from percentiles (never silently). Raw JSON is in
[evidence/](evidence/) (`bench-stubs-*-20261001.json` before the fix pass, `*-after-fixes-*` after,
`bench-azure-contract-mock-20261001.json` for the real network run).

```bash
cd services/mcp
uv run python dev/bench.py --samples 50                       # in-process stubs, concurrency 1
uv run python dev/bench.py --samples 50 --concurrency 5       # in-process stubs, concurrency 5
BENCH_OPS_BASE_URL=https://healthcare-contract-mock.icytree-6543aaa9.centralindia.azurecontainerapps.io \
  BENCH_OPS_CLIENT_ID=x BENCH_OPS_CLIENT_SECRET=y BENCH_READ_DEADLINE=8 \
  uv run python dev/bench.py --samples 30                     # real network to the Azure contract mock
```

Boundary measured: **agent (client) → MCP adapter (local TCP) → owner service(s) → result at the
client**. Not included: ContextForge, the LLM, STT/TTS, media. The per-sample MCP session handshake
(initialize + tools/list is not included; initialize is) adds about 20–30 ms locally.

## Results

### A. In-process stubs (ASGI, no network) — adapter overhead only

Warm token and pool; fixed clock (Thu 1 Oct 2026 10:00 IST); macOS laptop; 50 samples per scenario.
Two runs: before and after the review fix pass (the latency review found ~16 ms/call of SDK output
re-validation and serial routing→reads; both fixed).

| Scenario (owner calls) | before c=1 p50 / p95 | **after c=1 p50 / p95 / p99** | before c=5 p50 / p95 | **after c=5 p50 / p95 / p99** | failures |
|---|---:|---:|---:|---:|---:|
| availability, known doctorId (route ∥ profile ∥ board) | 42 / 56 ms | **27 / 31 / 61** | 203 / 420 | **95 / 133 / 141** | 0 |
| availability, name search (route ∥ search; then profile ∥ board) | 43 / 48 | **28 / 30 / 32** | 178 / 221 | **98 / 137 / 158** | 0 |
| availability, ambiguous name (route ∥ search → clarification) | 42 / 69 | **27 / 33 / 38** | 172 / 218 | **97 / 159 / 198** | 0 |
| availability, department (route ∥ departments ∥ doctors ∥ board) | 43 / 50 | **28 / 31 / 73** | 186 / 229 | **101 / 169 / 197** | 0 |
| search_knowledge (answer) | 15 / 19 | **12 / 17 / 74** | 65 / 189 | **65 / 103 / 109** | 0 |
| manage_booking LIST (find by trusted mobile) | 26 / 37 | **17 / 24 / 31** | 111 / 136 | **61 / 81 / 82** | 0 |

Reading: with zero network cost, one availability invocation now costs about 27 ms at the client,
of which roughly 15–20 ms is the per-sample MCP session initialize plus client-side schema checking
(the bench opens a session per sample, as a per-call voice agent would) and the rest is the adapter's
composition (three to four stub exchanges in one parallel stage). At concurrency 5 on one laptop
process (adapter and both stubs share one event loop) p50 is ~95–100 ms; this is CPU contention of
the test rig, not a network effect. Caveats from the latency review (deferred, see REVIEW-REPORT):
the client runs in the same process as the server, and session set-up is not timed separately.

### B. Real network: laptop → Azure contract mock (Central India), knowledge from the in-process stub

Prism mock, static example responses, example bearer; 30 samples; concurrency 1; warm token after the
first call. The laptop's TLS handshake to Central India alone measured 0.59 s and a single request
0.7–1.0 s (curl `time_total` to the mock's `/departments` and to the real backend's `/health`), so
these figures are dominated by the laptop's distance, not by the adapter.

| Scenario | first call (cold TLS/token) | p50 | p95 | p99 | failures |
|---|---:|---:|---:|---:|---:|
| availability, known doctorId (profile ∥ board: one network stage) | 2200 ms | 361 | 469 | 2200 | 0 |
| availability, name search (search; then profile ∥ board: two stages) | 1042 | 678 | 811 | 1042 | 0 |
| availability, ambiguous (search only, 1 stage) | 704 | 704 | 808 | 812 | 0 |
| availability, department (departments cached; mock has no matching dept → clarification, no board) | 396 | 40 | 44 | 396 | 0 |
| search_knowledge (stub) | 19 | 15 | 21 | 22 | 0 |
| manage_booking LIST (one GET) | 397 | 345 | 406 | 429 | 0 |

An earlier 20-sample run against the same mock showed 6/20 failures (`COULD_NOT_CHECK`) and a 3 s
p99 on the known-doctor scenario while the mock was waking up; the mock is a cold-starting Container
App. Both runs are in `evidence/`.

Reading: the composition shape is confirmed on a real network: one parallel stage ≈ 1 RTT
(~300–350 ms from this laptop), two stages ≈ 2 RTT (~680 ms). Everything above the stub figure is
network and TLS from the laptop; from the intended region the same shape should cost about
2 × in-region RTT plus the owner services' own processing time.

### C. Direct probes of Manoj's deployed backend (`healthcare-api`, Central India), from the laptop

Unauthenticated (no machine credentials available): `POST /api/v1/auth/token` returned 401 in
0.70–1.02 s over 12 samples; `GET /health` 200 in 0.69–1.01 s; one sample broke down as DNS 3 ms,
TCP connect 292 ms, TLS 592 ms, first byte 884 ms. This is the laptop's path, not the gateway's.

### A2. Stubs, after the architect's AR-07 correction — verified outcomes only

The benchmark now sends `X-Caller-Verification`, declares the intended outcome per scenario and, in stub mode,
checks that the intended owner operation was observed on the wire; anything else is counted as rejected, never
as a success timing. 50 samples, c=1, warm token, in-process stubs (`evidence/bench-stubs-c1-verified-outcomes-20261001.json`).

| Scenario | verified ok | p50 ms | p95 | p99 | rejected/failed |
|---|---:|---:|---:|---:|---:|
| availability_known_doctor | 50/50 | 27.5 | 38.1 | 59.9 | 0 |
| availability_name_search | 50/50 | 27.5 | 31.8 | 37.0 | 0 |
| availability_ambiguous | 50/50 | 27.1 | 36.6 | 44.2 | 0 |
| availability_department | 50/50 | 28.0 | 45.4 | 76.2 | 0 |
| knowledge_answer | 50/50 | 14.4 | 17.8 | 22.1 | 0 |
| booking_list | 50/50 | 19.3 | 23.8 | 48.5 | 0 |

The earlier stub figures above were produced before this correction; their booking LIST samples were
IDENTITY_UNAVAILABLE refusals (no owner call), so those LIST timings are withdrawn. Availability and knowledge
samples did perform their owner calls (the recording transport confirms the same paths now).

### D. Deadline budget after the architect's AR-06 correction

Defaults are now derived: tool deadline = `VOICE_RESPONSE_BUDGET_SECONDS` (1.0) − `RESERVED_STAGE_SECONDS`
(0.65) − `GATEWAY_OVERHEAD_SECONDS` (0.05) = **0.30 s** for every in-call tool, reads and confirmed writes alike
(the earlier 0.6 s write allowance exceeded the budget together with the reserved stages); per-exchange cap
0.30 s; summaries 8 s (after the call). Overrides above the share need `ALLOW_BUDGET_OVERRIDES=true`. Slow and degraded paths are exercised with injected delays (routing/directory 0.3 s each,
slow write, dribbling TCP server) and return COULD_NOT_CHECK / UNCERTAIN inside the budget. Whether 0.30 s is
enough for the real in-region path is exactly what the live measurement must show (a short deadline proves only
that a slow turn fails fast, never that successful responses meet the target); the laptop → Azure numbers
in section B (one stage ≈ 350 ms) say a laptop cannot meet it and a same-region deployment is required.
Fast failures are reported separately from successful-response percentiles in every run above.

### A3. Stubs, after the re-review bench corrections (call-id attribution, CREATE scenario, over-budget count)

30 samples, concurrency 5, in-process stubs, routing + owner calls verified per sample
(`evidence/bench-stubs-c5-rereview-20261001.json`):

| Scenario | ok | over 300 ms | p50 ms | p95 ms |
|---|---:|---:|---:|---:|
| availability_known_doctor | 30/30 | 0 | 114 | 171 |
| availability_name_search | 30/30 | 0 | 97 | 139 |
| availability_ambiguous | 30/30 | 0 | 104 | 165 |
| availability_department | 30/30 | 0 | 96 | 138 |
| knowledge_answer | 30/30 | 0 | 57 | 108 |
| booking_list | 30/30 | 0 | 63 | 85 |
| booking_create | 30/30 | 0 | 67 | 89 |

Stub timings only; the per-exchange caps now differ by path (in-call 0.30 s; summaries 8 s; token refresh 5 s).

## Comparison with the targets

| Target (TARGET-STATE.md) | Measured | Verdict |
|---|---|---|
| Tool round trip ≈ 250 ms (70 ms gateway/MCP/transport + 180 ms downstream) | Adapter overhead ≈ 40 ms incl. session init (stubs); real in-region downstream not measured | **Not demonstrated.** Adapter share is inside its 70 ms allocation; downstream share unknown |
| Caller response p95 ≤ 1,000 ms | Not measured (no voice platform access) | **Not demonstrated** |

## Bottlenecks and what decides the budget

1. **Owner-service RTT × stages.** The availability critical path is two dependent stages when the
   doctor must be searched (search → profile ∥ board) and one when `doctorId` is known; the routing
   call overlaps stage one. From the intended region each stage ≈ one RTT plus Manoj's processing;
   the knowledge routing call runs in parallel with stage one and is only on the critical path if it
   is slower than the directory read. Measure both owners from the MCP region before cutover.
2. **Session handshake per call.** A voice agent that opens a new MCP session per tool call pays
   ~15–20 ms (local) plus a gateway hop; keep the session open for the call.
3. **Cold starts.** The first call after a cold token/TLS costs 1–2 s on the mock from the laptop;
   Container Apps cold starts of the owner services would land in the caller's first turn. Keep
   min replicas ≥ 1 on all three services and warm the token at start-up (the adapter refreshes
   before expiry once warm).
4. **Not in MCP's control:** STT endpointing, both LLM stages and TTS, which the plan allocates
   ~650 ms of the 1,000 ms to.

## What would make this real

- Machine credentials for `healthcare-api` (Manoj) and Shobhit's host: rerun
  `BENCH_OPS_BASE_URL=https://healthcare-api…/api/v1 BENCH_KNOWLEDGE_BASE_URL=… uv run python dev/bench.py`
  from an Azure Container App or VM in Central India (not a laptop) and record cold/warm, c=1/5/20.
- A LiveKit test call with the platform forwarding the trusted headers; measure end-of-speech →
  first useful audio at the caller with LiveKit's turn timings, EN/KN/HI, including a clarification
  turn and a UNKNOWN-callback turn; count timeouts and fillers separately.
