# Paperclip Render Gap Analysis

**Date**: 2026-03-21 UTC
**Auditor**: ender
**Scope**: Fresh capability and governance analysis of the isolated Render path against current live evidence

## Verdict

The Render path is **operational as an isolated control plane baseline, but still short of full capability parity**.

What is proven now:

- authenticated Render bootstrap is live
- the isolated company, three agents, and goal are seeded
- at least one native Render heartbeat completed end-to-end
- the successful run posted an issue comment and moved the issue to `done`
- run detail, event, log, dashboard, and company APIs are reachable through board auth

What is now proven beyond the earlier pass:

- Render-native periodic scheduling is live via a dedicated Render worker
- the old Zo scheduled Paperclip heartbeat fallback has been paused
- a native timer/system heartbeat was enqueued on Render after the worker cutover

What is not yet proven:

- approval workflows on the isolated company
- budget enforcement on the isolated company
- session continuity across repeated heartbeats
- cross-agent verification on the isolated company
- live eval-gated execution on the isolated Render relay path
- browser/UI parity for the Render deployment

That means the old “fully operational” framing is no longer acceptable for the Render-isolated target. `(CORE-06, SELF-06, WORK-09)`

## Validated Evidence Snapshot

- `https://paperclip-server.onrender.com/api/health` reports authenticated private deployment, `bootstrapStatus: "ready"`.
- `https://paperclip-zo-relay.onrender.com/health` reports `{"ok":true}`.
- `paperclip/scripts/.render-bootstrap.json` contains live admin creds, company id, three agent ids, three agent keys, and goal id.
- `paperclip/scripts/.render-state.json` now includes the dedicated worker service `srv-d6v2sr75r7bs73ej4nog`.
- The isolated company `Zo Autonomous` exists on Render with company budget `100000` cents, `requireBoardApprovalForNewAgents=true`, three agents, and one active goal.
- Heartbeat run `11a72428-7e25-4e5f-b935-4934b050c2c2` succeeded on 2026-03-21 04:52:47Z → 04:53:02Z.
- That run is linked to issue `ZOA-1`, posted a comment, and changed the issue status from `todo` to `done`.
- Render worker `paperclip-heartbeat-worker` is live on service `srv-d6v2sr75r7bs73ej4nog`.
- Heartbeat run `a4722cad-1b8c-45fa-8cd6-36a967f6ed00` was created on 2026-03-21 05:43:28Z with `invocationSource: "timer"` and `triggerDetail: "system"`.
- Zo scheduled agent `686c2275-229f-4fe9-82ac-e3a8a5b7f3d3` is now paused.
- Repo commit `30039c8` adds relay-side eval gating before Paperclip mutations, plus deterministic Render env wiring for `RELAY_EVAL_ENABLED`, `RELAY_EVAL_PROJECT`, and `EVAL_SERVICE_URL`.
- Local verification for `30039c8` passed (`zo-relay` test, typecheck, build; Python compile for deploy/bootstrap scripts).
- Live Render rollout of `30039c8` is still unproven because this shell surface did not expose `RENDER_API_KEY`, so relay env update and forced redeploy could not be completed in this turn.

## Capability Matrix

| Capability | Status | Evidence | Gap |
|---|---|---|---|
| Authenticated deployment bootstrap | Validated on Render | Health endpoint green; board sign-in works; bootstrap state current | None for first bootstrap proof |
| Company / agent / goal seeding | Validated on Render | Company, three agents, and active goal present in live APIs | Seed is minimal, not parity with older Zo company state |
| Heartbeat invocation | Validated on Render | Run `11a72428-...` succeeded through Render relay | Only one proved run |
| Issue-scoped wakeups | Validated minimally | Known-good run was triggered from `issue.comment.reopen` automation context | Only comment-reopen path proved |
| Session continuity / resume | Implemented but unvalidated | Run detail shows `sessionIdBefore=null`, `sessionIdAfter=null` | No repeated heartbeat proof for same task identity |
| Comment posting + issue status mutation | Validated on Render | Run activity shows `issue.comment_added` and `issue.updated` to `done` under same run id | No proof yet for multi-issue or reviewer chain mutations |
| Cost-event reporting | Implemented but unvalidated | Cost summary endpoint works; company and agent spend remain `0` | No direct isolated proof that relay path emitted/ingested a cost event |
| Budgets / budget enforcement | Implemented but unvalidated | Budget values exist on company/agents; budget services exist in repo | No live Render proof of warn/hard-stop/approval behavior |
| Approvals / approval-required flows | Implemented but unvalidated | Company requires board approval for new agents; approvals APIs are live | No isolated approval created/resolved during this pass |
| Scheduled heartbeats | Validated on Render | Dedicated worker service produced run `a4722cad-...` with `timer/system` context; Zo fallback is paused | Need one later continuity proof at the normal 4h cadence, not only the forced 60s proof |
| Heartbeat run logs / events observability | Validated minimally | Run detail, events, and log endpoints return data for known-good run | Only two lifecycle events observed; not yet stress-tested |
| Dashboard / UI operability | API validated; UI unvalidated | Dashboard API returns agent/task/cost summary | Browser/UI flow not proven on Render |
| Eval integration | Implemented in repo; live rollout unvalidated | Commit `30039c8` adds relay-side eval gate and Render env wiring; eval endpoint `https://eval-service-abp.zocomputer.io/health` is healthy | Live Render relay still needs env rollout + redeploy proof before the claim becomes operational truth |
| Cross-agent verification | Configured but unvalidated | Agent metadata/policies support reviewer separation | No `in_review` → reviewer proof on Render |
| Config recovery / re-bootstrap / resumability | Bootstrap path validated; recovery partially unvalidated | Resumable bootstrap artifacts exist and match live state | HTTP recovery exists in code but was not re-exercised this pass |

