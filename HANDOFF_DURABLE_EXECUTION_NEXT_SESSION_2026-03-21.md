# Paperclip Handoff: Durable Execution Next Session

Last updated: 2026-03-21 UTC
Mode: research-to-design handoff

## Assumptions — correct these first or proceed with them

1. The durable-workflow-engine pattern is effectively decided. Paperclip should not keep deepening custom durability logic directly on Render workers. `(CORE-06, CORE-07, WORK-09)`
2. The leading candidate for the first pilot is **Inngest**, but that choice is still justified by substrate fit and research synthesis, not by an already-proven Paperclip integration. `(SELF-06)`
3. The next session should design a **minimal pilot slice**, not resume broad substrate research unless new contradictory evidence appears. `(CORE-03, WORK-01)`

## Current Decision State

### Decided

- Paperclip's real problem is **durable orchestration with external-event continuation**, not scheduler ownership.
- Render is a useful host and adapter surface, but not the right primary owner for pause/resume/approval-heavy workflow semantics.
- The strongest proven pattern class is:
  - durable workflow runtime owns orchestration state
  - domain service emits/consumes events
  - execution adapters perform actual work
  - external approval/event resumes the same durable run

### Current front-runner

- **Inngest** is the recommended first pilot substrate.

### Ranked finalists

1. Inngest
2. Trigger.dev
3. Temporal

### Rejected as primary durable substrate

- Render-centered custom durability expansion
- LangGraph as the whole control-plane engine

LangGraph remains viable **inside a workflow step** for agent reasoning/runtime concerns.

## What Has Actual Evidence vs What Does Not

### Strong evidence

- Official documentation across Temporal, Inngest, Trigger.dev, AWS Step Functions, and Azure Durable shows the same durable orchestration pattern for approvals, waits, and resume.
- Render docs support the conclusion that Render is a host/task surface, not the same kind of durable orchestration owner.

### Weak or absent evidence

- There is **no known existing successful Paperclip integration** with Inngest, Trigger.dev, or Temporal in the local repo or obvious upstream public surface.

### Paperclip-specific adjacency evidence

- Upstream Paperclip issue `#1190` proposes a persistent coordination layer using **LangGraph StateGraph + PostgresSaver**.
- Upstream PR `#978` proposes a **DeerFlow** adapter (LangGraph-based runtime).
- Both are still open, so they are **directional signals**, not deployment proof.

## Artifacts Created In This Session

- `file 'paperclip/DURABLE_EXECUTION_RESEARCH_2026-03-21.md'`
- `file 'paperclip/DURABLE_EXECUTION_PROVEN_PATTERNS_2026-03-21.md'`
- `file 'paperclip/DURABLE_ENGINE_FINALISTS_2026-03-21.md'`

Read those in that order if deeper context is needed.

## Exact Goal For The Next Session

Design the **minimal Inngest pilot** for Paperclip.

Do not reopen full-market research unless something materially breaks the current conclusion.

## Pilot To Design

### Workflow slice

`paperclip/heartbeat.requested`
→ durable workflow starts
→ call Zo execution adapter
→ if approval required, pause durably
→ `paperclip/approval.resolved`
→ resume same workflow
→ write result/cost/status back into Paperclip

### Why this slice

It is the smallest slice that tests:

- retries
- pause/resume
- approval waiting
- event-driven continuation
- observability
- rollback safety

## Deliverables For The Next Session

### 1. Pilot architecture memo

Define:

- what stays in Paperclip
- what moves to Inngest
- what remains on Zo
- whether Render is still needed in the pilot path

### 2. Event contract

Define the first event schemas:

- `paperclip/heartbeat.requested`
- `paperclip/approval.requested` if needed
- `paperclip/approval.resolved`
- `paperclip/execution.completed` or equivalent

For each:

- producer
- consumer
- required ids
- idempotency key
- correlation strategy

### 3. Workflow boundary

Define:

- step boundaries
- retry boundaries
- what can be retried safely
- what must be idempotent
- where side effects occur

### 4. State ownership map

Be explicit about:

- Paperclip as domain/audit/policy system of record
- Inngest as workflow execution state owner
- Zo as execution plane
- any derived status mirrors

### 5. Proof plan

Define how to prove:

1. workflow survives restart
2. approval wait is native and does not poll
3. resume continues same durable run
4. retries do not duplicate successful steps
5. run is inspectable by an agent at 3 AM
6. rollback to old path is one switch, not a manual repair exercise

## Constraints For The Next Session

- Stay in research/design mode unless explicitly asked to implement.
- Do not assume any secret is absent just because one surface cannot read it.
- Do not treat “managed” as proof of lower total complexity without mapping remaining custom code.
- Do not design a system that needs a human to babysit dashboards or repair stuck runs manually.

## Recommended Opening Move For The Next Session

1. Read:
   - `file 'paperclip/HANDOFF.md'`
   - `file 'paperclip/HANDOFF_DURABLE_EXECUTION_NEXT_SESSION_2026-03-21.md'`
   - `file 'paperclip/DURABLE_ENGINE_FINALISTS_2026-03-21.md'`
2. Confirm the task is:
   - **design the Inngest pilot slice**
3. Produce:
   - event contract
   - workflow boundary map
   - proof plan

## Stop Conditions

Stop and surface it immediately if:

- the pilot requires more than one new major architectural assumption
- the Inngest model cannot cleanly express approval resume semantics
- the proposed state ownership becomes ambiguous between Paperclip and Inngest
- rollback requires manual operational repair instead of a simple route/selector reversal
