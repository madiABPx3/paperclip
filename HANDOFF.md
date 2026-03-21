# Paperclip Research Handoff: Durable Execution, Native Reliability, Minimal Custom Wiring

**Last updated**: 2026-03-21 UTC  
**Branch**: `codex/render-relay-deploy`  
**Mode for next session**: research-first, architecture-hardening, no premature implementation

## Assumptions — correct these first or proceed with them
1. The immediate goal is not to keep incrementally patching the current Paperclip path. The goal is to identify the most reliable architecture for autonomous agent execution with minimal custom wiring and maximum use of proven platform primitives. `(CORE-06, CORE-07, WORK-09)`
2. Nothing is off the table at the research stage: keep the current Render path as one candidate, but compare it against managed durable-execution systems and agent runtimes that already solve retries, pause/resume, approvals, and observability natively. `(CORE-02, ARCH-03, GOV-01)`
3. The real problem is not "scheduler ownership" anymore. The real problem is choosing the right durable execution substrate for Paperclip’s control-plane workflows so we stop rebuilding reliability features one seam at a time. `(WORK-09, CORE-03, SELF-06)`

## Current validated state

Treat these as true unless fresh evidence disproves them:

- Render-isolated Paperclip is real and live enough to study:
  - `paperclip-server` health is green on Render.
  - `paperclip-zo-relay` health is green on Render.
  - A dedicated Render worker now owns periodic scheduling.
  - A native timer/system heartbeat run has already been proven on Render.
  - The old Zo scheduled heartbeat fallback has been paused.
- Repo state:
  - `def4656` added the dedicated Render heartbeat worker.
  - `30039c8` added a relay-side eval gate before Paperclip mutations.
- Local verification for `30039c8` passed:
  - `pnpm --dir /home/workspace/paperclip --filter @paperclipai/zo-relay test`
  - `pnpm --dir /home/workspace/paperclip --filter @paperclipai/zo-relay typecheck`
  - `pnpm --dir /home/workspace/paperclip --filter @paperclipai/zo-relay build`
  - `python3.12 -m py_compile /home/workspace/paperclip/scripts/deploy-render.py /home/workspace/paperclip/scripts/bootstrap-render.py`
- Important nuance:
  - The user has stated that `RENDER_API_KEY` is already in Zo.
  - The previous rollout blocker was execution-surface visibility, not proof that the key does not exist anywhere in Zo.
  - Future sessions must distinguish `secret exists in Zo` from `secret is visible on this exact shell/tool surface`. `(CORE-06, ARCH-08)`

## Why the next session is research-focused

Paperclip already proves that the current path can be made to work. That is no longer the main question.

The main question is:

**What durable execution substrate gives Paperclip the highest reliability with the least custom reliability code?**

More concretely, Paperclip needs native support for:

1. Long-running orchestration that survives crashes and restarts.
2. Pausing indefinitely for approvals or external events.
3. Resuming exactly from prior state, not by re-deriving context from comments and ad hoc DB records.
4. Retries and idempotency at the step level.
5. Strong observability of run history and failure points.
6. Zero-human recovery that an agent can drive by API.

That is the capability we are selecting for. The implementation substrate comes second. `(CORE-01, CORE-02, ARCH-08)`

## Platform opportunity analysis

### What is this an instance of?

Paperclip is an instance of a **durable agent workflow control plane**:

- it schedules work
- hands work to an execution runtime
- waits for external outcomes
- gates risky actions on approvals/policies
- resumes over long time horizons
- tracks spend, status, and audit history

It is not merely "a scheduler" or "a webhook relay." `(CORE-02, WORK-09)`

### What variations will exist?

Expect at least these variants:

1. Simple recurring heartbeats.
2. Issue-scoped wakeups.
3. Human approval checkpoints.
4. Budget-stop and resume flows.
5. Multi-agent review/verification chains.
6. Long-running research/build tasks with intermittent external events.
7. Potential future execution planes beyond Zo.

If the substrate handles only one or two of those elegantly, it is not the right foundation. `(CORE-01, ARCH-05)`

### What would make the next variant zero-effort?

The winning substrate should make new workflows mostly configuration or graph-definition work, not new custom plumbing for:

- retries
- checkpoints
- approval waiting
- resumption state
- event correlation
- run history
- operator visibility

If every new Paperclip behavior still requires hand-written persistence and recovery logic, the architecture has failed the platform test. `(CORE-01, CORE-03, CORE-08)`

## Candidate solution classes to research

Research should compare these as first-class options, not as straw men:

### 1. Keep the current Render-centered Paperclip path

Shape:
- Paperclip server + worker + relay on Render
- Zo remains execution plane
- reliability features continue to be built in Paperclip itself

Why it stays in scope:
- already partially proven
- preserves current investment
- maximum control

Main risk:
- reliability burden stays on us; each missing primitive becomes another custom subsystem

### 2. Add a dedicated durable workflow substrate under Paperclip

Examples to investigate:
- Temporal Cloud / Temporal workers
- Trigger.dev Cloud or self-hosted Trigger.dev
- Inngest Cloud / durable endpoints / steps
- Cloudflare Workflows
- LangGraph as the workflow runtime, if it can serve as the durable state machine rather than only an agent library

