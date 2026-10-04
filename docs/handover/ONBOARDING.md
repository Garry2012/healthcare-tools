# Onboarding a hospital: a new rollout

A hospital is a **rollout**: one deployment of the adapter with that hospital's tenant identity and
its owner-service endpoints. Onboarding changes no code.

1. **Tenant settings (non-secret).** `rollouts/<id>/rollout.env` with `PROVIDER_ID`, `DOMAIN_PACK=healthcare`,
   `TENANT_TIMEZONE` (IANA), `TENANT_COUNTRY_CALLING_CODE` (digits) and `TENANT_SUPPORTED_LANGUAGES`
   (e.g. `en,kn,hi`). A real hospital's rollout lives in a private repository; only `demo-*` is committed.
2. **Owner services.** The hospital's operational API base URL (Manoj's deployment, including `/api/v1`
   when it serves there) and knowledge service base URL (Shobhit's), both https. Machine credentials
   are registered by each owner with the scopes the adapter needs (`appointments.write`, `calls.write`)
   and stored in Key Vault by `deploy/azure/deploy.sh` on first run; never in files.
3. **Verification policy.** Agree with Manoj and the voice platform which `X-Caller-Verification`
   assertions authorise appointment lookups/changes; set `ACCEPTED_CALLER_VERIFICATION` accordingly
   (default `SIP_CALLER_ID`).
4. **Deploy and register.** `deploy/azure/deploy.sh rollouts/<id> --profile live` then `deploy/contextforge/register.py`
   (`AZURE.md`, `CONTEXTFORGE.md`). The smoke must pass against the owners' designated test tenant
   before the hospital's own.
5. **Voice platform.** The platform forwards trusted identity/operation/start-time headers. All four tools, including
   LLM-called `record_call_summary`, share gateway authentication (`VOICE-TEAM.md`).

Directory data, schedules, approved answers and routing rules are the owners': the adapter reads
them through their contracts and holds none of them.
