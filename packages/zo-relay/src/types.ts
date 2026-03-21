import { createHash } from "node:crypto";
import { z } from "zod";

export const issueStatusSchema = z.enum([
  "backlog",
  "todo",
  "in_progress",
  "in_review",
  "blocked",
  "done",
  "cancelled",
]);

export const zoScenarioSchema = z.enum([
  "general",
  "code-generation",
  "code-review",
  "architecture-planning",
  "research",
  "scoring-evaluation",
  "data-processing",
]);

export const relayOptionsSchema = z.object({
  schemaVersion: z.literal("v1"),
  executionMode: z.literal("heartbeat"),
  paperclipBaseUrl: z.string().url(),
  paperclipCompanyId: z.string().uuid().nullable().optional(),
  paperclipAgentKeyRef: z.string().min(1),
  zoPersonaId: z.string().min(1).nullable().optional(),
  zoPersonaName: z.string().min(1).nullable().optional(),
  zoModelScenario: zoScenarioSchema,
  timeoutMs: z.number().int().positive().max(120000).optional().default(45000),
  maxAttempts: z.number().int().positive().max(3).optional().default(2),
  taskIdentityPreference: z
    .array(z.enum(["issueId", "taskKey", "runId"]))
    .min(1)
    .optional()
    .default(["issueId", "taskKey", "runId"]),
});

export const paperclipWakePayloadSchema = z.object({
  agentId: z.string().uuid(),
  runId: z.string().uuid(),
  context: z.record(z.unknown()).default({}),
  relay: relayOptionsSchema,
});

export const relayActionSchema = z.object({
  type: z.enum(["comment_issue", "update_issue_status", "no_op"]),
  issue_id: z.string(),
  body_markdown: z.string(),
  next_status: z.string(),
});

export const zoStructuredOutputSchema = z.object({
  outcome: z.enum(["completed", "needs_input", "blocked", "failed"]),
  summary_markdown: z.string(),
  paperclip_actions: z.array(relayActionSchema),
  continuity: z.object({
    should_continue: z.boolean(),
    continuation_hint: z.string(),
  }),
});

export const relayResultSchema = z.object({
  status: z.enum(["success", "retryable_failure", "terminal_failure"]),
  runId: z.string().uuid(),
  agentId: z.string().uuid(),
  continuityKey: z.string().min(1),
  zoConversationId: z.string().nullable(),
  zoOutcome: z.enum(["completed", "needs_input", "blocked", "failed"]).nullable(),
  summaryMarkdown: z.string(),
  paperclipActions: z.array(relayActionSchema),
  attemptCount: z.number().int().positive(),
  failureCode: z.string().nullable(),
  failureDetail: z.string().nullable(),
});

export type RelayOptions = z.infer<typeof relayOptionsSchema>;
export type PaperclipWakePayload = z.infer<typeof paperclipWakePayloadSchema>;
export type RelayAction = z.infer<typeof relayActionSchema>;
export type ZoStructuredOutput = z.infer<typeof zoStructuredOutputSchema>;
export type RelayResult = z.infer<typeof relayResultSchema>;
export type ZoScenario = z.infer<typeof zoScenarioSchema>;
export type IssueStatus = z.infer<typeof issueStatusSchema>;

export type ContinuityRecord = {
  continuityKey: string;
  agentId: string;
  issueId: string | null;
  taskKey: string | null;
  latestRunId: string;
  zoConversationId: string;
  lastZoOutcome: ZoStructuredOutput["outcome"];
  lastSummarySha256: string;
  lastTouchedAt: string;
  expiresAt: string | null;
};

export const zoAskOutputFormat = {
  type: "object",
  properties: {
    outcome: {
      type: "string",
      enum: ["completed", "needs_input", "blocked", "failed"],
    },
    summary_markdown: { type: "string" },
    paperclip_actions: {
      type: "array",
      items: {
        type: "object",
        properties: {
          type: {
            type: "string",
            enum: ["comment_issue", "update_issue_status", "no_op"],
          },
          issue_id: {
            type: "string",
            description: "UUID of the issue to act on, or empty string when no issue applies.",
          },
          body_markdown: {
            type: "string",
            description: "Markdown comment body, or empty string when not needed.",
          },
          next_status: {
            type: "string",
            enum: ["", "backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled"],
          },
        },
        required: ["type", "issue_id", "body_markdown", "next_status"],
      },
    },
    continuity: {
      type: "object",
      properties: {
        should_continue: { type: "boolean" },
        continuation_hint: {
          type: "string",
          description: "Empty string when there is no continuation hint.",
        },
      },
      required: ["should_continue", "continuation_hint"],
    },
  },
  required: ["outcome", "summary_markdown", "paperclip_actions", "continuity"],
} as const;

export function sha256(input: string): string {
  return createHash("sha256").update(input).digest("hex");
}