Why this is attractive:
- these systems already exist to solve retries, checkpointing, pause/resume, external wait, and eventful long-running execution

Main question:
- which one best fits Zo + Render + Modal without forcing raw-human ops or excessive new infrastructure

### 3. Replace more of the custom Paperclip orchestration with an agent-native runtime

Examples to investigate:
- LangGraph durable execution + interrupts
- OpenAI Agents SDK only as execution harness for particular paths

Why this is attractive:
- aligns more directly with agent loops and human-in-the-loop interactions

Main risk:
- some agent runtimes are excellent for agent state and interrupts but weak as general business workflow engines, especially around non-agent operational control-plane concerns

### 4. Use mixed architecture

Likely serious contender:
- Paperclip remains the policy/control-plane domain model
- durable workflow engine handles orchestration state machine
- Zo remains execution plane
- Render or Modal hosts workers where needed

This may be the highest-probability shape if no single product cleanly replaces all current Paperclip responsibilities. `(ARCH-03, CORE-03)`

## Current evidence snapshot from official docs

These are the key patterns already surfaced and should anchor the next research pass:

- **LangGraph**:
  - durable execution is built around persistence/checkpointers
  - interrupts natively pause execution and wait indefinitely for resume input
  - same `thread_id` resumes the same execution state
  - production durability requires a durable checkpointer, not in-memory persistence
- **Trigger.dev**:
  - designed for reliable background jobs and AI tasks
  - native retries, queuing, observability, scheduling
  - waitpoint tokens support approval/external wait patterns
  - idempotency keys are first-class
- **Inngest**:
  - durable steps can wrap API logic directly
  - retries, recovery, observability, waits are built in
  - durable endpoints explicitly position themselves as "all the benefits of durable workflows, none of the overhead"
- **Temporal**:
  - strongest durability story in the set
  - workflow history, signals/updates/queries, and long waits are part of the model
  - likely highest rigor and highest complexity
- **Render native primitives**:
  - workers and cron jobs are solid hosting primitives
  - they do not themselves give durable workflow semantics
  - they are hosting substrates, not complete durable-orchestration runtimes
- **Modal**:
  - excellent for scheduled or spawned compute
  - queues are explicitly not durable enough to be relied on for persistent storage
  - good compute plane, not obviously the primary durable control-plane substrate
- **OpenAI background mode**:
  - useful for long model calls
  - not a durable workflow engine for the Paperclip problem

## Current working hypothesis

The likely answer is **not** "keep adding custom reliability logic directly into Paperclip."

The likely answer is one of these:

1. **Temporal-backed Paperclip** if we want the strongest durable workflow semantics and can justify the operational weight.
2. **Trigger.dev-backed or Inngest-backed Paperclip** if we want maximum managed reliability with lower custom wiring and simpler developer ergonomics.
3. **LangGraph-backed Paperclip** if agent-native pause/resume becomes the dominant concern and the rest of the control-plane state model can fit cleanly around it.
4. **Current Render path remains only if** its custom seams are actually fewer and safer than adopting one of the above. That must be proven, not assumed. `(CORE-06, SELF-06)`

This is still a hypothesis, not a conclusion.

## What the next fresh session should do

The next session should be a disciplined research pass, not an implementation pass.

### Research gate

For each candidate class, answer:

1. What exact primitives does it give us natively?
2. What reliability work would still remain custom?
3. How does approval waiting work?
4. How does resume/state continuity work?
5. How does observability/audit trail work?
6. How does it fit the Tri-Partite model:
   - control plane on Zo
   - compute plane on Modal
   - application sandbox on Render
7. Does it satisfy the 3 AM agent-only recovery test?

### Deliverables

Produce all of these:

1. A candidate matrix:
   - substrate
   - native retries
   - native pause/resume
   - native approval/event waiting
   - native observability
   - hosting fit
   - remaining custom code
   - zero-human fit
   - cost/complexity
2. A recommendation memo:
   - best option
   - why it wins
   - what should be kept from current Paperclip
   - what should be deleted or not extended further
3. A migration shape:
   - minimal pilot slice
   - proof criteria
   - rollback path

## Explicit anti-goals for the next session

Do **not** do these prematurely:

- do not keep patching scheduler or relay code unless the research pass proves the current path is the winner
- do not assume "managed" automatically means simpler
- do not assume "agent framework" automatically means good workflow durability
- do not optimize for minimal migration if it increases long-term custom reliability code
- do not reopen raw infrastructure or human-run ops paths; zero-human remains mandatory `(CORE-08, GOV-01)`

## Stop conditions

Stop and surface it immediately if:

- a candidate requires human dashboard babysitting or manual recovery
- a candidate’s pause/resume semantics are weaker than Paperclip actually needs
- a candidate introduces more custom glue than the current path
- the current path turns out to already be the minimal-custom solution after honest comparison
- research evidence is still too weak to choose a front-runner

Do not guess. The output of the next session should be a high-believability recommendation grounded in official docs and direct comparison. `(CORE-06, WORK-09, SELF-06)`
