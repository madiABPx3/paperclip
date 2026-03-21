# Paperclip Durable Execution: Proven Patterns Research

Last updated: 2026-03-21 UTC

## Question

Before selecting Inngest specifically, what proven durable-execution patterns and existing solution classes already solve Paperclip's actual problem?

## Scope

This pass focuses on:

- approval waits
- pause / resume
- long-lived continuity
- retries without redoing successful work
- inspectable execution history
- zero-human operational recovery

It does **not** assume Inngest is the answer.

## First-Principles Conclusion

Paperclip's problem is an instance of **durable orchestration with external-event continuation**.

The proven pattern is not "host a worker and add more app logic."

The proven pattern is:

1. persist workflow state durably
2. model waiting as a native runtime primitive
3. resume via external event / signal / callback
4. keep successful prior steps from rerunning
5. expose execution history and status as first-class runtime state

That pattern shows up repeatedly across the strongest existing systems.

## Proven Pattern Families

### 1. Durable workflow engines with external events

This is the clearest and strongest pattern family.

Representative systems:

- Temporal
- Inngest
- Trigger.dev
- AWS Step Functions
- Azure Durable Functions / Durable Task Scheduler

Common traits:

- workflow state is persisted by the runtime
- waits do not require process residency
- resume happens via signal / event / callback token / external event
- retries are runtime-level, often step-level
- history is queryable and inspectable

This is the family Paperclip belongs to. `(CORE-06, CORE-07, WORK-09)`

### 2. Agent runtimes with interrupt/resume semantics

Representative systems:

- LangGraph
- Azure Agent Framework on Durable Functions

Common traits:

- strong at human-in-the-loop agent execution
- good for interrupting reasoning loops
- weaker when used as the entire business-workflow control plane unless paired with a durable orchestration substrate

This family is useful **inside** Paperclip workflows, but not clearly the best owner of all control-plane semantics.

### 3. Generic background-job hosts

Representative systems:

- Render workers
- cron jobs
- queue consumers

Common traits:

- good for executing work
- not enough by themselves for durable waits, replay, and long-lived workflow state

This family is a host pattern, not the answer to Paperclip's actual problem.

## What Official Sources Show

### Temporal

Temporal documents the exact pattern directly:

- workflow event history is durable
- signals / queries / updates are first-class messaging semantics
- long-running workflows are a primary use case
- human-in-the-loop is positioned as a native durable-orchestration fit

Interpretation:

Temporal is the canonical "maximum rigor" solution for this problem class.

### Inngest

Inngest documents:

- multi-step durable functions
- step-level retries and step memoization
- `step.waitForEvent()` for human-in-the-loop and external waits
- traces, metrics, and event audit surfaces

Interpretation:

Inngest is a strong modern expression of the same durable-event-workflow pattern, with lower apparent operational weight than Temporal.

### Trigger.dev

Trigger.dev documents:

- checkpointed long-running jobs
- wait primitives including token-based waits
- idempotency
- replay / reattempt tooling
- built-in logging and run observability

Interpretation:

Trigger.dev is also in the right pattern family. It appears especially strong when the team prefers a task-centric TypeScript background-job mental model.

### AWS Step Functions

AWS Step Functions provides a very explicit proof that the approval-wait pattern is long-solved:

- `waitForTaskToken`
- callback pattern for human approval
- long waits
- visible state-machine status

Interpretation:

This is strong evidence that Paperclip's needed primitives are not novel. But Step Functions would pull the system toward raw cloud platform gravity, IAM-heavy ops, and a much larger infrastructure surface than we want.

### Azure Durable Functions / Durable Task Scheduler

Azure Durable docs explicitly show:

- wait indefinitely or until timeout for human interaction
- external events to resume orchestrations
- persisted orchestration state while waiting
- dashboard / scheduler observability

Interpretation:

This is another strong proof that the substrate class is right: durable orchestration with external-event continuation. It is also evidence that agentic HITL patterns already exist atop durable orchestration, not as ad hoc app logic.

### LangGraph

LangGraph documents:

- durable execution
- persistence via checkpointers
- human-in-the-loop via interrupts

Interpretation:

LangGraph is real and useful, but its strongest fit is durable **agent execution**, not the whole Paperclip control plane by itself.

### Render

Render docs are strong on:

- background workers
- cron jobs
- hosting APIs and workers

But Render does not present itself as the durable workflow state machine for long-lived eventful orchestration in the same way these other systems do.

