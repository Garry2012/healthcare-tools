# Opus review: booking F-1 fix (b1ce587..1132666), 6 October 2026

**Scope:**
- `49da15c`: docs only (my B-2/M-1 review, verified identical);
- `1132666`: the F-1 fix (`booking.py`, `test_booking.py`, `DECISIONS.md`, hand-back).

Checked against `.context/astra-prompt-booking-f1.md`. Review only: no code, commit, push, merge or deployment.

## Verdict

**F-1 is fixed correctly and the boolean flag is gone. Merge-ready.**

- One nit: a narrowing for the `appointmentId` path parameter, low likelihood.
- One informational note.

**Counts:** Critical 0 · Important 0 · Minor 0 · Nit 1 · Info 1.

## Verification

| Check | Result |
|---|---|
| `make test-fast` at `1132666` | **599 passed**, 11 deselected |
| `make -s schema` vs snapshot | **identical** |
| Files changed | 4 (≤10); no change to schema, packs, `ops_client.py`, request bodies or operation keys |
| F-1 reproduction, re-run | `_failure(Rejected(400, …, ("mobile", "from")), "LIST")` → `["fromDate"]` (was `["patientMobile"]`) ✓ |

## Requirement check

| Prompt requirement | Code | Verdict |
|---|---|---|
| Translate with the failing action's mapping | `booking.py:157` uses `_REJECTION_FIELDS[action]`; no flattening across actions | ✓ |
| LIST: `from`/`to`/`status` translated, owner `mobile` dropped | `_OWNER_FIELDS["LIST"]` (`booking.py:62`); `mobile` is absent, so it is dropped | ✓ |
| RESCHEDULE's internal lookup uses RESCHEDULE's mapping | `_reschedule_gate` passes `request.action` (`booking.py:310`) | ✓ |
| One source of truth, no parallel list | `_REJECTION_FIELDS` is **derived** from `_OWNER_FIELDS` (`booking.py:68`), built once at module load. `_write_body` still reads `_OWNER_FIELDS[action]` only for write actions | ✓ (see I-1) |
| Replace the boolean `write` with the action | `_failure(self, exc, action)` derives `write = action != "LIST"` (`booking.py:148`). All five call sites pass the action (`:189, 224, 239, 298, 310`) | ✓ Flag removed |
| No per-call rebuild | `names = _REJECTION_FIELDS[action]` is a lookup | ✓ |
| Intersection with `model_fields` | Removed: the per-action map now defines what is actionable. Canonical tool names stay accepted per action, so the existing M-1 test (duplicates plus `patientMobile`) is preserved unchanged | ✓ |
| Read/write outcomes preserved | Existing `COULD_NOT_CHECK` / `COULD_NOT_RECORD` / `UNCERTAIN` tests green | ✓ |
| Tests through real paths | `test_appointment_lookup_rejection_uses_the_requested_action` (LIST and RESCHEDULE lookup via an owner 400 on `GET /appointments`; asserts query params, no POST, no owner text echoed); `test_schedule_rejection_uses_the_originating_action` (CREATE and RESCHEDULE via an owner 400 on `GET /doctors/{id}`) | ✓ |

## Findings

### N-1 (nit): an owner rejection naming the `appointmentId` path parameter is now dropped

**Reproduction:**
```python
svc._failure(Rejected(400, "VALIDATION_FAILED", ("appointmentId",)), "RESCHEDULE").fields  # → []
```

- At `b1ce587` this returned `["appointmentId"]`, because it was a `BookingRequest` field.
- Now CANCEL/RESCHEDULE translate only their **body** fields, and `appointmentId` is a path parameter in the contract (`components.parameters.AppointmentId`, `in: path`).

**Likelihood is very low:**
- the id is pre-validated locally (`_ID`, and `InvalidIdentifier` → local `INVALID_REQUEST` with `fields: ["appointmentId"]`);
- an absent id is the owner's neutral 404 (`NOT_FOUND`).

**If it is ever wanted:** add path parameters to the rejection map only, never to `_OWNER_FIELDS`, because adding `appointmentId` there would put it into the write body. Accepting the current behaviour is reasonable.

### I-1 (info): two places name LIST's owner query fields

`_OWNER_FIELDS["LIST"]` (`booking.py:62`) and `ops_client.find_appointments` (`ops_client.py:385-391`) both spell `from`, `to` and `status`. The prompt allowed this option. Drift risk is small because the contract is pinned and its changes are reviewed. No change needed.

## Code quality

- The flag parameter is removed rather than a parameter added.
- The translation is derived from the existing mapping and built once.
- No duplicated logic, special cases or dead code. The hand-back reports a vulture run on `booking.py` with no findings.
- `_schedule_gate` gains an `action` argument only to forward it to `_failure`. That is acceptable for now; if more request context is needed later, pass the request instead of growing the argument list.

## Recommendation

**Merge-ready.** N-1 can be accepted. Deployment still requires separate approval.
