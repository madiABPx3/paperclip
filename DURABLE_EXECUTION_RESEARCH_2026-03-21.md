# Paperclip Durable Execution Research

Last updated: 2026-03-21 UTC

## Scope

This pass answers one question:

**What durable execution substrate should own Paperclip's retries, pause/resume, approvals, long waits, continuity, and observability with minimal custom wiring and maximum use of native platform capability?**

This is an architecture selection pass, not an implementation pass.

## Assumptions

1. The current Render-centered Paperclip path is a valid candidate, not the default answer. `(CORE-06, SELF-06)`
2. The user's standard is zero-human, agent-first recovery. Any design that requires manual dashboard babysitting or ad hoc terminal rescue fails. `(CORE-08, ARCH-08)`
3. "Secret exists in Zo" and "this execution surface can read the secret" are different statements and must not be conflated in future rollout work. `(CORE-06, ARCH-08)`

## Platform Opportunity Analysis

### 1. What is this an instance of? `(CORE-02)`

Paperclip is not merely a scheduler or a relay. It is a **durable agent workflow control plane**:

- starts governed runs
- waits for external events and approvals
- resumes after long delays
- tracks run state and audit history
- routes execution into Zo and other planes
- needs operator-grade observability and replay

### 2. What variations will exist? `(CORE-02, ARCH-05)`

Expected workflow variants:

- recurring heartbeats
- issue-triggered wakeups
- approval checkpoints
- budget stop / resume
- long-running research or build flows
- multi-agent review chains
- future execution targets besides Zo

### 3. What makes the next variant zero-effort? `(CORE-01, CORE-02, CORE-03)`

The winning substrate makes the next workflow mostly:

- event schema
- workflow definition
- policy configuration

It should **not** require new bespoke plumbing for:

- retries
- checkpoint persistence
- indefinite waits
- event correlation
- replay
- run inspection

## Candidate Matrix

| Candidate | Native retries | Native pause / resume | Native approval / event wait | Native observability | Hosting fit with Zo / Render / Modal | Remaining custom code | Zero-human fit | Cost / complexity |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Current Render-centered Paperclip** | Partial. Render workers are a host primitive; retry semantics come from app code or queue framework. Render Workflows adds managed queuing and automatic retries, but is still beta. | Weak as a substrate. Workers themselves do not provide durable checkpoint / resume semantics. | Weak. Must be built in Paperclip or queue layer. | Good for service logs and metrics, but not workflow-native execution history. | Strong as hosting plane only. Good for always-on services, not sufficient alone as durable execution owner. | High: queue semantics, wait state, approval correlation, replay, recovery logic. | Medium. API automation exists, but logical recovery burden stays custom. | Low platform delta, high engineering burden. |
| **Temporal Cloud + Paperclip workers** | Excellent. Workflow execution and retries are core primitives. | Excellent. Event History durably replays and workflows can run for years. | Excellent. Signals, Updates, and Queries are first-class. | Excellent. Visibility, search attributes, workflow history. | Technically strong, but introduces a new specialist platform plus worker deployment. Render or Zo can host workers; Modal is not needed for the control path. | Medium: workflow definitions, adapters, approval/UI integration, worker deployment. | High once deployed; low human recovery burden. | Highest rigor, highest operational and conceptual weight. |
| **Trigger.dev-backed Paperclip** | Strong. Task retries and idempotency keys are first-class. | Strong. Long waits are checkpointed and don't burn compute while waiting. | Strong. Waitpoint tokens support external approval / callback patterns. | Strong. Built-in logs, traces, spans, replay, alerts. | Good fit if Paperclip remains on Render/Zo and Trigger owns durable run state. Can also self-host, but cloud is the cleaner zero-human path. | Medium: map Paperclip approvals/events onto wait tokens and run boundaries. | High in cloud shape; moderate if self-hosted. | Moderate platform cost, moderate complexity. |
| **Inngest-backed Paperclip** | Strong. Step-level retries are native; successful steps are memoized and not re-run. | Strong. Multi-step functions are durable and resume from stored function state. | Strong. `step.waitForEvent()` and time sleeps are native; docs position multi-step waits up to a year. | Strong. Run details, traces, metrics, retry attempts, event logs are built in. | Best fit for current shape: Paperclip can stay the domain/control API while Inngest owns the durable workflow state machine. Works with HTTP-served functions or container workers. | Low to medium: event schemas, adapters, idempotent step boundaries, correlation IDs. | High in managed-cloud shape. | Moderate platform cost, lower complexity than Temporal. |
| **LangGraph as primary durable substrate** | Mixed. Durable execution exists, but only with persistent checkpointers and deterministic/task discipline. | Strong for agent interruption/resume when configured correctly. | Strong for human-in-the-loop agent/tool approvals via interrupts. | Moderate to strong with LangSmith Deployment; weaker if open-source only. | Good as an execution runtime for agent loops, weaker as the primary business workflow engine for Paperclip's non-agent orchestration. | High: scheduling, domain event routing, operator workflows, non-agent control-plane semantics. | Medium in open-source/self-host shape; higher with managed LangSmith Deployment. | Moderate to high complexity, with hidden infra/custom-state costs. |
| **Mixed: Paperclip domain control plane + Inngest durable workflows + Zo execution plane + Render/Modal as hosts** | Strong, delegated to Inngest. | Strong, delegated to Inngest. | Strong, event-native and approval-friendly. | Strong across Inngest run traces plus existing Paperclip / Zo observability. | Best overall fit. Preserves Tri-Partite roles while moving durability into a purpose-built managed layer. | Lowest strategic custom surface: Paperclip keeps domain policy; substrate owns workflow mechanics. | Highest practical fit if adding one external specialist substrate is allowed. | Moderate platform cost, best engineering leverage. |