## Highest-Leverage Gaps

### 1. Render docs still overstate capability parity

The current isolated company has one issue and one proven run, while older project docs still describe the pre-isolation Zo company with 29 issues, active agent fleet history, and fully operational governance loops. That is historical context, not current Render truth. `(CORE-06, CORE-08)`

### 2. Eval is implemented but not yet live on the Render relay path

The missing relay-side eval gate is now fixed in repo, but the live Render relay has not been rolled forward yet because the current shell surface could not reach the Render control plane. Until the env update and redeploy are proven, the system still cannot claim eval-gated isolated execution as live behavior. `(WORK-04, WORK-10, CORE-06)`

### 3. Governance features exist in code but remain unproven on Render

Budget services, approval APIs, and cross-agent verification all exist. None were exercised on the isolated company during this pass. These remain implementation facts, not live capability proofs. `(GOV-07, WORK-09)`

### 4. Session continuity still has a live unknown

The native timer proof used a forced short interval and the latest Render timer run is still in progress. Session carry-forward under repeated normal scheduling remains unproven, and the earlier failed manual run shows relay/execution instability still exists on some paths. `(ARCH-08, WORK-09)`

## Governance Re-Score

| Principle | Status | Re-score |
|---|---|---|
| CORE-06 | Partial | Current analysis is evidence-based, but project docs still mix historical Zo state with current Render state |
| CORE-08 | Partial | Current-state artifacts now exist, but `paperclip/AGENTS.md` still lags the Render baseline |
| ARCH-08 | Partial | Run/event/log surfaces work, but important isolation drift is not yet surfaced in the primary docs |
| ARCH-13 | Partial | Legacy Zo webhook routes include breaker/cooldown logic; Render isolation proof did not establish equivalent scheduler resilience as a complete system |
| ARCH-16 | Validated | Authenticated private deployment is live and board auth works |
| ARCH-17 | Validated | Render now owns periodic autonomy through a dedicated background worker; the Zo scheduler fallback is paused |
| GOV-07 | Partial | Approval-required config is live, but no isolated approval workflow was proven end-to-end |
| WORK-01 | Unvalidated | No Render proof yet that live agent behavior consistently follows plan-first protocol |
| WORK-04 | Unvalidated | Reviewer chain exists in config, but no Render proof of cross-agent verification |
| WORK-10 | Partial | This is still meta-layer infrastructure, but the isolated execution path and legacy core-Zo path are both active |

## Ranked Next Slice

1. **Finish the live relay eval rollout.** Update the live Render relay env to include `RELAY_EVAL_ENABLED=true`, `RELAY_EVAL_PROJECT=paperclip`, and `EVAL_SERVICE_URL=https://eval-service-abp.zocomputer.io/eval`, then redeploy commit `30039c8` and prove a gated run. `(WORK-04, WORK-10, CORE-06)`
2. **Run an isolated governance proof pack.** Seed one hire/approval scenario and one budget-hard-stop scenario in the Render company, then verify resulting approvals, pauses, and recovery behavior. `(GOV-07, ARCH-17, WORK-04)`
3. **Prove continuity on a second heartbeat.** Reuse the same issue/task identity on Render, confirm session/workspace carry-forward, and verify a non-forced cadence run after the worker cutover. `(ARCH-08, WORK-09)`
4. **Refresh stale state docs.** Update `paperclip/AGENTS.md` and any remaining Zo-centric status language so the next agent starts from the isolated Render baseline instead of the older core-Zo operating history. `(CORE-08, WORK-09)`

## Pass / Fail Gate

- **Research → Plan**: pass
- **Plan → Execute**: pass
- **Execute → Present**: pass, with honest gaps retained

The isolated Render path is real, but the “full Paperclip capability” target has **not** been reached yet.
