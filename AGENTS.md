# Paperclip

Project memory for agents working in `paperclip/`.

## What Paperclip Is

Paperclip is the control plane for autonomous agent operations. It owns:
- companies, agents, goals, and issues
- heartbeat scheduling and run tracking
- approvals, budgets, and policy enforcement
- audit and operator visibility

Zo remains an execution plane. Render is the current managed hosting surface under evaluation for the isolated Paperclip deployment.

## Current Baseline

- Branch in active use for Render work: `codex/render-relay-deploy`
- Live Render services currently tracked by this repo:
  - `paperclip-server`
  - `paperclip-heartbeat-worker`
  - `paperclip-zo-relay`
- Durable execution pilot exists in repo behind `DURABLE_ENGINE=legacy|inngest-pilot`
- Default safe mode is `legacy`
- `inngest-pilot` is not considered live until real `INNGEST_EVENT_KEY` and `INNGEST_SIGNING_KEY` are present on the Render server/worker and the managed deploy is proven

## Read First

Read in this order when touching durable execution or Render rollout:
1. `INNGEST_PILOT_SLICE_2026-03-21.md`
2. `HANDOFF_DURABLE_EXECUTION_NEXT_SESSION_2026-03-21.md`
3. `GAP_ANALYSIS.md`
4. `DRIFT_LEDGER.md`

Read these when working specific adjacent areas:
- Issue identifier guard: `doc/fix-spec-uuid-validation.md`
- Cross-agent review/governance: `doc/CROSS_AGENT_VERIFICATION.md`
- HyperSkills follow-up: `doc/hyperskills-refactor-spec.md`

## Working Rules

- Use the isolated test path for behavior changes before claiming success:
  - start test server: `/home/workspace/.bin/start-paperclip-test.sh`
  - bootstrap: `python3.12 /home/workspace/.bin/bootstrap-paperclip-test.py`
  - trigger: `/home/workspace/.bin/trigger-test-heartbeat.sh`
- Do not claim Render rollout complete from repo state alone. Prove the managed deploy and health surface. `(CORE-06, WORK-09)`
- Treat `scripts/.render-*.json` as sensitive local scratch. Do not rely on them as canonical state; prefer Render API truth. `(ARCH-08)`
- Keep `DURABLE_ENGINE=legacy` as rollback shape. Flip modes with `python3.12 scripts/set-durable-engine.py ...`, not dashboard edits. `(CORE-03, CORE-09)`
- When editing docs, distinguish clearly between:
  - historical Zo-centric integration state
  - current Render-isolated baseline

## Verification Expectations

- Durable pilot changes:
  - targeted tests for durable engine and approval resume
  - local route smoke if touching `/api/inngest`
  - Render deploy proof before calling anything live
- Issue route changes:
  - verify malformed ids fail closed without hitting Postgres
- Bootstrap / embedded-postgres changes:
  - verify the CLI surface accepts the option you add
  - verify root execution does not break embedded Postgres startup

## Known Open Gaps

- Render deploys for commit `cd1c5c8` were triggered manually and may still be building; check live deploy status before assuming the durable pilot code is active.
- Full monorepo `pnpm typecheck` currently fails in unrelated CLI files with a Drizzle type split (`cli/src/commands/auth-bootstrap-ceo.ts`, `cli/src/commands/worktree.ts`). Do not attribute that to the durable pilot without fresh proof.
- Approval flows, budget hard-stop behavior, and cross-agent verification are not yet fully proven on the isolated Render baseline.

## Useful Files

- Durable pilot runtime:
  - `server/src/services/durable-engine.ts`
  - `server/src/routes/inngest.ts`
  - `server/src/services/heartbeat.ts`
  - `packages/shared/src/inngest.ts`
- Rollout helpers:
  - `scripts/deploy-render.py`
  - `scripts/set-durable-engine.py`
  - `scripts/render-status.py`
- Adjacent bugfix:
  - `server/src/routes/issues.ts`
  - `server/src/__tests__/issue-routes-uuid-guard.test.ts`
