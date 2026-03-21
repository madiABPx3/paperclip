import type { PaperclipAgentRecord, IssueHeartbeatContext } from "./paperclip-client.js";
import type { PaperclipWakePayload } from "./types.js";

function collectSkillPaths(agent: PaperclipAgentRecord): string[] {
  const metadata = agent.metadata ?? {};
  const skills = Array.isArray(metadata.skills) ? metadata.skills : [];
  return skills
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .map((skill) => `/home/workspace/Skills/${skill}/SKILL.md`);
}

export function buildHeartbeatPrompt(input: {
  payload: PaperclipWakePayload;
  agent: PaperclipAgentRecord;
  issueContext: IssueHeartbeatContext | null;
}): string {
  const { payload, agent, issueContext } = input;
  const skillPaths = collectSkillPaths(agent);
  const contextJson = JSON.stringify(payload.context, null, 2);
  const issueJson = JSON.stringify(issueContext, null, 2);

  const skillInstructions = skillPaths.length > 0
    ? skillPaths.map((path) => `- Read ${path} if it exists and apply it only when relevant.`).join("\n")
    : "- No agent-specific skills were declared in Paperclip metadata.";

  return [
    "You are executing a Paperclip heartbeat through a Render relay.",
    "",
    "Operating rules:",
    "- Read /home/workspace/ender/lessons.md before acting.",
    skillInstructions,
    "- Work from the provided Paperclip context first; do not invent missing issue facts.",
    "- Use tools when needed to inspect files, services, or logs.",
    "- Prefer comment-only updates unless a status change is clearly justified by completed work or a durable blocker.",
    "- If you are blocked on missing information, return outcome 'needs_input' and explain the missing input in the comment body.",
    "- Return outcome 'failed' only for genuine execution failure, not for ordinary blockers.",
    "",
    "Relay execution context:",
    `- agentId: ${payload.agentId}`,
    `- runId: ${payload.runId}`,
    `- executionMode: ${payload.relay.executionMode}`,
    "",
    "Agent record from Paperclip:",
    JSON.stringify(
      {
        id: agent.id,
        name: agent.name,
        role: agent.role,
        capabilities: agent.capabilities,
        metadata: agent.metadata,
      },
      null,
      2,
    ),
    "",
    "Heartbeat context payload from Paperclip:",
    contextJson,
    "",
    "Issue heartbeat context from Paperclip:",
    issueContext ? issueJson : "null",
    "",
    "Required output behavior:",
    "- `summary_markdown` should be a concise markdown summary of the work you actually performed.",
    "- If an issue is in scope, include at least one `paperclip_actions` item so Paperclip receives a visible update.",
    "- Set top-level `outcome` to exactly one of: `completed`, `needs_input`, `blocked`, `failed`.",
    "- Every `paperclip_actions` item must use the exact key name `type` (not `action`).",
    "- Always include a top-level `continuity` object with `should_continue` and `continuation_hint`.",
    "- Use `comment_issue` for narrative updates.",
    "- Use `update_issue_status` only when the issue status should change now.",
    "- Use `no_op` only when no issue exists in scope.",
    "- The structured output schema does not support nulls: use empty strings for `issue_id`, `body_markdown`, `next_status`, and `continuation_hint` when a field is not applicable.",
  ].join("\n");
}
