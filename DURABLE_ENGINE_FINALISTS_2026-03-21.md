# Paperclip Durable Engine Finalists

Last updated: 2026-03-21 UTC

## Scope

This memo narrows the durable workflow decision to the three real finalists:

- Inngest
- Trigger.dev
- Temporal

It evaluates only the remaining tie-breakers:

1. approval / resume semantics
2. replay and versioning behavior
3. observability depth
4. operational boundary: what we still host and own

## Executive Read

### Current recommendation

**Inngest remains the best first choice.**

### Why

- It stays inside the proven durable-event-workflow pattern.
- Its wait / resume semantics fit Paperclip's approval-heavy flows directly.
- Its versioning model is explicit enough for long-lived workflows without Temporal's heavier determinism tax.
- Its hosting boundary is cleaner than self-hosting Trigger.dev or Temporal.
- It gives better "control-plane leverage per unit complexity" than the others. `(CORE-03, CORE-07)`

### Current ranking

1. **Inngest**
2. **Trigger.dev**
3. **Temporal**

## Comparison

| Dimension | Inngest | Trigger.dev | Temporal |
| --- | --- | --- | --- |
| **Approval / resume semantics** | Strongest fit. `step.waitForEvent()` directly models "pause until approval/event arrives," including HITL cases. | Strong. `wait.forToken()` is real and checkpointed, but the shape is more token/task-centric than event-native. | Strongest in theory. Signals / Updates / Queries are first-class, but the workflow model is more demanding to implement correctly. |
| **Replay / retry behavior** | Strong. Step state is stored; retries are step-aware; Replay is a first-class recovery surface. | Strong. Runs can be replayed and retries stay version-locked to the original run. | Excellent. Temporal's replay model is the most rigorous, but it comes with determinism and workflow-versioning discipline that is easy to misuse. |
| **Versioning / deploy behavior** | Good but opinionated. Docs explain how step IDs, step ordering, strict mode, and v2-style function cutovers should be handled. This is workable, but it does require explicit design discipline for long-lived runs. | Very good. Trigger.dev versions task deployments, locks runs to the version they started on, supports skip-promotion and later promote, and makes replay against current version explicit. | Excellent but highest complexity. Safe evolution is a core concern, but developer burden is also highest because workflow determinism rules are strict. |
| **Observability / stuck-run diagnosis** | Strong. Run details, traces, metrics, replay surfaces, and run inspection are all first-class. | Strong. Trace view, run inspector, alerts, deployment/run filtering, and run state inspection are excellent. | Strong. Event history and visibility are powerful, but the operator/developer learning curve is materially higher. |
| **Operational boundary** | Cleanest managed shape. Inngest hosts the durable execution engine; functions can be served from HTTP or container workers. | Cloud shape is good, but self-hosting docs explicitly shift availability, security, checkpoints, and scaling burden back to us. | Heaviest. Even with Temporal Cloud, we still host workers and absorb the conceptual/operational overhead of Temporal's programming model. |
| **Fit for Paperclip specifically** | Best. Paperclip is eventful and policy-driven. Inngest matches that naturally. | Good. Best if we prefer a TypeScript task-runner mental model and explicit deployment version controls. | Good for a larger/harder future Paperclip, but too heavy for the first migration. |

## Detailed Read

### 1. Approval / resume semantics

#### Inngest

Inngest's `step.waitForEvent()` is the cleanest semantic fit for Paperclip's core pattern:

- heartbeat requested
- wait for approval
- resume same run on approval-resolved event

That is exactly the way Paperclip already thinks.

#### Trigger.dev

Trigger.dev's wait model is real and durable. In Cloud, long waits are checkpointed and stop consuming compute. `wait.forToken()` is solid for approval gates.

But its center of gravity is still:

- task runs
- wait tokens
- parent/child task coordination

That is good, but slightly less natural than event-native continuation for Paperclip's domain shape.

#### Temporal

Temporal is fully capable here. Signals and updates are first-class and very powerful.

The issue is not capability. The issue is cost of correctness:

- stronger determinism model
- more room to create workflow-versioning pain
- higher engineering discipline required on every workflow evolution

### 2. Replay and versioning behavior

#### Inngest

Inngest docs are unusually explicit here:

- step identity matters
- adding steps can be safe but may warn
- strict mode can turn compatibility concerns into hard failures
- large logic changes are best handled by creating a new function version and replaying failed runs if needed

This is good and honest. It is not magic, but it is understandable.