Interpretation:

Render remains a host, not the best durable orchestration owner.

## Synthesis: What Pattern Is Actually Proven?

The most proven pattern is:

**A dedicated durable workflow runtime owns orchestration state; domain services emit and consume events; execution adapters run actual work; approval or external input resumes the same run through a native event/signal primitive.**

That is the recurring shape across:

- Temporal
- Step Functions
- Azure Durable Functions
- Inngest
- Trigger.dev

This means the durable-workflow-engine decision is not speculative. What remains open is the **vendor / platform choice inside that proven pattern family**.

## What This Means for Paperclip

### Strong conclusion

Paperclip should not keep expanding custom durability logic on Render workers.

That is the anti-pattern consistently avoided by the proven solutions above.

### Strong but still provisional conclusion

Paperclip likely wants:

- Paperclip for policy/domain state
- a durable workflow engine for orchestration state
- Zo for execution
- Render only where hosting / adapters are needed

### What still needs narrowing

The remaining decision is not "durable engine or not."

That decision is already resolved by the research.

The remaining decision is:

1. **Inngest**: likely best simplicity / capability balance
2. **Trigger.dev**: likely best alternative if task-centric TS ergonomics matter most
3. **Temporal**: best if maximum rigor and long-term workflow criticality outweigh complexity

## Current Ranking After Proven-Pattern Research

### Pattern-class ranking

1. **Dedicated durable workflow engine**
2. **Agent runtime nested inside durable workflow engine**
3. **Background-job host with custom workflow semantics**

### Product ranking, provisional

1. **Inngest** remains the current leader
2. **Trigger.dev** remains a serious second
3. **Temporal** remains the high-rigor alternative
4. **LangGraph-only primary substrate** remains a poor fit for full control-plane ownership
5. **Render-centered custom durability** remains the wrong foundation

## What Would Change the Ranking

These findings could still move Inngest out of first place:

1. If its approval / resume model is weaker in practice than the docs imply
2. If its observability or replay surfaces are materially thinner than Trigger.dev or Temporal
3. If Paperclip needs stronger workflow mutation / versioning / multi-year execution guarantees than Inngest provides comfortably
4. If the required hosting or identity integration with Zo is meaningfully cleaner in Trigger.dev

## Recommended Next Research Slice

Before deciding on Inngest specifically, run one more narrowing pass on only these three:

1. Inngest
2. Trigger.dev
3. Temporal

And answer only these questions:

1. Approval wait semantics: what exactly resumes the run?
2. Replay semantics: what re-runs and what does not?
3. Versioning / migration semantics: what happens to in-flight workflows after deploys?
4. Observability depth: can an agent diagnose stuck waiting, retry storms, or replay confusion at 3 AM?
5. Operational boundary: what runtime must we host ourselves vs what the platform owns?

That pass should be enough to move from "pattern proven" to "vendor selected."

## Decision State

Status:

- **Durable-workflow-engine pattern**: effectively decided
- **Specific engine vendor**: not yet fully decided
- **Current front-runner**: Inngest
- **Highest-confidence negative decision**: do not keep building Paperclip durability directly on Render workers

## Sources

1. https://docs.temporal.io/workflows
2. https://docs.temporal.io/encyclopedia/event-history
3. https://docs.temporal.io/encyclopedia/workflow-message-passing
4. https://temporal.io/
5. https://www.inngest.com/docs/features/inngest-functions/steps-workflows/wait-for-event
6. https://www.inngest.com/docs/guides/multi-step-functions
7. https://www.inngest.com/docs/learn/inngest-steps
8. https://www.inngest.com/docs/platform/monitor/traces
9. https://trigger.dev/docs/wait
10. https://trigger.dev/docs/wait-for-token
11. https://trigger.dev/docs/idempotency
12. https://trigger.dev/docs/v3/reattempting-replaying
13. https://trigger.dev/docs/logging
14. https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
15. https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-human-approval.html
16. https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-external-events
17. https://learn.microsoft.com/es-es/azure/azure-functions/durable/durable-functions-human-interaction
18. https://learn.microsoft.com/en-us/agent-framework/tutorials/agents/orchestrate-durable-agents
19. https://docs.langchain.com/oss/javascript/langgraph/durable-execution
20. https://docs.langchain.com/oss/javascript/langgraph/human-in-the-loop
21. https://render.com/docs/background-workers
22. https://render.com/docs/cronjobs
23. https://render.com/docs/workflows