## Recommendation Memo

### Best option

**Recommend a mixed architecture: keep Paperclip as the policy and domain control plane, move durable execution to Inngest, keep Zo as the execution plane, and keep Render as a host/adaptor plane instead of the workflow owner.**

This is the best balance of:

- minimal custom reliability code `(CORE-07)`
- fast path to new workflow variants `(CORE-01, ARCH-05)`
- strong observability and replay `(ARCH-08, ARCH-15)`
- agent-first recovery `(CORE-08)`
- low enough operational weight to actually ship `(CORE-03)`

### Why it wins

#### 1. It matches the real shape of Paperclip better than the alternatives. `(CORE-06, WORK-09)`

Paperclip is fundamentally eventful and policy-driven:

- heartbeat requested
- approval requested
- approval granted / denied
- budget exceeded
- Zo run completed
- verification failed

Inngest's model aligns with this directly:

- steps persist state
- waits are event-native
- successful steps are memoized
- traces are run-native

That means less impedance mismatch than:

- **Trigger.dev**, which is strong but more token/run-centric than event-native
- **Temporal**, which is stronger in theory but heavier than the problem currently requires
- **LangGraph**, which is strongest for agent-loop interruption, not for all control-plane workflow mechanics

#### 2. It removes the specific failure mode the current path keeps reintroducing. `(CORE-04, WORK-09)`

The current Render path keeps pushing Paperclip toward building custom durable semantics:

- custom wait state
- custom replay semantics
- custom event correlation
- custom resume logic
- custom approval plumbing

Render is a good **host**. It is not, by itself, the durable workflow substrate Paperclip needs.

#### 3. It preserves what is already valuable in Paperclip instead of replacing the domain. `(ARCH-03, CORE-10)`

Paperclip should keep owning:

- organization / agent model
- issue model
- budgets and policies
- approval rules
- audit-facing domain concepts
- Zo execution dispatch contract

Those are domain assets. They should not be rewritten into a vendor's mental model.

The workflow substrate should own:

- retries
- checkpoints
- sleeps / waits
- run continuity
- replay
- execution inspection

That is the durable-mechanics layer.

### What to keep from current Paperclip

Keep:

- Paperclip domain model and API
- current Zo relay / execution contract shape
- existing auth / audit patterns that already map actions back to Paperclip runs
- Render as a host for Paperclip API or adapters where always-on service hosting is still useful
- existing observability surfaces that remain valuable above the workflow layer

### What not to keep extending

Do **not** keep extending:

- Render worker logic as if it were the durable state machine
- custom pause / resume semantics in Paperclip
- ad hoc recovery logic based on comment scraping or partial DB reconstruction
- new bespoke approval-wait plumbing in the current relay / worker chain

If the architecture decision stands, those should be treated as debt to freeze and replace, not as foundations to deepen. `(GOV-10, WORK-09)`

## Why not the others?

### Why not keep Render-centered Paperclip?

Because it leaves the hardest part custom. Render docs clearly describe background workers as services that poll a task queue, and even point high-volume distributed tasks toward Render Workflows beta. That means Render alone is still a hosting surface, not a complete durable workflow engine for Paperclip's needs.

### Why not Temporal first?

Temporal is the strongest pure durable-execution substrate in the set. If Paperclip were a larger multi-team platform, or if workflow correctness / lifespan / mutation semantics were the dominant problem over delivery speed, Temporal could win.

It loses here because:

- the operational and conceptual weight is materially higher
- it likely demands more adapter code than Inngest for the current scope
- it solves the problem with maximum rigor, not minimum justified complexity

Temporal is the strongest **backstop candidate**, not the best first migration candidate. `(CORE-03)`

### Why not Trigger.dev first?

Trigger.dev is credible and close. It is the runner-up.

It loses narrowly because Paperclip's workflows are more naturally modeled as domain events than token-driven pauses. Trigger waitpoints are good, but Inngest's `waitForEvent` and step-state model fit approval/event continuation more directly.

If the team strongly prefers a task-centric TypeScript developer experience, Trigger.dev is the best alternative.

### Why not LangGraph as the primary substrate?

LangGraph should stay in scope as an **execution runtime inside a workflow step** for agent reasoning paths.

It should not be the primary durable control-plane substrate because:

- production durability still depends on persistent checkpointers and replay discipline
- interrupts restart nodes, so side effects before interrupts must be carefully designed
- it is better at agent-loop continuity than whole-business workflow ownership