Risk:

- long-lived workflows still require careful function design

Assessment:

- acceptable for Paperclip's first durable workflow layer

#### Trigger.dev

Trigger.dev is strongest on deployment version ergonomics:

- each deploy creates a new version
- runs lock to the version they started on
- retries stay on that original version
- skip-promotion and promote make rollout control explicit
- replay against current version is explicit

This is the cleanest deploy-story in the set for day-to-day operator control.

Assessment:

- Trigger.dev wins this category

#### Temporal

Temporal remains the most rigorous, but it expects the team to earn that rigor:

- deterministic workflow code
- careful safe-deployment discipline
- stronger modeling burden during workflow evolution

Assessment:

- best long-term rigor
- worst first-migration burden

### 3. Observability depth

#### Inngest

Strong enough for the Paperclip need:

- traces
- metrics
- run details
- retry visibility
- replay tooling

This is sufficient for 3 AM agent diagnosis if we also preserve Paperclip correlation IDs.

#### Trigger.dev

Also strong, and arguably best-looking operationally:

- real-time trace view
- run inspector
- deployment-aware filtering
- alerts via email / Slack / webhooks

This is a real strength and the main reason Trigger.dev stays close.

#### Temporal

Temporal gives deep visibility through workflow history and visibility/search surfaces.

But the cost is interpretive overhead: it is powerful, not lightweight.

### 4. Operational boundary

This is where the ranking stabilizes.

#### Inngest

Inngest's managed-platform story is straightforward:

- the Inngest platform hosts the durable execution engine
- we host functions using `serve()` or `connect()`
- functions are portable between those connection styles

That preserves portability and keeps the durable state machinery off our plate.

#### Trigger.dev

Trigger.dev Cloud is a good managed option, but the self-hosting docs are a warning sign for our standards:

- self-hosted shifts responsibility for security, uptime, and data integrity to us
- some cloud-only reliability features do not carry over cleanly
- self-hosting caveats are explicit and material

This does not kill Trigger.dev Cloud, but it makes the "easy fallback to self-hosting" materially worse than it sounds.

#### Temporal

Temporal is the most operationally serious choice:

- Temporal Cloud can host the service layer
- we still host workers
- the programming model itself is more operationally expensive

That is viable, but not the best first slice under current constraints.

## Final Recommendation

### Choose Inngest unless one of these becomes true:

1. We decide deployment-version ergonomics are the top priority and Trigger.dev's stronger version-locking model materially outweighs Inngest's event-native fit.
2. We learn that Paperclip's workflows need Temporal-grade rigor on workflow evolution, determinism, or multi-year execution sooner than expected.

### Why Inngest still wins

It is the best overall compromise:

- closest semantic fit to Paperclip
- native waits for approval/event continuation
- durable step model
- strong enough observability
- lower operational and conceptual burden than Temporal
- less mismatch than Trigger.dev

## Recommended Next Move

Proceed with Inngest as the selection **for pilot design**, not yet full migration.

Pilot target:

- `paperclip/heartbeat.requested`
- `paperclip/approval.resolved`
- Zo execution adapter
- Paperclip writeback adapter

Success criteria:

1. restart-safe continuity
2. event-native approval resume
3. no custom polling loop
4. inspectable run state
5. rollback to existing path via workflow selector

## Sources

1. https://www.inngest.com/docs/features/inngest-functions/steps-workflows/wait-for-event
2. https://www.inngest.com/docs/learn/versioning
3. https://www.inngest.com/docs/platform/replay
4. https://www.inngest.com/docs/platform/monitor/inspecting-function-runs
5. https://www.inngest.com/docs/platform/monitor/observability-metrics
6. https://www.inngest.com/docs/setup/connect
7. https://www.inngest.com/docs/learn/serving-inngest-functions
8. https://www.inngest.com/docs/platform/deployment
9. https://trigger.dev/docs/wait
10. https://trigger.dev/docs/wait-for-token
11. https://trigger.dev/docs/deployment/overview
12. https://trigger.dev/docs/runs
13. https://trigger.dev/docs/replaying
14. https://trigger.dev/docs/v3/troubleshooting-alerts
15. https://trigger.dev/docs/self-hosting/overview
16. https://docs.temporal.io/
17. https://docs.temporal.io/workflows
18. https://docs.temporal.io/encyclopedia/event-history
19. https://docs.temporal.io/encyclopedia/workflow-message-passing
20. https://render.com/docs/deploy-temporal
