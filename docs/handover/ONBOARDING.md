# Onboarding a hospital: a new rollout

A hospital is a **rollout**: one deployment of the adapter with that hospital's tenant identity and
its owner-service endpoints. Onboarding changes no code.

1. **Tenant settings (non-secret).** `rollouts/<id>/rollout.env` with `PROVIDER_ID`, `DOMAIN_PACK=healthcare`,
   `TENANT_TIMEZONE` (IANA), `TENANT_COUNTRY_CALLING_CODE` (digits) and `TENANT_SUPPORTED_LANGUAGES`
   (e.g. `en,kn,hi`). A real hospital's rollout lives in a private repository; only `demo-*` is committed.
2. **Operational service.** The hospital's HTTPS operational API base URL (Manoj's deployment, including
   `/api/v1` when it serves there). Manoj registers machine credentials with the scopes the adapter
   needs (`appointments.write`, `calls.write`)
   and stored in Key Vault by `deploy/azure/deploy.sh` on first run; never in files.
3. **Verification policy.** Agree with Manoj and the voice platform which `X-Caller-Verification`
   assertions permit the verified default booking mobile when patientMobile is absent or blank; set
   `ACCEPTED_CALLER_VERIFICATION` accordingly (default `SIP_CALLER_ID`). Explicit valid booking mobiles
   do not require caller verification. The voice team owns name checking and family selection before disclosure.
4. **Deploy and register.** `deploy/azure/deploy.sh rollouts/<id> --profile live` then `deploy/contextforge/register.py`
   (`AZURE.md`, `CONTEXTFORGE.md`). The smoke must pass against the owners' designated test tenant
   before the hospital's own.
5. **Voice platform.** The platform forwards trusted identity/operation/start-time headers. All three tools, including
   LLM-called `record_call_summary`, share gateway authentication (`VOICE-TEAM.md`).

Directory and schedule facts are Manoj's: this adapter reads his public contract and owns no data.
The voice team configures Stratum separately in ContextForge for knowledge, symptoms and emergencies.
Before deployment, Rajeev's team validates these journeys and transfers (gate 8). Before live traffic,
refresh our three-tool registration and the voice cache and verify discovery (gate 9); see PLAN.md.
This repository does not modify Stratum's registration or supply its credentials.
