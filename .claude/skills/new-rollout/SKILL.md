---
name: new-rollout
description: Create, validate and deploy a rollout (a new hospital, hotel or other provider) of an existing domain pack, as that provider's differences only. Use when asked to onboard, add, configure or deploy a new provider or rollout.
disable-model-invocation: true
---
# New rollout: $ARGUMENTS

A rollout is one provider's instance of one domain: files only (`docs/handover/ONBOARDING.md`,
`docs/architecture/TARGET.md` A10). You create **only** what differs for this provider. Never edit
the core, a domain pack or another rollout to make this one work; if it seems necessary, stop and
say which layer is missing something (a language module is the one expected exception: step 3).

## 1. Ask (one message, then wait)

Ask for what you cannot know, grouped, marking what is required:
- **Identity (required):** provider id (lowercase, `-`), domain (list `services/api/src/frontdesk_api/packs/`),
  timezone, country calling code, national phone format, currency, languages callers use.
- **Where the files live:** a real provider's rollout goes in a private repository or folder
  outside this one (their doctors, schedules and numbers are theirs); only `demo-*` rollouts go in
  `rollouts/`.
- **Departments / services, and the people or resources in each:** names as callers say them, in
  each language; weekly sessions (days, start, end, capacity or slot length); a spreadsheet is fine.
- **Transfers:** the desk and emergency numbers or queues for each destination the domain uses
  (`transfer_destinations` in the pack).
- **Approved answers:** hours, parking, payment, directions, reports… with the exact approved wording
  in each language.
- **Policy (default is the cautious choice; only if the provider signed off something else):**
  disclosure (P1–P4 in `docs/handover/OPEN-QUESTIONS.md`), cancel on a spoken number.
- **Differences from the domain:** any symptom the provider routes elsewhere, a department the domain
  doesn't have, local names for doctors. Anything else that differs from the domain's defaults.
- **Deployment:** Azure region and sizes if not the defaults (`azure.env`), or where else it runs.

Never invent a value you were not given. Clinical words, prices, numbers, policies and approved
answers come from the provider. For anything missing, leave it out or mark the row
`data_confirmed: false`, and list it as open in your summary.

## 2. Write the files

Start from the demo of the same domain (`rollouts/demo-hospital` for healthcare), in the target
directory:
- `rollout.env`: the seven identity fields, then **only** settings that differ. Run validate and
  delete any line it shows as equal to the default (`test_rollout_files_write_only_differences`
  enforces this for committed rollouts).
- `data.yaml`: categories with the domain's **codes** (read `CATEGORIES` in the pack), resources and
  sessions (times in quotes), `terms` only for what the baseline lacks or re-points, `knowledge`.
- `dialogues.yaml`: for every language, lines for danger signs (`TRANSFER_EMERGENCY`), each
  department, a doctor by name, the two-same-surname case if there is one, and each approved answer.
- `azure.env` only if the deployment differs from the defaults in `deploy/azure/deploy.sh`.

## 3. A language with no module

If `rollout validate` says `no language module for xx`, that is core work, done once for every
rollout: `ONBOARDING.md` step 1b. Then the domain's baseline words in that language, reviewed by
the domain's owners, go in the pack. Do it as a separate change, with its tests, before this
rollout.

## 4. Validate, then prove it locally

```bash
cd services/api && uv run frontdesk-api rollout validate <dir>     # must print "problems": []
```
Fix every problem in the rollout's own files. Read every note back to the user.
For a directory under `rollouts/`, run `./scripts/test.sh` too: it validates every rollout.
A local run: `PROVIDER_ID=<id> make up && make rollout-apply` (demo: `make seed-reset`).

## 5. Deploy (only when asked)

```bash
deploy/azure/deploy.sh <dir> --dry-run      # show the user what would be created
deploy/azure/deploy.sh <dir>                # only after the user says so
```
Then register the gateway (`ONBOARDING.md` step 4, `register.py --dry-run` first) and run the
checks in `AZURE.md` §8. Never `--seed-demo` a real provider (the script refuses it too), never put
secrets in the rollout's files, and never run `register.py` without `--dry-run` unless the user asks.

## 6. Report

What was created, the effective settings that came from the rollout, every note and open item,
and the exact commands to deploy and to test.
