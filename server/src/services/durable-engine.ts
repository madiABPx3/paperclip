import { Inngest } from "inngest";
import type { Db } from "@paperclipai/db";
import { approvals, heartbeatRuns } from "@paperclipai/db";
import { and, desc, eq, inArray, isNull, sql } from "drizzle-orm";
import {
  approvalResolvedEventDataSchema,
  buildApprovalResolvedEventId,
  buildApprovalResumeKey,
  buildHeartbeatRequestedEventId,
  durableEngineSchema,
  heartbeatRequestedEventDataSchema,
  paperclipApprovalResolvedEventName,
  paperclipHeartbeatRequestedEventName,
  type ApprovalResolvedEventData,
  type DurableEngine,
  type HeartbeatRequestedEventData,
} from "@paperclipai/shared";
import { logger } from "../middleware/logger.js";

export const APPROVAL_WORKFLOW_METADATA_KEY = "__paperclipWorkflow";

const inngest = new Inngest({
  id: process.env.INNGEST_APP_ID?.trim() || "paperclip-server",
  ...(process.env.INNGEST_EVENT_KEY?.trim()
    ? { eventKey: process.env.INNGEST_EVENT_KEY.trim() }
    : {}),
});

export function getDurableEngine(): DurableEngine {
  const parsed = durableEngineSchema.safeParse(process.env.DURABLE_ENGINE?.trim() || "legacy");
  return parsed.success ? parsed.data : "legacy";
}

export function isInngestPilotEnabled() {
  return getDurableEngine() === "inngest-pilot";
}

export function withApprovalWorkflowMetadata(
  payload: Record<string, unknown>,
  meta: { runId?: string | null } | null | undefined,
) {
  if (!meta?.runId) return payload;
  return {
    ...payload,
    [APPROVAL_WORKFLOW_METADATA_KEY]: {
      ...(readApprovalWorkflowMetadata(payload) ?? {}),
      runId: meta.runId,
    },
  };
}

export function readApprovalWorkflowMetadata(payload: Record<string, unknown> | null | undefined) {
  const raw = payload?.[APPROVAL_WORKFLOW_METADATA_KEY];
  if (!raw || typeof raw !== "object") return null;
  const runId = typeof (raw as Record<string, unknown>).runId === "string"
    ? (raw as Record<string, unknown>).runId
    : null;
  if (!runId) return null;
  return { runId } as { runId: string };
}

export async function publishHeartbeatRequestedEvent(
  run: typeof heartbeatRuns.$inferSelect,
  contextSnapshot: Record<string, unknown> | null | undefined,
) {
  const invocationSource = heartbeatRequestedEventDataSchema.shape.invocationSource.parse(run.invocationSource);
  const triggerDetail =
    run.triggerDetail == null
      ? null
      : heartbeatRequestedEventDataSchema.shape.triggerDetail.unwrap().parse(run.triggerDetail);
  const data = heartbeatRequestedEventDataSchema.parse({
    schemaVersion: "v1",
    companyId: run.companyId,
    agentId: run.agentId,
    runId: run.id,
    invocationSource,
    triggerDetail,
    issueId: typeof contextSnapshot?.issueId === "string" ? contextSnapshot.issueId : null,
    taskKey: typeof contextSnapshot?.taskKey === "string" ? contextSnapshot.taskKey : null,
    requestedAt: new Date(run.createdAt).toISOString(),
  } satisfies HeartbeatRequestedEventData);

  const eventId = buildHeartbeatRequestedEventId(run.id);
  await inngest.send({
    id: eventId,
    name: paperclipHeartbeatRequestedEventName,
    data,
  });

  return eventId;
}

export async function publishApprovalResolvedEvent(data: ApprovalResolvedEventData) {
  const parsed = approvalResolvedEventDataSchema.parse(data);
  const eventId = buildApprovalResolvedEventId(
    parsed.approvalId,
    parsed.decidedAt ?? new Date().toISOString(),
  );
  await inngest.send({
    id: eventId,
    name: paperclipApprovalResolvedEventName,
    data: parsed,
  });
  return eventId;
}

export async function findPendingApprovalForRun(db: Db, runId: string) {
  return db
    .select()
    .from(approvals)
    .where(
      and(
        inArray(approvals.status, ["pending", "revision_requested"]),
        sql`${approvals.payload} -> ${APPROVAL_WORKFLOW_METADATA_KEY} ->> 'runId' = ${runId}`,
      ),
    )
    .orderBy(desc(approvals.updatedAt), desc(approvals.createdAt))
    .limit(1)
    .then((rows) => rows[0] ?? null);
}

export async function attachHeartbeatDispatchMarker(db: Db, runId: string, marker: string) {
  await db
    .update(heartbeatRuns)
    .set({
      externalRunId: marker,
      updatedAt: new Date(),
    })
    .where(and(eq(heartbeatRuns.id, runId), isNull(heartbeatRuns.externalRunId)));
}

export function buildApprovalResolvedPayload(input: {
  companyId: string;
  approvalId: string;
  runId: string;
  status: "approved" | "rejected" | "revision_requested";
  decisionNote: string | null;
  decidedAt: Date | null;
  decidedByUserId: string | null;
  requestingAgentId: string | null;
  issueIds: string[];
}) {
  return approvalResolvedEventDataSchema.parse({
    schemaVersion: "v1",
    companyId: input.companyId,
    approvalId: input.approvalId,
    runId: input.runId,
    resumeKey: buildApprovalResumeKey({
      companyId: input.companyId,
      runId: input.runId,
      approvalId: input.approvalId,
    }),
    status: input.status,
    decisionNote: input.decisionNote,
    decidedAt: input.decidedAt ? input.decidedAt.toISOString() : null,
    decidedByUserId: input.decidedByUserId,
    requestingAgentId: input.requestingAgentId,
    issueIds: input.issueIds,
  });
}

export function logDurableEngineFallback(input: {
  surface: "heartbeat" | "approval";
  runId?: string | null;
  approvalId?: string | null;
  err: unknown;
}) {
  logger.warn(
    {
      surface: input.surface,
      runId: input.runId ?? null,
      approvalId: input.approvalId ?? null,
      err: input.err,
    },
    "inngest pilot dispatch failed; falling back to legacy execution path",
  );
}

export { inngest };
