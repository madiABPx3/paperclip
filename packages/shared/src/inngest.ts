import { z } from "zod";

export const durableEngineSchema = z.enum(["legacy", "inngest-pilot"]);

export const paperclipHeartbeatRequestedEventName = "paperclip/heartbeat.requested" as const;
export const paperclipApprovalResolvedEventName = "paperclip/approval.resolved" as const;

export const heartbeatRequestedEventDataSchema = z.object({
  schemaVersion: z.literal("v1"),
  companyId: z.string().uuid(),
  agentId: z.string().uuid(),
  runId: z.string().uuid(),
  invocationSource: z.enum(["timer", "assignment", "on_demand", "automation"]),
  triggerDetail: z.enum(["manual", "ping", "callback", "system"]).nullable(),
  issueId: z.string().uuid().nullable(),
  taskKey: z.string().min(1).nullable(),
  requestedAt: z.string().datetime(),
});

export const approvalResolvedEventDataSchema = z.object({
  schemaVersion: z.literal("v1"),
  companyId: z.string().uuid(),
  approvalId: z.string().uuid(),
  runId: z.string().uuid(),
  resumeKey: z.string().min(1),
  status: z.enum(["approved", "rejected", "revision_requested"]),
  decisionNote: z.string().nullable(),
  decidedAt: z.string().datetime().nullable(),
  decidedByUserId: z.string().nullable(),
  requestingAgentId: z.string().uuid().nullable(),
  issueIds: z.array(z.string().uuid()).default([]),
});

export type DurableEngine = z.infer<typeof durableEngineSchema>;
export type HeartbeatRequestedEventData = z.infer<typeof heartbeatRequestedEventDataSchema>;
export type ApprovalResolvedEventData = z.infer<typeof approvalResolvedEventDataSchema>;

export function buildHeartbeatRequestedEventId(runId: string) {
  return `heartbeat-requested:${runId}`;
}

export function buildApprovalResolvedEventId(approvalId: string, updatedAt: string) {
  return `approval-resolved:${approvalId}:${updatedAt}`;
}

export function buildApprovalResumeKey(input: {
  companyId: string;
  runId: string;
  approvalId: string;
}) {
  return `${input.companyId}:${input.runId}:${input.approvalId}`;
}
