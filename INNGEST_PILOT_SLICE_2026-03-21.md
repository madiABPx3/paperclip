# Paperclip Minimal Inngest Pilot Slice

Last updated: 2026-03-21 UTC
Status: design-ready
Mode: implementation-ready pilot spec

## Assumptions — correct these first or proceed with them

1. The pilot is intentionally narrow: one heartbeat flow that may require approval, then resumes and completes. It is not a broad migration of Paperclip execution. `(CORE-03, WORK-01, BEHAV-01)`
2. Paperclip remains the system of record for domain truth: approvals, issues, cost events, activity logs, and company/agent metadata. `(ARCH-03, ARCH-08, ARCH-17)`
3. Inngest owns workflow runtime state only: retries, wait/resume continuity, step memoization, and replay. Zo remains the execution plane. Render remains only the host for the worker connection. `(CORE-07, ARCH-03, ARCH-08)`

## Platform Opportunity Analysis

### What is this an instance of?

This is an instance of a durable, event-driven agent workflow for the Paperclip control plane. The specific slice is "heartbeat execution with optional governance pause and event-driven resume." `(CORE-01, CORE-02, WORK-09)`

### What variations will exist?

Expected follow-on variants:

- timer-only heartbeat with no approval
- issue wakeup with no approval
- budget-stop and resume
- multi-agent review chain
- external callback resume
- long-running build/research tasks that checkpoint across days

The chosen boundary must support those variants without reintroducing custom persistence and retry logic inside Paperclip. `(ARCH-05, CORE-01)`

### What makes the next variant zero-effort?

The next variant should require:

- a new event name
- a new function or branch in the workflow
- the same writeback and correlation contracts

It should not require new custom queue semantics, polling loops, or homegrown pause/resume state. `(CORE-01, CORE-03, CORE-08)`

## Pilot Goal

Prove that Paperclip can hand off orchestration durability to Inngest while preserving:

- Paperclip as domain/audit owner
- Zo as execution plane
- zero-human restart recovery
- one-switch rollback to the legacy path

This pilot must prove the substrate, not just the happy path. `(WORK-09, SELF-06)`

## Minimal Workflow Shape

```text
Paperclip wakeup source
  -> emit paperclip/heartbeat.requested
  -> Inngest workflow starts
  -> load Paperclip context
  -> invoke Zo execution adapter
  -> if no approval required: write result/cost/status back to Paperclip and finish
  -> if approval required:
       create Paperclip approval
       wait durably for paperclip/approval.resolved
       resume same workflow
       apply approval outcome
       finalize result/cost/status in Paperclip
```

The workflow is deliberately scoped to a single approval checkpoint. If this slice works cleanly, the same pattern can extend to budget gates and multi-step review chains. `(CORE-03, ARCH-05)`

## Architectural Boundary

### Paperclip owns

- company, agent, and issue metadata
- approval creation and approval decision truth
- activity log
- cost events
- user-facing run and issue state
- authorization and governance policy

### Inngest owns

- workflow run lifecycle
- retries
- wait/resume semantics
- step memoization
- replay surface
- correlation of the approval resolution back into the same durable run

### Zo owns

- execution conversation/session
- structured result from the agent invocation
- actual work performed by the agent

### Render owns

- long-running worker/container process that hosts the Inngest connection
- not the orchestration state

This keeps domain truth in Paperclip, execution truth in Zo, and workflow mechanics in Inngest. No layer has ambiguous ownership. `(ARCH-03, ARCH-08, GOV-06)`

## Event Contract v1

All pilot events must carry `schemaVersion: "v1"` and use globally unique event IDs. Public contract changes require versioned evolution, not in-place drift. `(ARCH-06, WORK-09)`

### 1. `paperclip/heartbeat.requested`

**Producer**
- Paperclip heartbeat entrypoint or wakeup adapter

**Consumer**
- Inngest pilot workflow

**Event id**
- `heartbeat-requested:<runId>`

**Required data**

