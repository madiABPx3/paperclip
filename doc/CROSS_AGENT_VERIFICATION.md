# Cross-Agent Verification Protocol

**Version**: 1.0
**Date**: 2026-03-17
**Owner**: Architect (CTO)
**Governing principles**: WORK-04, ARCH-13, GOV-07, GOV-13, SELF-06

---

## Purpose

This protocol defines when, how, and by whom agent-produced work is independently verified before being marked `done`. It operationalizes WORK-04 (verification before done) and ARCH-13 (no agent consumes another's output without validation) within the Paperclip control plane.

**What this is NOT**: A checklist for agents reviewing their own work (that's SELF-06). This protocol governs *cross-agent* verification — a different agent evaluating the output.

---

## Protocol Participants

| Role | Agent | Persona | Responsibilities |
|------|-------|---------|-----------------|
| **Producer** | Builder (Engineer) | madi | Does the work. Provides evidence. Sets issue to `in_review`. |
| **Verifier** | Architect (CTO) | ender-verifier | Reviews evidence. Runs eval criteria. Approves or rejects. |
| **Escalation** | Ender (CEO) | ender | Resolves disputes. Unblocks deadlock. Final authority. |

---

## Section 1: Verification Triggers

### 1.1 Mandatory Verification (always requires Architect review)

Work MUST go through cross-agent verification before `done` when **any** of these apply:

| Trigger | Rationale | Principle |
|---------|-----------|-----------|
| Code deployed or modified in `lib/`, `config/`, or `Skills/` | Meta-layer changes affect all agents | WORK-10 |
| New dependency introduced | Requires boundary check | GOV-08 |
| Architecture decision made | No self-referential governance | GOV-13 |
| Security-sensitive change (auth, tokens, permissions) | Safety bar ≥ 0.95 | ARCH-16, GOV-07 |
| New zo.space route deployed | Affects public surface | ARCH-09 |
| Agent configuration modified (persona, rules, skills) | Config-as-code | GOV-15 |
| Score or eval result self-reported | Score inflation risk | eval_registry meta.score_recomputation |
| Governance exceptions recorded | Requires independent confirmation | GOV-14 |

### 1.2 Optional Verification (Producer may request)

- Exploratory research outputs the Producer is uncertain about
- Complex multi-file changes where self-review found edge cases
- Any output where the Producer wants a second opinion

### 1.3 Verification NOT Required

- Status updates, issue comments, or coordination-only work
- Reading files, running health checks, reporting metrics
- Work already verified in a prior cycle with no changes since

---

## Section 2: Evidence Standard

Before setting an issue to `in_review`, the Producer **MUST** post an issue comment containing all of the following. Absence of any required field is an automatic reject.

### 2.1 Required Evidence Fields

```
## Verification Request

**Work summary**: [1-3 sentences describing what was done]
**Changed artifacts**: [list of file paths or systems modified]
**Governing principles cited**: [list of principle IDs, e.g., CORE-07, ARCH-08]
**Tests / verification run**: [command + output showing it works, or "N/A — no executable test applicable"]
**Self-review gaps**: [anything the Producer flagged as uncertain or unverified — be honest]
**Eval scenario**: [which scenario from eval_registry.yml applies, e.g., code_generation]
```

### 2.2 Evidence Quality Bar

- **"Tests run"**: Must show actual output, not just "ran successfully." Paste the key lines.
- **"Principles cited"**: Must cite specific IDs (CORE-01, not "the core principles").
- **"Self-review gaps"**: Must be honest. An empty gaps section with complex work is itself a red flag.
- **Eval scenario**: Must match the work type. If unsure, use `agent_behavior` as fallback.

---

## Section 3: Verifier Checklist

When the Architect receives an `in_review` issue, this checklist drives the review. All items must pass for an approval.

### 3.1 Evidence Completeness (deterministic — run first, no LLM needed)

- [ ] All required evidence fields present in the issue comment
- [ ] Principle IDs are valid registry IDs (not generic references)
- [ ] Test output is present (not just "tests passed")
- [ ] Changed artifacts list is non-empty for code changes

**Gate**: If any field missing → immediate `reject` with specific field name. Do not proceed.

### 3.2 Correctness Check (aligned to eval registry scenario)

Run against the scenario declared by the Producer:

| Scenario | Key checks |
|----------|-----------|
| `code_generation` | Does it compile/parse? Does it handle declared inputs? Spec compliance ≥ 0.80? |
| `agent_behavior` | Task completed without overstepping permission scope? No denied actions taken? |
| `config_audit` | Reported discrepancies trace to specific principle IDs? No invented problems? |
| `research_quality` | Claims cite authoritative sources? Goes beyond surface level? |
| `data_synthesis` | No data loss? Sources cited via footnotes? |
| `content_quality` | Completeness ≥ 0.80? Key gaps acknowledged? |

### 3.3 Safety Check (always runs, regardless of scenario)

- [ ] No secrets exposed (env var values in logs, comments, or output)
- [ ] No destructive operations without confirmation trail in comments
- [ ] No actions outside declared permission scope (check against GOV-07 scope)
- [ ] No external calls to unauthorized services

**Safety bar**: 0.95 (higher than default 0.90). Any safety failure → immediate `reject`.

### 3.4 Principle Compliance Check

- [ ] Decisions in the work cite specific principle IDs (WORK-09)
- [ ] No obvious principle violations in the changed artifacts
- [ ] If any exception to a principle was taken, it's documented (GOV-14)

### 3.5 Score Inflation Check (when Producer self-reported a score)

- [ ] Recompute the score independently from evidence (NEVER accept Producer's number)
- [ ] If delta > 0.10 from Producer-reported → flag the inflation in the rejection comment
- [ ] Recomputed score must meet the scenario threshold from eval_registry.yml

---

## Section 4: Verification Outcomes

### 4.1 Approve

All checklist items pass.

**Actions**:
1. Post approval comment: `## Verification: APPROVED\n[brief rationale, key checks that passed]`
2. Set issue status to `done`
3. If a Paperclip approval was gated on this: resolve the approval

### 4.2 Reject

One or more checklist items fail.

**Actions**:
1. Post rejection comment:
   ```
   ## Verification: REJECTED

   **Failed checks**: [list each failed item]
   **Required to re-submit**: [exactly what Producer must fix/add]
   **Principle refs**: [principle IDs for each failure]
   ```
2. Set issue status back to `in_progress` (NOT `todo` — work is not restarted, just revised)
3. Do NOT set to `blocked` unless the failure is outside Producer's control

### 4.3 Conditional Approval (rare)

Work is functionally correct but has minor gaps that don't affect safety or correctness.

**Actions**:
1. Post comment: `## Verification: CONDITIONALLY APPROVED\n[what passed, what needs follow-up]`
2. Set issue to `done`
3. Create a follow-up issue for the unresolved minor gaps
4. Only use this when gaps are documented and non-blocking (e.g., missing a `governing_principle` citation on a metric, not a missing safety check)

---

## Section 5: Paperclip Issue State Machine

```
todo
  │
  ▼ (Producer picks up)
in_progress
  │
  ▼ (Producer posts evidence comment)
in_review ←─────────────────────────────────────┐
  │                                              │ (Verifier rejects → Producer revises)
  │ (Verifier reviews)                           │
  ├── APPROVED → done                            │
  │                                              │
  ├── REJECTED → in_progress ──────────────────→─┘
  │
  └── BLOCKED → blocked (external dependency, not a quality failure)
```

**SLA**: Verifier must review within the next heartbeat cycle after `in_review` is set (≤4 hours). If not reviewed within 8 hours, Ender is notified via issue comment.

---

## Section 6: Escalation Path

### 6.1 Dispute Resolution

If Producer disagrees with a rejection:
1. Producer posts a rebuttal comment citing specific principle IDs that support their work
2. Verifier reviews rebuttal and either: maintains rejection (with updated rationale) or flips to approval
3. If still disputed after one rebuttal cycle → escalate to Ender via Paperclip approval request

### 6.2 Deadlock Prevention

If a rejection loop exceeds 3 cycles on the same issue:
1. Architect posts to Ender: `## Deadlock Alert: Issue [id] has cycled 3+ times. Requesting Ender decision.`
2. Creates a Paperclip approval request with type `approve_ceo_strategy`, including both Producer and Verifier positions
3. Ender makes the final call

### 6.3 Verifier Unavailable

If the Architect agent is not responding within 8 hours of `in_review`:
- Ender may perform the verification using the ender-verifier persona
- This is recorded as a GOV-14 exception (self-referential verification, temporary)

---

## Section 7: Integration with Eval Registry

The verification protocol uses `config/eval_registry.yml` as the authoritative source for thresholds. Verifiers do NOT hardcode their own thresholds.

**Lookup pattern**:
```
1. Get the scenario from Producer's evidence comment
2. Look up scenario in eval_registry.yml → get required metrics + thresholds
3. Check ender-verifier agent overrides (higher safety: 0.95, task_completion: 0.85)
4. Apply all required metrics. Non-required metrics are advisory.
5. Any required metric below threshold = fail.
```

**Score recomputation**: The eval registry's `meta.score_recomputation: true` applies unconditionally. Verifiers always compute independently, never copy Producer's score.

---

## Section 8: Heartbeat Prompt Integration

The webhook at `/api/paperclip-heartbeat` injects verification duties into the Architect's heartbeat prompt. The relevant injection block:

```
VERIFICATION DUTIES (WORK-04):
When you find issues with status "in_review" assigned to other agents:
1. Read the most recent issue comment for the evidence package
2. Check all items in the Cross-Agent Verification Protocol (paperclip/doc/CROSS_AGENT_VERIFICATION.md)
3. Post an approval or rejection comment with specific findings
4. Update issue status: approved→done, rejected→in_progress
5. Eval thresholds: use config/eval_registry.yml scenarios, apply ender-verifier overrides
6. Never trust self-reported scores — always recompute from evidence (eval_registry meta.score_recomputation)
```

---

## Appendix A: Quick Reference Card

**Producer (Builder) before setting `in_review`**:
1. Post evidence comment with all 6 required fields
2. Be honest about gaps — the verifier will find them anyway
3. Set status to `in_review`

**Verifier (Architect) when picking up `in_review`**:
1. Check evidence completeness (if missing field → reject immediately)
2. Run scenario-specific correctness checks
3. Run safety check (always, threshold 0.95)
4. Check principle compliance
5. Recompute any self-reported scores
6. Post approval/rejection comment with specific findings
7. Update issue status

**Never**:
- Mark `done` without verification for mandatory-trigger work
- Accept self-reported scores without recomputation
- Approve work with safety failures
- Approve work with missing evidence fields

---

## Appendix B: Example Evidence Comment (reference)

```markdown
## Verification Request

**Work summary**: Implemented Paperclip health endpoint at /api/paperclip-health.
Returns JSON with status, agent count, and open issues. Registered in systems.yml.

**Changed artifacts**:
- zo.space route: /api/paperclip-health (new API route)
- config/systems.yml: added health endpoint field for paperclip system

**Governing principles cited**: CORE-08 (agent-discoverable), ARCH-01 (API-first),
ARCH-08 (observability)

**Tests / verification run**:
```
curl https://abp.zo.space/api/paperclip-health
{"status":"ok","agents":3,"open_issues":4,"timestamp":"2026-03-17T05:00:00Z"}
```

**Self-review gaps**: The endpoint makes a live call to localhost:3102 — if Paperclip
is down, the endpoint returns 503, which may be confusing to mission control. Not sure
if we should return a degraded status or a hard 503.

**Eval scenario**: agent_behavior
```
