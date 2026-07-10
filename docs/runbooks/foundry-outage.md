# Runbook — `egp-prompt-fallback-nonzero` (Foundry outage)

**Sev 3** (email, no page).

## Symptom
`egp.prompt.fallback` > 0 in the last hour. The app fell back to
bundled prompts because Foundry was unreachable.

## Mitigation
- Confirm Foundry status.
- Verify the bundled prompt version matches the last-known-good Foundry
  prompt (check `docs/prompts/README.md` version table).
- If Foundry-only prompt updates are queued, they will apply when the
  fetch resumes.

Bundled prompts guarantee the system stays available; there is no
runtime action required.
