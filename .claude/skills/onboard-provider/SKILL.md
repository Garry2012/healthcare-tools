---
name: onboard-provider
description: Onboard a new hospital or hotel (provider) as its own deployment. Use when asked to add, configure or register a new provider.
disable-model-invocation: true
---
# Onboard provider: $ARGUMENTS

Follow `docs/handover/ONBOARDING.md` exactly. Claude's part:

1. Create `deploy/providers/<provider>.env` from the closest demo file. Ask the user for
   every value you cannot know (timezone, phone format, languages, identity policy). Never
   invent the provider's policy values; leave the demo defaults and list them as open.
2. Validate: read the file with a line reader (not `source`), export, and run
   `cd services/api && uv run frontdesk-api check-config`. It must exit 0.
3. Add the file to `test_committed_provider_files_are_valid` and run the unit tests.
4. Never put secrets in the provider file, never load the synthetic seed into a real
   provider's database, and never run `register.py` without `--dry-run` unless the user asks.