Use it where agent state matters most, not where the whole control plane needs durable orchestration.

## Minimal Pilot / Migration Shape

### First slice `(ARCH-04, GOV-06, WORK-04)`

Pilot one workflow only:

**Heartbeat with approval-aware continuation**

Proposed shape:

1. Paperclip emits `paperclip/heartbeat.requested`.
2. Inngest workflow starts run, records correlation IDs, and calls Zo execution.
3. If Zo or policy requires approval, workflow pauses on `paperclip/approval.resolved`.
4. On approval event, same workflow resumes and completes.
5. Final state posts results back into Paperclip issues / runs.

Why this slice:

- touches retries
- touches long waits
- touches approvals
- touches resume continuity
- touches observability
- does not require migrating the full system at once

### Proof criteria `(GOV-04, SELF-07)`

The pilot passes only if all are proven:

1. A run survives worker/process restart without losing state.
2. Approval pause waits without custom polling loop.
3. Resume continues from stored workflow state, not reconstructed context.
4. Retries occur at step boundaries without duplicating successful prior work.
5. Operator can inspect run history, waiting reason, retry attempts, and completion path.
6. Zo dispatch remains an adapter, not the new source of orchestration truth.

### Rollback path `(ARCH-09, GOV-06)`

Rollback is simple:

- keep current Render-centered Paperclip path intact during pilot
- mirror the chosen heartbeat path behind a feature flag / workflow selector
- route only one workflow type through Inngest first
- if proof fails, disable the new workflow and continue on the current path while retaining the research result

Do **not** delete the existing path until the pilot proves continuity, waits, and observability under restart conditions.

## Decision Summary

### Ranked recommendation

1. **Mixed architecture with Inngest as durable execution owner**
2. **Mixed architecture with Trigger.dev as second choice**
3. **Temporal-backed Paperclip if the system later proves to need maximum rigor over simplicity**
4. **Render-centered Paperclip only as a temporary host architecture, not the durable substrate strategy**
5. **LangGraph as a nested agent runtime, not the primary workflow owner**

### Important governance constraint

Under the current Architecture Governance skill, production introduction of a new platform outside **Zo / Modal / Render** requires explicit approval.

That means:

- the **best research recommendation** is still **Inngest-backed Paperclip**
- but the **best currently approved in-boundary answer** is only: **do not let Render pretend to be the durable engine; treat it as a host, freeze further custom durability expansion, and seek approval before committing to a new substrate**

Stated differently:

**Within the currently approved pillars alone, there is no clearly sufficient native durable-workflow substrate for Paperclip's full requirements.**

That is a valid research conclusion. It should not be papered over by pretending Render workers or Modal jobs solve the missing semantics. `(CORE-06, GOV-08, GOV-09)`

## Open Questions

These do not block the recommendation, but they do affect pilot design:

1. Whether external specialist substrates beyond Zo / Render / Modal are acceptable for production adoption, not just research evaluation.
2. Whether Paperclip wants approval semantics modeled as pure events, synchronous updates, or both.
3. Whether the current Paperclip DB should remain the system of record for workflow summaries while the substrate owns execution history.

## Evidence Notes

This memo is based on official documentation for:

- Temporal workflows, event history, message passing, and visibility
- Trigger.dev waits, idempotency, replay, and observability
- Inngest durable execution, steps, waits, and traces
- LangGraph durable execution, persistence, interrupts, and LangSmith deployment
- Render workers, API, and environment configuration

No implementation claims are made here. This is a research recommendation only.

## Sources

1. https://docs.temporal.io/
2. https://docs.temporal.io/workflows
3. https://docs.temporal.io/encyclopedia/event-history
4. https://docs.temporal.io/encyclopedia/workflow-message-passing
5. https://docs.temporal.io/visibility
6. https://trigger.dev/docs/how-it-works
7. https://trigger.dev/docs/wait
8. https://trigger.dev/docs/wait-for-token
9. https://trigger.dev/docs/idempotency
10. https://trigger.dev/docs/v3/reattempting-replaying
11. https://trigger.dev/docs/logging
12. https://www.inngest.com/docs/learn/how-functions-are-executed
13. https://www.inngest.com/docs/guides/multi-step-functions
14. https://www.inngest.com/docs/learn/inngest-steps
15. https://www.inngest.com/docs/guides/error-handling
16. https://www.inngest.com/docs/platform/monitor/traces
17. https://www.inngest.com/docs/platform/monitor/observability-metrics
18. https://www.inngest.com/docs/learn/serving-inngest-functions
19. https://docs.langchain.com/oss/javascript/langgraph/durable-execution
20. https://docs.langchain.com/oss/javascript/langgraph/persistence
21. https://docs.langchain.com/oss/javascript/langgraph/human-in-the-loop
22. https://docs.langchain.com/langsmith/deployments
23. https://render.com/docs/background-workers
24. https://render.com/docs/api
25. https://render.com/docs/configure-environment-variables
26. https://render.com/docs/blueprint-spec