```json
{
  "schemaVersion": "v1",
  "companyId": "uuid",
  "agentId": "uuid",
  "runId": "uuid",
  "invocationSource": "timer|manual|automation",
  "triggerDetail": "system|issue|approval|manual",
  "issueId": "uuid|null",
  "taskKey": "string|null",
  "requestedAt": "iso8601",
  "relay": {
    "schemaVersion": "v1",
    "executionMode": "heartbeat",
    "paperclipBaseUrl": "https://...",
    "paperclipCompanyId": "uuid|null",
    "paperclipAgentKeyRef": "string",
    "zoPersonaId": "string|null",
    "zoPersonaName": "string|null",
    "zoModelScenario": "general|code-generation|code-review|architecture-planning|research|scoring-evaluation|data-processing",
    "timeoutMs": 45000,
    "maxAttempts": 2,
    "taskIdentityPreference": ["issueId", "taskKey", "runId"]
  },
  "contextSnapshot": {}
}
```

**Notes**
- `runId` is the durable workflow anchor.
- `relay` mirrors the existing relay shape so the pilot reuses current execution intent instead of inventing a parallel configuration model.
- The producer must set the event `id`; Inngest event deduplication is keyed off that ID for 24 hours. `(CORE-06, ARCH-06)` 

### 2. `paperclip/approval.resolved`

**Producer**
- Paperclip approval approve/reject/request-revision/cancel path, emitted only after the approval record is committed

**Consumer**
- Waiting Inngest workflow

**Event id**
- `approval-resolved:<approvalId>:<updatedAt>`

**Required data**

```json
{
  "schemaVersion": "v1",
  "companyId": "uuid",
  "approvalId": "uuid",
  "runId": "uuid",
  "resumeKey": "sha256(companyId:runId:approvalId)",
  "status": "approved|rejected|revision_requested|cancelled",
  "decisionNote": "string|null",
  "decidedAt": "iso8601|null",
  "decidedByUserId": "string|null",
  "requestingAgentId": "uuid|null",
  "issueIds": ["uuid"]
}
```

**Notes**
- `resumeKey` is the safe correlation token for the wait expression.
- Emission must happen only on the first state transition that actually changes the approval.
- Repeated route calls that are treated as no-ops must not emit duplicate resume events. `(ARCH-08, GOV-04)`

### 3. Deferred event: `paperclip/execution.completed`

Not part of the pilot unless a second consumer appears. The pilot does not need a downstream fan-out event to prove durability; Paperclip can remain the final write target for now. `(CORE-03)`

## Correlation and Idempotency

### Durable correlation

- Primary correlation key: `runId`
- Wait/resume correlation: `resumeKey = sha256(companyId + ":" + runId + ":" + approvalId)`
- Inngest wait expression:
  - `async.data.resumeKey == event.data.resumeKey`

### Idempotency rules

- Producers must set event IDs explicitly.
- Approval creation must use a deterministic external key derived from `runId` and approval type.
- Paperclip writeback operations must accept a deterministic idempotency key:
  - `runId + ":" + stepId`
- Finalization writes must be upserts or conflict-safe updates, never blind duplicate inserts.

This is required because the whole value proposition of the pilot is retry safety under restarts and partial failures. `(ARCH-09, GOV-04, WORK-09)`

## Workflow Step Boundaries

The pilot function should have these stable step IDs:

1. `load-paperclip-context`
2. `invoke-zo-heartbeat`
3. `write-initial-paperclip-effects`
4. `create-approval-if-needed`
5. `wait-for-approval-resolution`
6. `apply-approval-outcome`
7. `finalize-run-and-cost`

### Why this split

- Reads and writes are separated clearly.
- Every non-deterministic operation is inside a step boundary.
- The approval pause is isolated to one explicit seam.
- Future variants can add steps without disturbing the core contract if they follow stable step naming. `(ARCH-08, ARCH-09)`

## Retry Boundaries

### Safe to retry

- load Paperclip context
- Zo invocation, if guarded by step memoization and downstream idempotent writeback
- posting/update operations back into Paperclip, if keyed by `runId + stepId`
- waiting for approval
- finalization

### Must be idempotent

- approval creation
- issue comment creation or issue status mutation
- cost event recording
- heartbeat completion writeback

### Must not be retried as an unmanaged side effect

- any state mutation that lacks a deterministic idempotency key

If a side effect cannot be made idempotent, it does not belong in this pilot slice. `(ARCH-09, CORE-03)`

## Paperclip Integration Seams

The pilot should reuse existing seams where they already exist:

- current relay payload structure in `packages/zo-relay/src/types.ts`
- current approval decision truth in `server/src/routes/approvals.ts`
- current heartbeat run identity and wakeup metadata in `packages/shared/src/types/heartbeat.ts`

Minimal required additions:

1. A workflow selector at the heartbeat entrypoint:
   - `DURABLE_ENGINE=legacy|inngest-pilot`
2. Event emission for `paperclip/heartbeat.requested` when selector is `inngest-pilot`
3. Event emission for `paperclip/approval.resolved` after approval decision commit when selector is `inngest-pilot`
4. Idempotent writeback endpoints or service methods keyed by `runId + stepId`

Do not change the Paperclip approval model, issue model, or Zo structured output format in the pilot unless evidence shows they are insufficient. `(CORE-06, BEHAV-03, GOV-08)`

## Worker Hosting Shape

Recommended first pilot shape:

- host the Inngest worker on Render using `connect()`
- keep the worker long-running and isolated from the Paperclip web process
- keep Paperclip web/API service unchanged except for selector + event emission seams

Why:

- preserves current Render hosting path
- avoids making Render the durable owner
- keeps long waits outside inbound HTTP timeout concerns

Important nuance:

- `connect()` is currently documented as Public Beta. If we decide beta status is too much risk for the first implementation, the same event/state contract can be hosted with `serve()` first without changing domain boundaries. `(CORE-06, GOV-08)`

## Proof Criteria

The pilot passes only if all of these are proven:

1. **Restart survival**
   - Start a pilot run.
   - Let it reach `wait-for-approval-resolution`.
   - Kill the worker.
   - Restart the worker.
   - Prove the same run remains waiting with intact context.

2. **Native approval wait**
   - While waiting, no custom polling loop runs against Paperclip approvals.
   - The workflow resumes only because `paperclip/approval.resolved` is emitted.

3. **Same-run resume**
   - Approve in Paperclip.
   - Prove the waiting workflow resumes the same Inngest run instead of triggering a new heartbeat.

4. **Step-level retry**
   - Inject a transient failure after resume.
   - Prove previously completed steps do not rerun.
   - Prove only the failed step retries.

5. **3 AM inspectability**
   - An agent can answer:
     - what run is waiting?
     - what approval is it waiting on?
     - what event resumed it?
     - what step failed last?
   - using `runId`, `approvalId`, event ID, Paperclip activity, and Inngest run history.

6. **Rollback simplicity**
   - Flip the selector back to `legacy`.
   - New runs use the current path immediately.
   - No data repair, manual unblocking, or backfill is required.

These are the real gates. Anything less proves only a demo, not a viable substrate. `(WORK-09, SELF-06, GOV-04)`

## Rollback Shape

Rollback must be one switch, not an incident procedure.

### Selector

- `DURABLE_ENGINE=legacy`
  - current Render worker + Zo relay wakeup path
- `DURABLE_ENGINE=inngest-pilot`
  - emit event and let Inngest own orchestration state

### Rollback procedure

1. Set selector to `legacy`
2. Stop sending `paperclip/heartbeat.requested`
3. Keep Paperclip approval and issue truth exactly where it already lives
4. Leave historical Inngest run data as operational history, not domain truth

### What rollback must NOT require

- approval migration
- issue status repair
- domain-state replay from Inngest back into Paperclip
- manual operator reconstruction of stuck runs

If rollback needs any of those, the boundary is wrong. `(GOV-06, ARCH-09, CORE-03)`

## Explicit Anti-Goals

- Do not migrate all heartbeat traffic to Inngest in the first pass.
- Do not move Paperclip approval truth into Inngest.
- Do not add a custom polling loop for approval checks.
- Do not redesign the whole relay output contract during the pilot.
- Do not let Render regain ownership of durability semantics.

## Recommendation

Proceed with implementation of this exact pilot slice unless one of these becomes true:

1. We determine that Inngest's beta `connect()` requirement is unacceptable and also do not want to use `serve()`.
2. We discover the existing Paperclip writeback seams cannot be made idempotent without a larger refactor.
3. We find a hard mismatch between current approval routes and event emission after commit.

Absent one of those failures, this is the minimal, honest pilot for proving Paperclip durable execution on Inngest. `(CORE-03, WORK-09, SELF-06)`
